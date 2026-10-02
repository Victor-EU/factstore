---
name: factstore-catalogue
description: Catalogue a company's systems into a factstore. Index each system's records under their own IDs, join them, resolve the same thing across systems (one product's codes in the shop, the marketplace, the warehouse and the factory; one customer with two accounts), and record which system owns which field. Use when asked to catalogue, index or map a company's data sources or exports into the fact store, or to re-run a catalogue after the sources change.
---

# Catalogue a company's systems

The store becomes the index of the company's systems. It holds every record that takes part in a join, under the ID its own system gives it, with refs to the records it names. That covers records others point at, such as customers, orders and products, and records that point at them, such as order lines naming an order and a product. It also holds what no single system knows: which records in different systems are the same thing. Nothing else. The output is ordinary facts written through `transact`.

You need the factstore MCP tools (`stats`, `search_attributes`, `register_attribute`, `transact`, `query`) and read access to the sources: exports, API reads, files. Beyond a few hundred facts you also need a shell with Python and the SDK (see Writing in bulk).

## Rules

1. **Read-only against sources.** Never write to a source system, and never edit, move or delete an export.
2. **Identifiers and join keys only, for records another system owns.** That means orders, customers, a warehouse's receipts, a marketplace's listings. Index the record's own ID and refs to the records it names; nothing else.
   - Names, emails, phones, addresses, amounts, statuses, quantities and free text stay in the source. Readers ask the source for them.
   - The reason: identifiers don't go stale, and personal data can't be un-copied.
3. **Never write personal data.** Use it in your working files to match records, for example two accounts with one mailbox. Write only the conclusion.
4. **Idempotent.** Address every entity by a lookup on an identity attribute, such as `["shopify/order_id", "6402103816881"]`.
   - Never use a temporary ID for a record that has an identifier.
   - A second run on unchanged sources must create nothing and write nothing.
5. **Reluctant to register.** Reuse before you register. Register only the identifiers and join keys the installed vocabulary lacks.

**Which sources.**
- **Systems are the catalogue's:** the shop, the marketplace, the warehouse, and an accounting system's vendor and customer lists.
- **Documents and messages are the ingestion skill's.** PDFs, chats and emails hold the records the store is primary for, such as purchase orders, shipments, inspections and customs entries. The vocabulary package's ingestion skill reads them into the store.
- **Read documents only to complete a hub's crosswalk:** a factory's item code and tariff code for a product, a supplier's name in each system. Create nothing else from them.
- **The general ledger is never indexed,** not even its IDs. That means bills, invoices, payments and journal entries. From an accounting system, index only its vendor and customer lists.

## Steps

### 0. Read the store

Before you open a source:
- Run `stats`.
- Run `search_attributes` for each system and each kind of record you expect, for example "shopify", "amazon", "warehouse", "sku", "supplier", "order", "customer".
- Read the installed vocabulary's docs.

On a re-run the store already holds the vocabulary and the crosswalk. Reuse them: query the crosswalk the store has rather than rebuilding it from nothing.

### 1. Enumerate sources

List each reachable source: the system, what it exports, and the kinds of record in it. Include hand-made sources such as folders of PDFs and chat exports. They hold identifiers no system has, like a factory's item codes.

### 2. Sample each source

For each file or endpoint, find:
- the kinds of record and their fields;
- which fields are identifiers;
- volumes.

Read a few records, not whole files: `head`, `wc -l`, and short scripts that count distinct values.

Before treating a field as an identifier, check that it is unique and never blank in that source. Note fields whose values look like another source's IDs. Those are join keys.

### 3. Map every field before registering anything

Write a mapping table in your working directory. Each field goes to one of three places:
- **An existing attribute.** Find it with `search_attributes`, and read its doc, not just its name.
- **A new identifier or join key.**
  - An identifier goes in the source system's namespace, with `unique: identity` and a doc naming the system and the record ("Shopify's ID for a customer account.").
  - A join key is a `ref` from the record to the record it names, such as `order/customer` or `line/sku`. A line of a whole is `core/part_of` the whole.
  - A record with no ID of its own still takes part in a join when it names other records, like a row in a warehouse's outbound file naming an order and an item. Index it under a key built from the fields that make it unique in its source, such as `#18301/ACMH-10021` for the order and the item code. Check that the key is unique before you use it.
  - Check a join key's values as you would an identifier's. A blank names nothing, so write no ref for it. A field holding several keys ("PO-1 / PO-2") is several refs, on a `many` attribute. Spellings need normalizing to the form the named record uses.
  - A ref by lookup creates the named record if the store lacks it, so a malformed value creates a bogus record.
  - Name a join key after the kind of record it is on and what it points to, such as `order/customer` or `receipt/shipment`. Reuse one across sources when the records are the same kind: a shop's and a marketplace's order lines can both use `line/sku`. Don't use a generic namespace shared by unrelated kinds of record.
- **Left in the source.** Most fields go here.

Register what is missing in one batch.

If registration is refused, read the near matches it returns and reuse one if its doc fits. Use `distinct_from` only when the meaning differs. Never use it to put the same kind of value on a second kind of entity.

### 4. Resolve identities

Within a source, the record's own ID is its identity. Lookups on it make re-runs update rather than duplicate.

Across sources, the same thing has an ID in each system. A product variant, for example, has:
- a shop's variant ID;
- a marketplace listing code, ASIN and FNSKU;
- the warehouse's item code;
- the factory's item code;
- a barcode.

Put them all on one entity, the hub, so a query can go from any system's ID to any other's. For products, the hub is the entity holding our own SKU code.

A product's crosswalk also ties it to the supply side. It records which supplier makes the product and its tariff (HS) code, if the vocabulary has attributes for them. Both are usually printed only on the factory's documents, next to the factory's item code, and they are what purchasing and customs data join through.

Match in tiers, strongest first, and keep a table of every match and its tier:

| Tier | Evidence | `core/confidence` |
|---|---|---|
| exact | The same identifier in both records: a barcode, or a code equal character for character. | 1 |
| normalized | Codes equal after normalizing case and separators, dropping a known suffix or prefix (`-FBA`), or swapping one pair of adjacent characters, where no other candidate comes as close. | 0.9 |
| corroborated | No shared code, but independent signals agree and nothing else fits: descriptions, the same quantities on the same order, dates. | 0.7 |

Don't write a match weaker than these. List it for a human.

How to write and check matches:
- **One transaction per tier.** Provenance belongs to the transaction, so add `{"e": "tmp:tx", "a": "core/confidence", "v": "0.9"}` to that tier's write.
- **One to one.** If two hubs claim the same warehouse code, one match is wrong. Find which before writing either.
- **Writing an ID onto a hub** looks like `{"e": ["sku/code", "AH-KTL-0001-BLK"], "a": "amazon/asin", "v": "B0..."}`. If that ID already sits on another entity, the kernel refuses, because it is an identity. Find out why: it is either a duplicate to merge or a wrong match.
- **Our own codes.** Systems may spell our code differently: case, a dropped zero, a typo, a suffix. The hub's code is the spelling the company uses most consistently. The variants are evidence for the match, not new hubs.
- **Composite identifiers.** When a code is unique only within something else, such as a factory's item code within that factory, write it as the vocabulary's doc says, for example `NBBW:MT-2231`.
- **Duplicates within one source,** such as one person with two customer accounts:
  - Keep both index entries.
  - Mark the newer one with `core/same_as` pointing at the account it duplicates, at the tier's confidence.
  - Do this only on strong evidence: the same mailbox once normalized, or the same full name and postal address.
  - Normalizing a mailbox means lowercasing it and dropping a plus-alias: `ann+shop@` is `ann@`. Drop dots only at providers that ignore them, such as Gmail. Elsewhere `ann.lee@` and `annlee@` are two mailboxes, often two people with the same name.
  - Compare in your working files. The store gets only the `core/same_as`.

### 5. Record field authority

For each attribute whose values a source owns, assert on the attribute's own entity which system is authoritative:

```json
{"e": ["fs/ident", "amazon/asin"], "a": "core/authoritative_source", "v": "amazon"}
```

Use one lowercase name per system, the same every time: shopify, amazon, 3pl, quickbooks.

### 6. Where sources disagree on a term, record each meaning

"SKU" may be a listing code with a suffix in the marketplace and a hand-typed client code in the warehouse. "On hand" may include damaged units in one system and not in another.

Don't pick one meaning and force the other into it:
- Each meaning is its own attribute in its system's namespace, with a doc saying whose meaning it is.
- Report the disagreement.

### 7. Check what you wrote

Each check looks for what a common mistake leaves in the store. Fix what you find before you report.

On a re-run, report what the checks find and change nothing. An earlier run's matches may rest on evidence your rules don't cover, such as one mailbox name at two providers, and a re-run on unchanged sources writes nothing (rule 4). The person decides.

- **Records a join key created by mistake.** A lookup creates the record it names, so a malformed value leaves a record holding nothing but that value. For each identity your join keys point at, list the values on records that hold nothing else:
  ```sql
  select k.v from "po/number" k
  where not exists (select 1 from facts f where f.e = k.e and f.a <> 'po/number')
  ```
  Compare them with the rest. A blank, a list ("PO-1 / PO-2") or an odd spelling is a bad join key: retract the ref, and write the right ones. A record that is bare because another skill fills it is expected, such as a PO a receipt names before ingestion reads the PO.
- **Duplicates.**
  - Count the `core/same_as` you wrote by the rule that matched each pair: the same mailbox, a normalized mailbox, or the same name and address.
  - From each rule's pairs, read ten against the source records. If any pair is two different people, the rule is wrong. Retract its matches, fix the rule and match again.
  - List any account that more than three others point at, through any number of `core/same_as` hops. It is more often a bad rule than one busy person.
- **Sources left out.** Every file in every source is either indexed or named in your report with the reason. A file whose rows have no ID of their own but name other records is not a reason (step 3).
- **Counts.** For each kind of record, the store holds as many as the source has distinct IDs.

## Writing in bulk

Use the MCP tools to explore and for small writes. For thousands of records, write a script in your working directory that uses the SDK:

```python
import factstore                     # the store in FACTSTORE_DSN
r = factstore.transact(facts)        # one transaction; facts as in the transact tool
factstore.query('select count(*) from "shopify/order_id"').rows
```

- Put 1,000 to 5,000 facts in each transaction. A rejected transaction writes nothing and lists every problem: fix the batch and run it again.
- Before a script writes a join key, print its distinct values that don't look like the IDs of the record they name: blanks, several IDs in one field ("PO-1 / PO-2"), and spellings unlike the rest. Split, normalize or skip each one, as step 3 says, before writing.
- Run the script on a small sample first, check the result with `query`, then run it in full.
- Record each export file you read as a document, and point every transaction written from it at that document:
  ```json
  {"e": ["document/hash", "<sha256 of the file's bytes, hex>"], "a": "document/url", "v": "shopify/orders.jsonl"},
  {"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", "<the same>"]}
  ```
- Facts you write about the same entity in different batches must agree. A cardinality-one attribute keeps only the last value written.

## Finish with a report

- Sources and record kinds indexed, with counts.
- The crosswalk: for each system, how many hubs carry its ID, by tier, and what is unmatched and why.
- Attributes registered, and why each was needed.
- Duplicates marked, by rule.
- The checks of step 7: what each found, and what you fixed.
- Terms the sources disagree on.
- Anything left for a human to decide.

## Re-running

Follow the same steps.
- Read the store first (step 0), and reuse its mapping and crosswalk.
- Keep the scope the store shows: the same sources and the same kinds of record as before. Index new records of those kinds. A source or kind of record the store doesn't have yet is a proposal for the person, not something to add on a re-run.
- Every write is a lookup, so unchanged records change nothing. Count entities before and after:
  ```sql
  select count(distinct e) from facts
  where e not in (select e from "fs/at") and e not in (select e from "fs/ident")
  ```
  This leaves out transactions and attributes. The count rises only by records that are new in the sources.
- A record gone from a source stays in the store, since it was true when seen. Report it.
- Run the checks of step 7, and report what they find without changing anything.
- A person excised from the store was also deleted in its source system. If you find them in a source again, report it instead of indexing them.
