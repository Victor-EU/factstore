# factstore — Design Doc

**Status:** Draft v0.7 · 2026-10-03
**Name:** `factstore`. A technical name, not a product name. Referred to below as *the kernel* when discussing Part I and *the store* when discussing what it holds.

**Naming scheme:**
- `factstore` — the kernel (Part I)
- `factstore-skills` — the catalogue, ontology and ingestion skills (Part III)
- `factstore-<package>` — a vocabulary package, e.g. `factstore-crm`, `factstore-ecom-ops`
- MCP server `factstore`, tools `transact`, `query`, `stats`, `search_attributes`, `register_attribute`, `excise`. Tool names are bare: the server name is already the namespace, and some clients reject dots in tool names.
- SDK `import factstore`, then `factstore.transact(...)`. Not `assert`, which is a Python keyword.

**Changes in v0.7:** what M6's five rounds found. Each ran one use case on public data from a real company ([evals/m6](evals/m6/README.md)). Round 4 read TV stations' orders and invoices, standing in for DocILE's supplier documents, and passed its mark on its last run.
- **The kernel's code didn't change.** Stores reached 3.2 million facts. What broke was skill text, a package's model, and what the MCP server tells an agent (§19).
- **The store's rules are in its MCP server's instructions** (§2, Part II): values, not copies of text; no personal data; each document once; every fact cites its document. They are the only guidance an agent with no skill reads. Without them, agents put people in the store.
- **A general ingestion skill,** `factstore-ingest`, for documents no package covers (§8).
- **The catalogue learned from real junk** (§6). A record is keyed by the IDs it names, never its row's position. An identifier holds only its own system's IDs. Every ID column is screened. Duplicates are compared on every address an account has used.
- **An Amazon listing is a record of its own** (§8, §14), since one ASIN can sit under two of a seller's codes.
- **What writing skills taught** (Part III).
- **Two new open questions** (§15).
  - Question 7 is personal data where the store is the source. The business that owns the store decides it, attribute by attribute, with `core/personal`. The default is none.
  - Question 8 is a vocabulary with no package. Open question 5 gains round 5's evidence.
- **The rounds' results** (§19).

