# factstore — Design Doc

**Status:** Draft v0.5 · 2026-10-02
**Name:** `factstore`. A technical name, not a product name. Referred to below as *the kernel* when discussing Part I and *the store* when discussing what it holds.

**Naming scheme:**
- `factstore` — the kernel (Part I)
- `factstore-skills` — the catalogue and ontology skills (Part III)
- `factstore-<package>` — a vocabulary package, e.g. `factstore-crm`, `factstore-ecom-ops`
- MCP server `factstore`, tools `transact`, `query`, `stats`, `search_attributes`, `register_attribute`, `excise`. Tool names are bare: the server name is already the namespace, and some clients reject dots in tool names.
- SDK `import factstore`, then `factstore.transact(...)`. Not `assert`, which is a Python keyword.

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

## 3. Invariants that cannot be retrofitted

Three things stay in even the smallest kernel, because adding them later is a migration nobody will do:

1. **Immutability.** No fact is ever changed in place. The only removal is excision, and excision is itself recorded.
2. **Every fact has a transaction, and the kernel says whose.** No anonymous writes, ever, and no self-declared actors. A log of claimed actors cannot be made trustworthy afterwards.
3. **Attributes are registered, namespaced and documented.** No free-form keys.

Remove any one of these and the result is a JSON file with extra steps.

Four decisions sit beside them, for the same reason — changing them later means rewriting history:

- **Exact types.** An amount stored as a float, or an ETA without a timezone, is wrong in every fact already written.
- **Unique identity.** Without it, idempotent ingestion is a race: two agents both find no entity for `shopify/order_id = 1234` and both create one. Duplicates already in the log cannot be told apart from real entities.
- **Excision.** The catalogue will copy personal data into the store — customer emails, supplier contacts — and GDPR, CCPA and PIPL require deleting it on request. `excise` takes an entity, optionally narrowed to attributes, deletes the matching facts, and records an excision transaction saying who, when, and which entity and attributes — never the values. Backups: open question 3.
- **Commit order.** Transaction IDs follow commit order, so an as-of query gives the same answer every time it runs (§5).

## 4. What the kernel does not know

The kernel has no concept of: money, documents, types, shapes, ownership, approval, conflict, policy, definition, identity propagation, or what a customer is. All of these are either conventions (Part II) or layers built on top (Part IV). The test for adding anything to Part I: *would Postgres add this?* Each kernel addition in v0.4 has a Postgres counterpart: `UNIQUE`, `DELETE`, `numeric`, `timestamptz`, `current_user`.

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
| Composition | `core/part_of` (ref, many) on the part. Line items, shipment contents. |
| Correction vs supersession | Fixing *our* recording error: a new fact on the same entity. The *world* reissuing something — a corrected invoice, a credit note: a new entity with `core/supersedes` (ref, one); the old one is untouched. |
| Entity merge | `core/same_as` (ref, one) on the duplicate, pointing at the survivor. Crosswalks will produce duplicates; nothing is rewritten, and queries follow `same_as`. |
| External identity / index | `shopify/order_id`, `stripe/customer_id` as identity attributes on the entity. **The catalogue is just facts.** |
| Field authority | `core/authoritative_source` as a fact about the attribute entity. |
| Money | Each amount is a `decimal` attribute named for what it is (`invoice/subtotal`, `invoice/tax`, `invoice/total`); the entity carries one `core/currency` covering all of them. An amount in another currency goes on a part (`core/part_of`) with its own currency. A package rule, not a type. |
| Documents | An entity with `document/hash` and `document/url`; referenced via `core/evidence` on a transaction. A chat message or an email is a document of its own, so evidence points at the message, not the whole export. |
| Domain time | `core/period`, `core/valid_from`, `core/valid_to` as ordinary `date` attributes, distinct from the transaction's `fs/at`. |
| Backfilled history (proposed, open question 6) | `document/issued_at` (instant) on a document: when it was sent or signed. As-of reads when a fact was written, which is the day of ingestion for history read from old documents. What was known on a date is then the facts whose evidence was issued by that date. |
| Acting for someone | `core/on_behalf_of` (ref) on the transaction. |
| Extraction confidence | `core/confidence` (decimal) on the transaction. Fields with different confidence go in different transactions (§1). |
| Location on inventory | `inventory/location` (ref) on every inventory fact — first-class from day one or it breaks on day two. |

---

# Part III — Skills (procedures, no kernel code)

## 6. Catalogue skill (aim 2)
An agent with read access to the company's systems follows this and writes facts through `transact`:

1. Enumerate reachable sources.
2. Sample each: entity kinds, fields, identifiers, volumes.
3. Map every field to the vocabulary before registering anything new.
4. Resolve identities across sources. Each source's own ID is an identity attribute, so re-runs update rather than duplicate. Record cross-source matches as external-ID facts with `core/confidence`, matches of different confidence in different transactions. Mark confirmed duplicates with `core/same_as`.
5. Record field authority as facts.
6. Where sources disagree on a term, record each meaning rather than choosing one.