**Changes in v0.6:** the decision after the first slice: change, then go ([evals/m5](evals/m5/README.md#after-the-decision)). Four changes, then the slice again on the fixture.
- **Business time for backfilled history is a convention** (Part II; open question 6, resolved). A document carries `document/issued_at`, and what was known on a date is the facts whose evidence was issued by then. The kernel is unchanged; `query`'s description and its as-of error point at the store's own dates.
- **The sales side's identifiers are a package,** `factstore-ecom-index` (§8). Every name the slice's runs had chosen for them is now refused as a near match.
- **Stock at factories and on the water is derived** (§14). factstore-ecom-ops no longer has stock attributes, and question 10 of the ten is now a derivation.
- **The catalogue checks its own output before it reports** (§6, step 7).
- **The slice again** (§18): three more runs, each from an empty store. Nothing was registered beyond the packages, all 16 of the operator's kinds were found, and in the last run the re-run wrote nothing and all ten questions were right on the first try.
- **factstore is MIT-licensed and not sold** (§13). Open question 5 asks whether a brand would adopt it, not pay for it.

**Changes in v0.5:** what building it found, up to the slice run on the synthetic fixture (build plan M1–M5, [evals/m5](evals/m5/README.md)). No partner data yet.
- **The kernel needed no change from the slice.** Part I stands as v0.4 wrote it, with two details the build settled:
  - registration's near-match check also catches a name whose words contain another's in the same namespace (§1);
  - a package's new version applies the evolutions §1 allows (§8).
- **Open question 2 resolved:** identifiers and join keys only (§6, §15). The slice answered every question its sources can answer, and wrote no personal data.
- **Backfilled history has no business time.** As-of reads when a fact was written, so a store built in October from a year of documents knows nothing "as of 1 July". Proposed: documents carry their date (Part II, open question 6).
- **Stock at factories and on the water is derived, not counted** (§14). No source counts it; POs and shipment lines imply it.
- **Proposed: the sales side's identifiers go in a package** (§8). Left to the catalogue, their names change from run to run.
- **Part III** gains what the skills learned: the catalogue's scope (§6), fragments in the ontology (§7), and what a package's skill must fill (§8).
- **The first slice's results on the fixture** (§18).

**Changes in v0.4:** the kernel's semantics, pinned down.
- `assert` renamed `transact`. Facts carry an `op` (assert or retract), so retraction has a representation.
- Cardinality `one` is last-writer-wins, stated.
- `actor` and `at` are stamped by the kernel and live in the reserved `fs/` namespace. Conventions move to `core/`.
- Attributes gain a required `doc` and optional `unique: identity`. Registration runs its own search and refuses near matches unless the caller names them.
- Value types: `number` becomes `decimal`; `date` splits into `date` and `instant`.
- Excision: the one way to physically remove data, itself recorded.
- Writes serialized in commit order; a current-state table beside the log.
- Conventions: correction vs supersession rule, `same_as` merge, several amounts per entity.
- Open questions 1, 2, 3 and 5 (v0.3 numbering) resolved; query language, index contents, backups and composite identity added. The first slice gains a WeChat export and measures.

**Changes in v0.3:** first-principles cut. The kernel is now three primitives and three calls. Everything v0.2 had pulled into the kernel is re-sorted into conventions (free), skills (procedures), or layers to build later. No idea was deleted; most were demoted. Named `factstore`.

---

## Aims

1. A flexible, universal data structure with attributes.
2. Enables a data catalogue / index when the company has external data sources.
3. Enables the ontology basic layer — entities and relationships. Logic is management work, built later with care.
4. Companies build an AI-native CRM, or data analytics, on top.

---

# Part I — The kernel (build this)

## 1. Primitives

### Fact
```
(entity, attribute, value, transaction, op)
```
One statement that an entity has a value for an attribute, asserted or retracted in a transaction. `op` is `assert` or `retract`. Append-only. There is no update and no overwrite. Correction is a new fact; retraction is a new fact with `op = retract`, leaving the original in place. The only physical removal is excision (§3).

**Entities** are opaque IDs allocated by the kernel. An entity is nothing but the facts about it.

**Current state.** For a `many` attribute, the current values are those asserted and not since retracted. For a `one` attribute, the current value is the latest assertion in transaction order, unless retracted: a new assertion replaces the old one. Between concurrent agents this is last-writer-wins, deliberately. Making a second assertion a recorded conflict instead (`once`) is a management-layer policy (§9).

### Attribute
An entity in its own right, registered before use, with:
- a **namespace** and name (`customer/email`, `invoice/number`)
- a **value type**: `string`, `decimal`, `boolean`, `date`, `instant`, or `ref` (a reference to another entity). `decimal` is exact (Postgres `numeric`); money is never a float. `date` is a calendar date; `instant` is a point in time with a timezone.
- a **cardinality**: `one` or `many`
- a **doc**: a required one-line description. It is what search runs over.
- a **uniqueness**: `none` (default) or `identity`. At most one entity holds a given value of an identity attribute, and `transact` can address an entity by it (§2).

Attributes are the alphabet. They are the one thing in the system that is deliberately expensive to extend. `register_attribute` runs a similarity search over existing names and docs itself. If there are near matches, it refuses unless the caller lists them in `distinct_from` — a recorded statement that the registrant saw them and means something else. Registration is a transaction like any other, so who registered what, and what they rejected, is in the log.

A near match is trigram similarity over names and docs, or, in the same namespace, a name whose words contain another's (`po/revised_etd` against `po/etd`). Synonyms such as `inventory/qty_on_hand` pass. Search still finds the existing attribute for them, so the registrant is expected to search first.

Attributes change in one direction only. Value type never changes. Cardinality may go from `one` to `many`. Uniqueness may be added if no existing values collide. A mistake is deprecated, not edited: `fs/replaced_by` (ref) on the old attribute points to the new one, search and `stats` follow it, and old facts stay.

The kernel's own attributes live in the reserved `fs/` namespace:
- the schema attributes above: `fs/ident` (the name), `fs/type`, `fs/cardinality`, `fs/doc`, `fs/unique`, `fs/distinct_from` and `fs/replaced_by`;
- the transaction stamps below;
- `fs/name`, an actor's display name;
- `fs/excised_entity` and `fs/excised_attribute`, which record an excision (§3).

The starter vocabulary (Part II) lives in `core/`.

### Transaction
An entity. The kernel stamps two attributes on it: `fs/actor`, taken from the authenticated credential — never from the payload — and `fs/at`, the commit time. Nothing else can write either. Credentials are issued to actors (a person, an agent, a package installer), and each actor is an entity. Anything else — evidence, reason, confidence, on whose behalf — is an ordinary attribute someone registers. Every fact belongs to exactly one transaction. Provenance is not a feature; it is the storage model.

Provenance attaches to the transaction, so it is exactly as fine-grained as the transaction. Facts with different evidence or confidence go in different transactions: fields extracted from one PDF at different confidence are several transactions, not one.

That is the whole structure. Entities and relationships (aim 3) require nothing further: a `ref` value is an edge, so the graph exists the moment refs do.

## 2. Calls

| Call | Does |
|---|---|
| `transact` | Submit assertions and retractions as one transaction. Validates value types, cardinality and uniqueness. Temporary IDs (`"tmp:order"`) let new entities in the same call refer to each other — an order and its line items in one write — and the kernel returns the mapping to real IDs. A lookup (`["shopify/order_id", "1234"]`) addresses an entity by an identity attribute and creates it if absent, so re-running an ingestion updates instead of duplicating. Returns what was accepted. `dry_run: true` reports what would happen without writing, including attributes that would need registering. |
| `query` | Facts, entities and traversals over refs, current state by default, with as-of (a transaction or a time). One read-only SQL statement over a view per attribute (§5). |
| `stats` | Attribute usage counts, co-occurrence of attributes on entities, and which attribute groups are connected by which refs. The raw material an agent reads to describe the ontology. |

Plus attribute registration (`search_attributes`, then `register_attribute`, which takes a batch so a package installs in one transaction) and `excise` (§3), which needs its own credential. Delivered as one MCP server (`factstore`) and a thin SDK (`import factstore`), with documentation written for models first.

The server's instructions state the store's rules (v0.7; Part II, *What goes in*), because they are the only guidance an agent with no skill reads. With a one-line instruction, agents ingesting a mailbox recorded people and copied message bodies (§19).

## 3. Invariants that cannot be retrofitted

Three things stay in even the smallest kernel, because adding them later is a migration nobody will do:

1. **Immutability.** No fact is ever changed in place. The only removal is excision, and excision is itself recorded.
2. **Every fact has a transaction, and the kernel says whose.** No anonymous writes, ever, and no self-declared actors. A log of claimed actors cannot be made trustworthy afterwards.
3. **Attributes are registered, namespaced and documented.** No free-form keys.

Remove any one of these and the result is a JSON file with extra steps.

Four decisions sit beside them, for the same reason — changing them later means rewriting history:

- **Exact types.** An amount stored as a float, or an ETA without a timezone, is wrong in every fact already written.
- **Unique identity.** Without it, idempotent ingestion is a race: two agents both find no entity for `shopify/order_id = 1234` and both create one. Duplicates already in the log cannot be told apart from real entities.
- **Excision.** Personal data can get into a store in two ways. One is a business deciding its store holds it, such as a supplier's contact (open question 7). The other is an agent that wasn't given the rules, as in two of round 5's runs (§19). GDPR, CCPA and PIPL require deleting it on request. `excise` takes an entity, optionally narrowed to attributes, deletes the matching facts, and records an excision transaction saying who, when, and which entity and attributes — never the values. Backups: open question 3.
- **Commit order.** Transaction IDs follow commit order, so an as-of query gives the same answer every time it runs (§5).

## 4. What the kernel does not know

The kernel has no concept of: money, documents, types, shapes, ownership, approval, conflict, policy, definition, identity propagation, or what a customer is. All of these are either conventions (Part II) or layers built on top (Part IV). The test for adding anything to Part I: *would Postgres add this?* Each kernel addition in v0.4 has a Postgres counterpart: `UNIQUE`, `DELETE`, `numeric`, `timestamptz`, `current_user`.

The server's instructions name core's conventions, such as `document/hash` and `core/evidence` (v0.7, §2), since `factstore init` always installs core. They are text an agent reads. The kernel's code still knows none of these names, and its tests run on stores without core.

## 5. Implementation
Postgres. Four indexes — by entity, by attribute, by value, by transaction. Boring on purpose.

- **Writes are serialized.** One writer at a time (an advisory lock around `transact`), with the transaction ID assigned inside it. Postgres sequences hand out numbers before commit, so without this, transaction 101 can commit before 100 and an as-of query returns different answers over time. At this scale a single writer costs nothing.
- **A current-state table** — the current values per entity and attribute — is updated in the same database transaction as the log. The log stays the source of truth. The table exists because filtering on several attributes over raw fact rows is where key-value storage in Postgres gets slow.
- **Reads are SQL over views.** Every attribute is a view named after it: `"po/status"(e, v, tx)` for current state, and `history."po/status"(e, v, tx, op)` for every fact in the log. Registration creates the views. An as-of read resolves the same names to a fold of the log up to one transaction. `query` runs one statement in a read-only transaction that is always rolled back.

A company whose fact log outgrows a single Postgres exports it to a real data platform; that is a feature, not a goal.

---

# Part II — Conventions (free)

Patterns expressed entirely with registered attributes, in the `core/` namespace. They cost no kernel code and the kernel does not know their names. A starter vocabulary ships them.

| Convention | How |
|---|---|
| What goes in (v0.7) | Stated in the MCP server's instructions, for every agent (§2). Identifiers, the refs between records, and the values someone will look up: a date, a quantity, a status, a deal number. Not copies of text: a body, a summary or a note stays in its document. No personal data: a person's name, address and phone stay in the source, unless the business has decided its store holds them (open question 7). A person is a record only under a system's ID, such as a shop's customer ID. Never under a name or an address, so the people a document names stay in it. Organisations are records. |
| Personal data a business allows (v0.7) | `core/personal` (boolean) on an attribute's own entity, written by the business's owner or a manager with their own credential. Without it, an attribute holds no personal data (open question 7). |
| Composition | `core/part_of` (ref, many) on the part. Line items, shipment contents. |
| Correction vs supersession | Fixing *our* recording error: a new fact on the same entity. The *world* reissuing something — a corrected invoice, a credit note: a new entity with `core/supersedes` (ref, one); the old one is untouched. |
| Entity merge | `core/same_as` (ref, one) on the duplicate, pointing at the survivor. Crosswalks will produce duplicates; nothing is rewritten, and queries follow `same_as`. |
| External identity / index | `shopify/order_id`, `stripe/customer_id` as identity attributes on the entity. **The catalogue is just facts.** An identifier holds only the IDs of the system its doc names (v0.7). The company's own codes and its join keys belong to no system: `sku/code` holds our code, whichever system it comes from. |
| Field authority | `core/authoritative_source` as a fact about the attribute entity. |
| Money | Each amount is a `decimal` attribute named for what it is (`invoice/subtotal`, `invoice/tax`, `invoice/total`); the entity carries one `core/currency` covering all of them. An amount in another currency goes on a part (`core/part_of`) with its own currency. A package rule, not a type. |
| Documents | An entity with `document/hash` and `document/url`; referenced via `core/evidence` on a transaction. A chat message or an email is a document of its own, so evidence points at the message, not the whole export. Each document once (v0.7): a mail client keeps one message in several folders, and its copies are one document, hashed by the first. A fact cites only a document that states it. |
| Domain time | `core/period`, `core/valid_from`, `core/valid_to` as ordinary `date` attributes, distinct from the transaction's `fs/at`. |
| Business time for backfilled history (v0.6) | `document/issued_at` (instant) on a document: when it was sent or signed. As-of reads when a fact was written, which is the day of ingestion for history read from old documents. What was known on a date is then the facts whose evidence was issued by that date, the latest issued winning: a filter on `history`, joined through `core/evidence`. A placeholder date, such as an unsent draft's, is left out (v0.7). |
| Acting for someone | `core/on_behalf_of` (ref) on the transaction. |
| Extraction confidence | `core/confidence` (decimal) on the transaction. Fields with different confidence go in different transactions (§1). Use 1 for a value the document prints plainly. A value that had to be interpreted, such as a date written without its year, goes in its own transaction at lower confidence (v0.7). |
| Location on inventory | Where a package stores stock counts, `inventory/location` (ref) on every one — first-class from day one or it breaks on day two. factstore-ecom-ops stores none: its stock is derived (§14). |

---

# Part III — Skills (procedures, no kernel code)

**What writing them taught** (v0.7, from M6's rounds, §19):
- **State the principle, and give cases only as examples.** A rule that listed the defects it covered left out a dropped zero, and the fixture's slice then kept one (round 1).
- **A fix can overreach, so the next run tests it.** The rule that an identifier holds only its own system's IDs took the shop's stock code off the product hub (round 2).
- **Rules say what stays out; a procedure says what goes in.** Under the store's rules alone, what an agent recorded from a mailbox swung from 8 of 8 questions to 2. A skill that listed what to look for made it 8 of 8 in three runs (round 5).
- **What holds at 20 documents may not at 100.** At 20 forms the agent read each one; at 100 it wrote parsers for the layouts it knew and left most forms' lines out (round 4). Told then to keep both a row's ordered and delivered dates, the next run still kept only when each spot aired. Told to list a table's columns and give each an attribute, the run after reached 99% of the lines, at twice the cost.
- **Each run is a sample.** One slice compared duplicates on first addresses only, under a rule unchanged since M5 (round 2). So each round runs three times, and the fixture's slice runs again after every change.

## 6. Catalogue skill (aim 2)
An agent with read access to the company's systems follows this and writes facts through `transact`:

1. Enumerate reachable sources.
2. Sample each: entity kinds, fields, identifiers, volumes.
3. Map every field to the vocabulary before registering anything new.
4. Resolve identities across sources. Each source's own ID is an identity attribute, so re-runs update rather than duplicate. Record cross-source matches as external-ID facts with `core/confidence`, matches of different confidence in different transactions. Mark confirmed duplicates with `core/same_as`.
5. Record field authority as facts.
6. Where sources disagree on a term, record each meaning rather than choosing one.
7. Check what it wrote before reporting: bare records a join key created, the rules that marked duplicates, sources left out, and counts against the sources.

Idempotent, read-only against sources, PII-aware, reluctant to register attributes. The output is facts in the same store as everything else; the index is not a separate system.

**What it holds** (open question 2, resolved): every record that takes part in a join, under its own system's ID, with refs to the records it names. That includes lines, which name a product. A record with no ID of its own, such as a row of a warehouse's outbound file, gets a key built from the fields that make it unique. Identifiers and join keys only: names, amounts, statuses and personal data stay in the source. Personal data may be used in working files to find duplicates, and only the `core/same_as` is written.

**What it reads.**
- Systems are the catalogue's.
- Documents and messages belong to the package's ingestion skill (§8). The catalogue reads them only to complete a hub's crosswalk, such as a factory's item code and the tariff code beside it.
- The general ledger is never indexed, not even its IDs.
- A re-run keeps the scope the store shows: a new source or kind of record is a proposal for a person.

A join key's values are checked like identifiers, because a lookup creates what it names: a blank or a list such as "PO-1 / PO-2" otherwise becomes a bogus record. In the slice this is the step agents most often skip (§18), which is why step 7 looks for what it leaves behind.

**What real data added** (v0.7, §19):
- **A record's key is built from the IDs it names.** A line number the source gives is one of them. A row's position in the file, a quantity or a price never is, since a re-export in another order would give the same line another key. Rows that repeat a key are one record.
- **An identifier holds only its own system's IDs** (Part II). A source from a system no one names gets a namespace of its own, and the report says what the system was taken to be. One run had filed a shop's invoices under Shopify's attributes because they existed.
- **Every ID column is screened,** not only join keys. Charge lines, a size range and category words had become products.
- **A file whose rows can't be indexed still adds what it names,** in a scheme the store holds. An example is a sales report whose only key is a customer's name. One run had dropped 77 products only that report sells.
- **Duplicates are compared on every mailbox, name and address an account has used,** not only its first.
- **A load longer than the agent's shell limit runs in parts,** and the agent never reports while one is running.

## 7. Ontology skill (aim 3)
An agent calls `stats`, reads attribute co-occurrence and ref connectivity, and describes the shapes it sees: "entities carrying `invoice/number`, `invoice/total`, `core/currency` and a `supplier` ref — 312 of them — call this *Invoice*; 98% also carry `core/period`." A human confirms a name, which is stored as a fact on a shape entity. Shapes stay derived; names are declared.

This replaces the "derived ontology engine" of v0.2. The model reads the stats and does the derivation; the kernel only counts.

The shape vocabulary ships with `factstore-skills`:
- `shape/name`: the confirmed name, an identity;
- `shape/signature`: a ref to each attribute every member carries;
- `shape/doc`: one line on what the members are.

Members stay derived: the entities that carry the whole signature. Entities that hold only an ID nothing joins to are fragments, such as a record a join key created and nothing filled in. The skill reports fragments as gaps, not shapes. Nothing is recorded until a person confirms, and the transaction says on whose behalf.

With no package (v0.7, §19), the ontology named the kinds a person would. For Olist, a marketplace, these were order, order line, payment, review, customer, product, seller and lead. From a mailbox read with no package, it named 17 to 19 kinds over 112 to 147 attributes, depending on the run (open question 8).

## 8. Packages as vocabularies (aim 4)
A package is a namespaced attribute set plus the conventions it relies on, plus one or more skills. The CRM package is `customer/`, `deal/`, `activity/` and a follow-up skill. The e-commerce ops package is `supplier/`, `po/`, `shipment/`, `customs/` and an ingestion skill for supplier PDFs and chat exports. Installing a package registers attributes. Nothing else. A new version may evolve an attribute only as §1 allows: `one` to `many`, or adding identity. The installer applies the change as the package's actor, then registers what is new.

A package's attributes should be ones its skill or the catalogue can fill. In the slice, 18 of factstore-ecom-ops's 69 attributes held nothing (§18):
- some because a source owns the field, such as a product's title and price in Shopify;
- freight cost, because only the general ledger has it;
- stock positions, because no source counts them (§14), and dropped in v0.6;
- a few the ingestion skill missed, since fixed.

**The sales side's identifiers are a package** (v0.6): `factstore-ecom-index`, for what Shopify, Amazon, the 3PL and QuickBooks own. Order, customer and line IDs, and the refs between them, are the same for every Shopify or Amazon seller. Left to the catalogue, each run named them its own way: one slice's `amazon/fba_shipment_id` was another's `amazon/inbound_shipment_id`. Registration should measure what is new about a company, and these aren't. With the package installed, the catalogue registered nothing in three runs (§18).

**An Amazon listing is a record of its own** (v0.7: ecom-ops 0.4.0, ecom-index 0.2.0). A real seller's reports broke the rule of one ASIN per SKU:
- Amazon listed 10 ASINs under two of the seller's codes each. Most pairs were one product listed twice, but one was two styles.
- 5 seller SKUs had moved to a new ASIN.

A listing is identified by its seller SKU, and points at our SKU and at its ASIN. Several listings can then share an ASIN, and a listing's earlier ASIN stays in its history.

**Documents with no package** (v0.7): `factstore-ingest`, in factstore-skills. A package's own ingestion skill comes first. With none, the agent names the kinds of record and their attributes itself. The skill:
- lists what to look for: identifiers, dates, quantities and prices, statuses and decisions;
- says to register an attribute rather than leave a value out;
- records copies of a message once, and reads mail sent to many;
- keys an organisation by its name, and a person never;
- cites only a document that states the fact;
- records every document it reads, even one that states nothing, so a re-run reads only what the store lacks.

Its examples come from trades other than the one it was tested on.

A coding agent then builds the application on top — narrow MCP tools that call `query`, a plain UI, whatever the company needs. The kernel does not generate these.

---

# Part IV — Layers, later

Everything below is real and was worked out in v0.2. None of it is needed for the structure, the catalogue, or a first CRM. Each has a trigger — the moment it becomes worth building.

## 9. Management layer — build when an agent is about to move money or make commitments

**Write modes / conflicts.** Per-attribute `once` (second assertion is a recorded conflict, not an overwrite), `latest`, `many`. The kernel's `one` is already `latest`, and cardinality already covers `many`; `once` is conflict policy and lives here.

**Write tiers.** Observations (what a source said, with evidence) and interpretations (our classification) flow ungated; decisions (approval, payment, commitment) are gated. A permission model keyed on the *kind* of write, not the agent.

**Policies as facts.** Entities binding attributes, patterns and thresholds to requirements and allowed actors. Evaluated on `transact`. Written by the founder in plain language; read by agents at runtime. Bind to attributes, never to shapes, so they work before anything is named.

**Definitions as facts.** Named, namespaced, owned, versioned predicates — `marketing/active_customer`, `finance/active_customer`, `ops/landed_cost`. The semantic layer, stored where everything else is. The ontology skill flags same-name, different-expression conflicts.

**Identity and scope.** Policies evaluate on `fs/actor` and `core/on_behalf_of` together. Each agent gets a scope: which attributes and definitions it may read and write.

## 10. Tooling layer — build when there are enough agents that hand-written tools don't scale

**Compiled tools.** Narrow MCP tools generated from definitions and policies with the gate and the identity filter in the tool code, not in the prompt. `get_open_pos(supplier)`, `approve_expense(expense)`. Operating agents hold these and never see `transact`.

**Agent-scoped MCP servers.** One server per agent, composed from the tools its scope allows.

**Tool search.** Context starts with zero tools; `search_tool(query)` over the ontology returns the few that fit.

**Published shapes.** A named shape gains an owner, a contract (guaranteed attributes), and an SLA — a data product. Docs and discoverability come free from `stats`.

## 11. Platform layer — build when volume demands it

Semantic search over documents and opted-in strings (vector index). A batch tier (DuckDB over the fact log) for heavy derivation. Generic UI generated from the ontology.

---

# Context

## 12. Positioning
Infrastructure, in the category of Postgres, Stripe or Clerk: `factstore` is the facts component. Never the application. A CRM is data + logic + UI; this is the data, and later a small, deliberate slice of the logic.

The emerging "agentic data platform" is read-side: data products, `get_` tools, identity propagation, tool search. Its advice for writes is "go to the transactional system," and then there is no agentic story for writes. The write side — where agents record what happened, with provenance, for companies that may have no transactional system at all — is unclaimed. That is this.

The Semantic Web needed hand-authored ontologies because the reading agent was dumb. Now the reader is smart, so structure matters less for reading and more for writing: trust, provenance, and "why is this number this?" A fact is an RDF triple with a transaction stapled on, and the ontology is read off the data instead of written down.

## 13. Distribution
factstore is MIT-licensed and not sold. The human adopts it; the agent chooses it. A coding agent asked to "store customer contacts" should find this the obvious thing to reach for instead of `json.dump`. The competitor is not Salesforce; it is a founder with a coding agent, a Postgres and a folder of markdown. The pitch is the three invariants and the catalogue — the parts they shouldn't build and can't bolt on later.

Invariant 3 makes registration expensive on purpose; distribution needs the store to be easier than `json.dump`. `register_attribute` is where the two meet: a coding agent is never blocked waiting for a human, but it cannot register silently — every new attribute names the near matches it rejected, in the log.

## 14. Stress test — cross-border e-commerce brand
Made in China, sold in the US. Shopify + Amazon, Klaviyo, Gorgias, 3PL + FBA, QuickBooks. Supply side in Excel, email and WeChat.

| Entity | Authoritative | Store role |
|---|---|---|
| Customer (DTC), Order | Shopify / Amazon | index |
| Customer (Amazon) | opaque | order-level only |
| Product title, price | Shopify | index: the SKU's IDs only |
| Inventory at 3PL / FBA | 3PL / Amazon | index: IDs only; counts stay in the source |
| Inventory at factory, in transit | **store** | derived from PO status and shipment lines. No source counts it (v0.5). |
| Supplier, PO, production, freight, customs | **store** | primary |
| Landed cost | **store** | later: definition `ops/landed_cost` |
| General ledger | QuickBooks | never |

With only Part I–III built: the catalogue skill maps the sales side and the SKU crosswalk (Shopify variant, ASIN, FNSKU, 3PL SKU, factory code, HS code — the painful one); the ops package holds the supply side as primary; a coding agent writes a handful of tools over `query`. Landed cost is computed by a skill until definitions exist. Nothing moves money, so no management layer is needed yet.

Each per-source SKU ID is an identity attribute, on the record it identifies. Amazon's are on a listing, which points at our SKU (v0.7, §8), since one ASIN can carry two listings. HS code is not — many SKUs share one — and factory codes are unique only within a factory (open question 4).

## 15. Open questions
1. *Resolved after v0.4, below.*
2. *Resolved after v0.4, below.*
3. **Excision and backups.** Deleting from the log does not reach backups or exports. Crypto-shredding (personal values encrypted with a key per entity; excision deletes the key) does, at the cost of a key store. Nor does excision stop re-ingestion: if the person is still in Shopify, the next catalogue run brings them back. Either the excision record keeps the source identifier and the catalogue skill skips anything it lists — retaining an identifier for a deleted person — or excision is also carried out in the source system, which the kernel cannot do itself.
4. *Resolved after v0.4, below.*
5. Is the e-commerce supply-side pain sharp enough for a brand to adopt factstore before agents read WeChat reliably? Only a partner can answer the first half. On the fixture's chats, the ingestion skill put 66 of 70 ETD changes and all 15 container numbers on the right records (§18). But the fixture was written alongside the skill, and its voice notes are unreadable by construction.

   Round 5 read a real company's mail (v0.7, §19). With the ingestion skill, three runs answered every question, and the 100 facts checked by hand were all right. That is a gas trader's email, though, not a factory's WeChat. No public WeChat export exists. Round 4 read real orders and invoices, though a TV station's rather than a factory's. On 100 forms, every field the mark scores reached 92% or more in each run, and line items reached 96% in the last, which passed (§19).
6. *Resolved after v0.5, below.*
7. **Personal data where the store is the source** (v0.7). The server's rules keep people's names, addresses and phones out of every store, because they "stay in the source". That holds for an index, and for a mailbox read in. It fails where the store is the source:
   - a supplier's contact: factstore-ecom-ops has `supplier/contact_name`, which no agent has filled;
   - a CRM's contacts (§8);
   - the coding agent asked to "store customer contacts" (§13).

   Round 4 met it in the data. 139 of 635 TV ad orders name the advertiser by its candidate, such as "POL/Ben Salango/Governor/WV/Dem". One run kept them out, as the rule says; later runs kept committee names such as "Tom Steyer 2020" and asked. Whether a political-ad tracker holds candidates' names is its business's call.

   **Who decides is settled: the business that owns the store,** through its owner or a manager (Victor, 2026-10-03). Factstore, a package and an agent don't. Under GDPR, the business is the controller of its personal data, the one that decides what it processes and why. A rule built into the server took that decision away from it.

   What stays fixed is the default. Until the business decides, a store holds no personal data. Round 5 showed why: without the rules, two runs recorded people from the mail they read. It is also the reversible choice of open question 2, since personal data copied in reaches backups.

   **How the business says yes** (built in v0.7: core 0.3.0; [packages](packages/README.md#allowing-personal-data)):
   - **Per attribute.** A package may offer attributes that hold personal data, such as `supplier/contact_name`. They hold nothing until the business allows them, and the package's skill fills one only then.
   - **As a fact in the log.** The business allows an attribute with `core/personal` on it, a convention beside `core/authoritative_source`. The owner or a manager writes it with a credential of their own, so the log says who allowed what, and when. That is invariant 2's actor, not a name someone claims.
   - **What agents read.** The server's rule is now: no personal data, except in attributes the business has allowed. It gives the query that lists them. It tells an agent never to allow one itself, even when asked to store contacts (§13). Instead, the agent tells the person which attributes they would allow.
   - **Taking it back.** A business that withdraws an allowance retracts the fact and excises every value it let in, history included.
   - **No kernel code.** These are ordinary writes and excisions. Only the server's instructions name `core/personal` (§4).
   - **Enforcement.** Nothing enforces the allowance until the management layer's policies (§9), just as nothing enforces the rule. The evals list every allowance and who wrote it, so an agent that allows one shows up.
   - **Open question 3 becomes live.** Once a store holds personal data, excision has to reach its backups.
   - **Run on it** ([evals/m6](evals/m6/README.md#after-design-v07-personal-data-the-business-allows)):
     - With nothing allowed, round 5 and the fixture's slice wrote no personal data and no allowance.
     - With `supplier/contact_name` allowed, ingestion filled it for all 8 of the fixture's suppliers, each name right, and put no other person anywhere.
     - The slice answered 9 of 10 questions. The miss was a WeChat reply ingestion has skipped before, unrelated to this change. It led to ecom-ops 0.4.2 (§19).
8. **A vocabulary with no package** (v0.7). With no package, ingestion registers what the documents need: 112 to 147 attributes for one trader's 103 messages.
   - Only 18 names were common to all three runs.
   - That is what the skill asks, since leaving out a value for want of an attribute was the worse failure (§19). But invariant 3's cost then grows with the documents, and the names change from run to run, as the sales side's did before ecom-index (§8).
   - The same path would turn a first mailbox's vocabulary into a draft package for its industry.
   - Untested: whether a second mailbox from the same desk reuses the first's attributes. Round 5's plan has a larger mailbox for this.

**Resolved after v0.5**
- *Business time for backfilled history (open question 6):* a convention, not a kernel change (Part II). As-of reads when a fact was written. So a store built today from a year of documents has no transaction from before today, and "what did we expect on 1 July" has no as-of answer. Every first install meets this. A document carries its date as `document/issued_at`, and a reader takes the values whose evidence was issued by the date, the latest issued winning. The alternative, a writer-supplied time on the transaction, would weaken invariant 2 (§3). On the fixture (§18):
  - ingestion dated every document it recorded, each date right;
  - the pattern, run on each slice's store, gives the world's as-of answer;
  - question agents used the pattern once the as-of error carried it. With the pattern only in `query`'s description, one of two did.

**Resolved after v0.4**
- *What the index holds (open question 2):* identifiers and join keys only (§6). Copied fields are fast, but stale and full of personal data. In the slice on the fixture (§18):
  - the crosswalk was exact;
  - duplicate customers were found from personal data kept in working files;
  - no personal value reached the store;
  - every question the sources could answer was answered through `query`.

  A question about a field left in the source, such as stock on hand at the 3PL, goes to the source.
- *Query language (open question 1):* SQL over views of the current-state table and the log (§5). Decided by the M0 spike ([spike/oq1](spike/oq1/README.md)). Fresh agents with Haiku, Sonnet and Opus answered the ten questions from a one-page doc per language:
  - SQL and Datalog got 29 of 30 right, and JSON patterns 28.
  - Datalog's miss was a silently wrong total, from Datomic's set semantics.
  - SQL needed the fewest queries and runs on Postgres as written.
  - Datalog is the runner-up.
- *Composite identity (open question 4):* one identity attribute holding `"<supplier code>:<factory code>"`, such as `factory/item_code` = `NBBW:MT-2231`. This was the build plan's default, adopted at the start of M3 ([packages](packages/README.md)). Compound identity attributes would be a kernel change, and one namespace per factory would make the vocabulary grow with every supplier.

**Resolved in v0.4**
- *Who may register attributes:* anyone with a credential, including builders' coding agents, through `register_attribute` and `distinct_from` (§1). Humans and packages only would stall the agent-first distribution.
- *Writes to fields an external system owns:* neither routed through nor held. The application writes to the source system; the catalogue observes the change and records it. The kernel never syncs.
- *Day-one vocabulary:* the `core/` conventions plus one package chosen at install.
- *Day-one install:* a third tool, installed after Shopify and QuickBooks. Provisioning them would make `factstore` the application (§12, §16).

## 16. Non-goals
No dashboard. No workflow builder. Never the general ledger. Not an analytics platform. Not a sync engine. Not a replacement for systems that are authoritative and working — index them.

## 17. Related work
Datomic (the datom; schema as data; also the source of v0.4's retract op, identity attributes, temporary IDs and excision). XTDB (immutable, bitemporal, queried with SQL — the closest prior art). Fluree (immutable graph ledger, JSON-LD). RDF (the triple; ontologies failed on authoring). Data mesh (owner/contract/SLA, later). Semantic layers like dbt metrics (definitions, later). Palantir ontology (authored, sold as a project). Odoo (small kernel, modules on top).

XTDB and Fluree are general databases a team adopts as its primary store. `factstore` is narrower: a registered vocabulary, kernel-stamped provenance, and a catalogue of the systems a company keeps, on a Postgres it already trusts.

## 18. First vertical slice
Build Part I. Write the catalogue and ontology skills. Run them against Shopify, QuickBooks, a 3PL export, a folder of supplier PDFs, and an export of supplier conversations from WeChat and email — the pain open question 5 asks about. No UI, no tool compiler, no policies.

Measured by:
- SKU crosswalk precision and recall against a hand-built ground truth.
- Shapes the ontology skill describes, scored against the list an operator of the business would write.
- New attributes registered beyond the package. Fewer is better.
- New entities created by re-running the catalogue. Should be zero.
- Ten real questions answered through `query` — "what is in transit for SKU X", "which POs from supplier Y are late".

**Results on the fixture** (v0.5, [evals/m5](evals/m5/README.md)). No partner data has arrived, so the slice ran on the synthetic brand's exports: four times, each from an empty store, with Sonnet.
- **Crosswalk:** precision and recall 1.0 in every run.
- **Shapes:** 14 to 16 of the operator's 18 kinds.
  - The two never held are stock. The 3PL and Amazon keep their own counts, and no source counts the rest (§14).
  - Two runs missed two more, by skipping the 3PL's outbound lines, which have no ID of their own.
- **Attributes registered beyond the packages:** 12 to 16, all identifiers and join keys on the sales side, named differently in each run (§8).
- **New entities on re-run:** none in any run.
- **Questions:** 7 or 8 right of the 8 the sources can answer.
  - Every run said questions 3 and 10 have no answer, rather than guess: as-of on backfilled history (open question 6), and stock no source counts.
- **Chats** (open question 5): 66 of 70 ETD changes and all 15 container numbers landed on the right records. The four misses were durations ("about 9 days"), not dates.
- **What broke was skill text, never the kernel.** Each of the first three runs found a failure the one before hadn't:
  - a document taken as read because its hash was in the store;
  - a list in a join key;
  - mailboxes normalized as if every provider were Gmail.

  All were fixed in the skills (§6, §8), and the fourth run, with every fix, found nothing new. One run is a sample. A partner's data needs two runs, and checks for what these failures leave behind.

Recommended next step: change, then go. Add document dates, a sales-side package, ecom-ops's stock attributes and the catalogue's own checks; then run on a partner's exports.

**After the decision** (v0.6). The decision was change, then go, and the four changes are in v0.6. The slice ran three more times on the fixture:
- **Crosswalk:** 1.0 / 1.0.
- **Shapes:** all 16 of the operator's kinds (the list lost its two stock kinds).
- **Attributes registered beyond the packages:** none, in every run.
- **Re-run:** no new entities.
  - One re-run retracted true duplicates its new checks couldn't re-justify. On a re-run the checks now only report, and the next re-run wrote nothing.
- **Questions:** all ten scored, and all ten right in the last run.
  - Question 3 reads document dates.
  - Question 10 derives stock.
- **Ingestion** dated every document it recorded, each date right.

What remains is the "go": partner data. Until then, M6 runs one use case at a time on public data (§19).

## 19. One use case at a time, on public data

Build plan M6 ([evals/m6](evals/m6/README.md)). A partner may put part of its data in factstore, not all of it. Until one does, each round runs one use case on one public dataset from a real company. It runs three times: a trial on a sample, a run, and a run that confirms its fixes. After each round's fixes, the fixture's slice (§18) runs again and has to stay as it was. Each round's questions and answers are written from the raw files before it runs.

| Round | Use case | Data | Last run |
|---|---|---|---|
| 1 | One product list across a brand's marketplaces | An Indian clothing seller's Amazon, stock and sales reports; 0.5 million facts | 6 of 6 questions. All 9,817 products. Every ASIN on its own product, and both listings under each ASIN Amazon lists twice. |
| 2 | One shop's orders, customers and products, with junk in its ID columns | Online Retail II, a UK gift retailer: 1,067,371 order lines; 3.2 million facts | 6 of 6. Every customer, invoice and product. One line per invoice and product. No postage or fee code taken for a product. |
| 3 | A marketplace and its sales funnel, with duplicate customers | Olist: 99,441 orders; 1.2 million facts | 7 of 7. All 2,997 people's customer IDs joined, and no two people. No review comment in the store. |
| 4 | Supplier invoices and orders, in layouts the skill hasn't seen | VRDU: 100 TV stations' orders and invoices for political airtime, from the FCC's public files, since DocILE had nothing under its token | 6 of 6. Contract number, station, advertiser and gross at 92% or more; line items at 96%. Each form once, scans included, every fact citing it, no person's details. |
| 5 | One mailbox, in an industry with no package | Enron: one gas trader's 103 messages, as 249 files | 8 of 8. Each message once. 50 of 50 facts right by hand. No personal data. On the skill text round 4 left, 7 of 8; the eighth's answer is in the store. |

Every last run wrote nothing on its re-run. On each round's final skill text, the fixture's slice kept product matching at 1.0, all 18 kinds and 10 of 10 questions. Two slices on intermediate text fell short, and the next fix restored them.

Ten questions can pass while a status is nearly a third short. Most of the fixture's POs go into production on a supplier's reply that names nothing, such as "Received, thank you" after our deposit message. Of the 43 production starts the chats state, slices l to q recorded 30 to 43, and the questions caught the shortfall in two of them. Ingestion classified messages with a script, one at a time, and its patterns covered only the phrasings it had seen. Ecom-ops 0.4.2's skill has the agent read the replies after each of our messages itself. The three slices on it each recorded all 43, against three of the six before it ([evals/m6](evals/m6/README.md#after-design-v07-personal-data-the-business-allows)).

**What broke** (§6, §8; [packages](packages/README.md)):
- **Never the kernel's code.** The one failure below the skills was Postgres's shared memory. Docker's default of 64 MB failed a parallel query at 530,000 facts, and the compose file now gives it 1 GB.
- **The catalogue's text, on real junk.** These are the rules §6 adds in v0.7, each found by a run that broke it.
- **A package's model.** One ASIN per SKU didn't survive a real seller (§8).
- **With no package and no skill, what an agent recorded** (round 5).
  - With a one-line instruction, it recorded people (124 values naming one in one run) and copied bodies.
  - Under the store's rules, it wrote no personal data, but answered 6 of 8 questions in one run and 2 in another.
  - The server's rules (§2) and `factstore-ingest` (§8) fixed both.
- **The general skill on forms at scale** (round 4). Written from a mailbox, it said nothing of tables, garbled text layers or a folder too big to read by hand. Each run found the next gap: lines, page images, batches, withdrawing a value, a row's columns. One run read five scans right, then doubted the reads and withdrew them. Another left four scans unopened, having extracted their images instead of opening the PDFs. Told to open the file itself, the last read all five and passed.
- **Judgement calls differ between first runs, and each re-run keeps its own.** Examples are gift vouchers as products, a seller's own-channel orders, and payments as records. They are a person's to settle. Round 3's report raised payments as one.

**Cost.** A catalogue run cost $0.47 to $0.82 and took 3 to 21 minutes, a million lines included, since the agent samples a file and then writes a script. A mailbox run cost $2.14 to $4.29, and 100 forms $7 to $25, since the agent reads each document; the last forms run mapped every column. All five rounds cost about $139 in runs, and $49 in fixture slices.