Idempotent, read-only against sources, PII-aware, reluctant to register attributes. The output is facts in the same store as everything else; the index is not a separate system.

**What it holds** (open question 2, resolved): every record that takes part in a join, under its own system's ID, with refs to the records it names. That includes lines, which name a product. A record with no ID of its own, such as a row of a warehouse's outbound file, gets a key built from the fields that make it unique. Identifiers and join keys only: names, amounts, statuses and personal data stay in the source. Personal data may be used in working files to find duplicates, and only the `core/same_as` is written.

**What it reads.**
- Systems are the catalogue's.
- Documents and messages belong to the package's ingestion skill (§8). The catalogue reads them only to complete a hub's crosswalk, such as a factory's item code and the tariff code beside it.
- The general ledger is never indexed, not even its IDs.
- A re-run keeps the scope the store shows: a new source or kind of record is a proposal for a person.

A join key's values are checked like identifiers, because a lookup creates what it names: a blank or a list such as "PO-1 / PO-2" otherwise becomes a bogus record. In the slice this is the step agents most often skip (§18).

## 7. Ontology skill (aim 3)
An agent calls `stats`, reads attribute co-occurrence and ref connectivity, and describes the shapes it sees: "entities carrying `invoice/number`, `invoice/total`, `core/currency` and a `supplier` ref — 312 of them — call this *Invoice*; 98% also carry `core/period`." A human confirms a name, which is stored as a fact on a shape entity. Shapes stay derived; names are declared.

This replaces the "derived ontology engine" of v0.2. The model reads the stats and does the derivation; the kernel only counts.

The shape vocabulary ships with `factstore-skills`:
- `shape/name`: the confirmed name, an identity;
- `shape/signature`: a ref to each attribute every member carries;
- `shape/doc`: one line on what the members are.

Members stay derived: the entities that carry the whole signature. Entities that hold only an ID nothing joins to are fragments, such as a record a join key created and nothing filled in. The skill reports fragments as gaps, not shapes. Nothing is recorded until a person confirms, and the transaction says on whose behalf.

## 8. Packages as vocabularies (aim 4)
A package is a namespaced attribute set plus the conventions it relies on, plus one or more skills. The CRM package is `customer/`, `deal/`, `activity/` and a follow-up skill. The e-commerce ops package is `supplier/`, `po/`, `shipment/`, `inventory/` and an ingestion skill for supplier PDFs and chat exports. Installing a package registers attributes. Nothing else. A new version may evolve an attribute only as §1 allows: `one` to `many`, or adding identity. The installer applies the change as the package's actor, then registers what is new.

A package's attributes should be ones its skill or the catalogue can fill. In the slice, 18 of factstore-ecom-ops's 69 attributes held nothing (§18):
- some because a source owns the field, such as a product's title and price in Shopify;
- freight cost, because only the general ledger has it;
- stock positions, because no source counts them (§14);
- a few the ingestion skill missed, since fixed.

**Proposed: the sales side's identifiers go in a package.** Order, customer and line IDs, and the refs between them, are the same for every Shopify or Amazon seller. Left to the catalogue, each run names them its own way: one slice's `amazon/fba_shipment_id` is another's `amazon/inbound_shipment_id`. Registration should measure what is new about a company, and these aren't.

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
The human buys it; the agent chooses it. A coding agent asked to "store customer contacts" should find this the obvious thing to reach for instead of `json.dump`. The competitor is not Salesforce; it is a founder with a coding agent, a Postgres and a folder of markdown. The pitch is the three invariants and the catalogue — the parts they shouldn't build and can't bolt on later.

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

Each per-source SKU ID is an identity attribute. HS code is not — many SKUs share one — and factory codes are unique only within a factory (open question 4).

## 15. Open questions
1. *Resolved after v0.4, below.*
2. *Resolved after v0.4, below.*
3. **Excision and backups.** Deleting from the log does not reach backups or exports. Crypto-shredding (personal values encrypted with a key per entity; excision deletes the key) does, at the cost of a key store. Nor does excision stop re-ingestion: if the person is still in Shopify, the next catalogue run brings them back. Either the excision record keeps the source identifier and the catalogue skill skips anything it lists — retaining an identifier for a deleted person — or excision is also carried out in the source system, which the kernel cannot do itself.
4. *Resolved after v0.4, below.*
5. Is the e-commerce supply-side pain sharp enough to pay for before agents read WeChat reliably? Only a partner can answer the first half. On the fixture's chats, the ingestion skill put 66 of 70 ETD changes and all 15 container numbers on the right records (§18). But the fixture was written alongside the skill, and its voice notes are unreadable by construction.
6. **Business time for backfilled history.** As-of reads when a fact was written. A store built today from a year of documents has no transaction from before today, so "what did we expect on 1 July" has no as-of answer. Question 3 of the ten had no answer in the slice for this reason, and every first install will meet it. Proposed: a convention, not a kernel change. A document carries its date as `document/issued_at`, and a reader takes the facts whose evidence was issued by the date. The alternative is a second, writer-supplied time on the transaction, which would weaken invariant 2 (§3).

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
