# factstore — Build Plan

**Status:** Draft v0.2 · 2026-10-01 · for [design v0.4](factstore-design.md)

## Goal

Run the first vertical slice (design §18) on a real brand's data and report its five measures. That needs Part I (the kernel), the `core/` starter vocabulary, the `factstore-ecom-ops` package, and the catalogue and ontology skills. Nothing from Part IV.

## Assumptions

- **Team:** one engineer working with coding agents. Durations below are indicative on that basis.
- **Language:** Python for the kernel, the MCP server and the SDK. The SDK is already Python (`import factstore`), and one language lets server and SDK share types. psycopg 3 for Postgres; the official MCP Python SDK for the server.
- **Database:** Postgres 16+, with `pg_trgm` for attribute search. No embeddings: the vector index is Platform layer (§11).
- **Deployment:** single-tenant, one Postgres per company. Hosted vs self-hosted is decided after the slice.
- **Repo:** one repository with `factstore/` (kernel, MCP server, SDK), `factstore-skills/`, `packages/core/` and `packages/ecom-ops/` (published as `factstore-ecom-ops`). Split when published.
- **Design partner:** a cross-border brand matching the stress test (§14) provides exports, an operator's time, and an agreement on how its personal data is handled.

## Decisions before code

OQ1–OQ5 are the open questions in design §15.

| Decision | Blocks | Decide by | If still open |
|---|---|---|---|
| Query language (OQ1) | `query` (M2) | end of M0 | Cannot stay open. The M0 spike decides it. |
| What the index holds (OQ2) | the ten questions (M0), the fixture's sales side (M1), the catalogue SKILL.md (M4) | end of M0 | Identifiers and join keys only. It is the reversible choice: fields can be copied in later, personal data cannot be un-copied. |
| Excision and backups (OQ3) | value storage and `excise` (M1), the catalogue SKILL.md (M4), partner data (M5) | end of M0 | Physical deletion, with slice backups kept short-lived so an excision reaches them by expiry. Switching to crypto-shredding later means reworking value storage — safe until partner data lands, after which old backups keep plaintext. Re-ingestion: excise only together with deletion in the source system, so the next catalogue run finds nothing to bring back. No identifier is kept and the kernel needs no change. |
| Composite identity (OQ4) | factory-code attributes (M3) | start of M3 | One identity attribute holding `"<factory id>:<code>"`. The M1 fixture uses this until then. |

## Milestones

| | Milestone | Indicative | Depends on |
|---|---|---|---|
| M0 | Spec and decisions | 1 week | — |
| M1 | Write path | 3 weeks | M0 |
| M2 | Read path, MCP server, SDK | 2 weeks | M1 |
| M3 | Vocabulary packages | 1 week, alongside M2 | M1 registration |
| M4 | Skills | 2–3 weeks | M2, M3 |
| M5 | Slice run and report | 1–2 weeks | M4, partner data |

About ten weeks end to end. The partner track runs from M0 and is the likeliest source of delay.

### M0 — Spec and decisions

- **Tool descriptions and input schemas** for all six MCP tools, before any code (`query`'s once the spike has chosen its language). They are the primary documentation (design §2), so they are the spec. Edge cases are settled in them: what `transact` returns on a uniqueness conflict, what `dry_run` reports, what `register_attribute` returns when it refuses.
- **Postgres schema draft:** facts with one value column per type, transactions, the current-state table, the four indexes.
- **The ten questions** from §18, written with the partner's operator — or from the stress test until a partner is signed. With the OQ2 default, they ask about data the store holds (the supply side), since `query` cannot reach fields left in Shopify. At least one asks as-of.
- **Query language spike.** Three candidates: a JSON pattern language (the tool's input schema), Datalog, and SQL over views of the current-state table and the log (as-of needs the log). Write a one-page doc for each; a model writes the ten questions' queries from that doc alone; score against hand-written references. The candidate that models get right most often wins.

**Exit:** OQ1 decided; OQ2 and OQ3 decided or their defaults adopted; tool descriptions reviewed; ten questions written.

### M1 — Write path

`transact`, `search_attributes`, `register_attribute`, `excise`, the `fs/` bootstrap and credentials.

- **Bootstrap.** The `fs/` attributes describe themselves as facts. `init` creates the first actor and credential.
- **Actors.** Credentials map to actor entities. The kernel stamps `fs/actor` and `fs/at`.
- **`transact`.** Type, cardinality and uniqueness checks; the retract op; temporary IDs; lookups that create if absent; `dry_run`.
- **Single writer.** An advisory lock around `transact`, with the transaction ID assigned inside it.
- **Current state.** The current-state table is updated in the same database transaction as the log.
- **Registration.** `pg_trgm` search over names and docs; refusal on near matches; `distinct_from` recorded as `fs/distinct_from` on the new attribute. Batch registration in one transaction, for package installs (M3). The evolution rules of §1 and `fs/replaced_by`.
- **`excise`.** Runs under its own Postgres role. Deletes from the log and the current-state table and writes the excision transaction, all in one database transaction.
- **Immutability enforced by Postgres, not just code.** The application role has `INSERT` and `SELECT` on the facts table, no `UPDATE` or `DELETE`. Only the excision role can delete.
- **Reference reader.** A deliberately naive fold over the log up to a given transaction. The test oracle for M1, and for `query` in M2; never shipped.
- **Synthetic fixture.** A fake cross-border brand — Shopify orders, SKUs under all six crosswalk codes of §14, suppliers, POs, shipments, inventory by location — with its crosswalk and shapes known by construction. Two outputs: a direct loader that writes facts at up to 10M, for kernel and performance tests; and source-shaped exports (Shopify, QuickBooks and 3PL files, a few supplier PDFs, a chat export) for the skills in M4. It registers a draft vocabulary, which M3 turns into packages. Every milestone tests against it, so M1–M4 never wait on partner data.

**Exit** — automated tests:
1. Updating or deleting a fact as the application role fails.
2. After a random sequence of assertions and retractions, the current-state table equals the reference reader at the latest transaction (property test).
3. With 20 concurrent writers, transaction IDs increase in commit order, and an as-of read taken during the load returns the same answer when re-run afterwards.
4. 20 concurrent `transact` calls using the lookup `["shopify/order_id", "1234"]` create exactly one entity.
5. A payload containing `fs/actor` or `fs/at` is rejected.
6. `decimal` values round-trip exactly; an `instant` without a timezone is rejected.
7. Registering `customer/e_mail` is refused while `customer/email` exists, accepted with `distinct_from`, and `fs/distinct_from` is in the log.
8. Value type changes are rejected; `one` → `many` is accepted and `many` → `one` rejected; adding uniqueness is refused when values collide.
9. After `excise`, the values are gone from the log, the current-state table and every as-of read. The excision transaction names the entity and attributes and no values.

Plus a benchmark, with no threshold yet: fixture load throughput, which feeds the single-writer risk below.

### M2 — Read path, MCP server, SDK

- **`query`** in the language chosen in M0: current state by default, as-of by transaction or time, ref traversal in both directions, and following a named ref transitively — so `core/same_as` and `core/supersedes` work without the kernel knowing their names.
- **`stats`:** usage counts, co-occurrence and ref connectivity over current state. Deprecated attributes are reported under their replacement.
- **MCP server** `factstore` exposing the tools under bare names, with the credential in the server config. `excise` is exposed only when the server is started with an excision credential.
- **SDK:** `factstore.transact`, `query`, `stats`, `search_attributes`, `register_attribute`, `excise`.

**Exit:**
- `query` agrees with the reference reader on current state and as-of, over random histories.
- The ten questions answered correctly against the fixture, each under 1 s at 10M facts (proposed budget).
- A fresh agent given only the MCP server, with no extra prompt, answers the ten questions and ingests a further fixture sample using the attributes already registered, without forcing a near-duplicate through `distinct_from`. Each failure is fixed in the tool descriptions, not with hints in the prompt.

### M3 — Vocabulary packages

Runs alongside M2 once M1's registration works.

- **Package format.** A manifest of attribute definitions (name, type, cardinality, doc, uniqueness), the packages it depends on, and its skills. Installing registers its attributes in one transaction under a package-installer actor, so `register_attribute` takes a batch. Packages obey the same rule as agents: where an attribute is a near match for another — in the package or already in the store — the manifest lists it in `distinct_from` (`core/valid_from` and `core/valid_to` will need this). The kernel learns no names.
- **From the fixture.** The fixture's draft vocabulary becomes the two packages below; the fixture then installs them instead of registering its own.
- **`packages/core/`.** The Part II conventions: `core/part_of`, `core/supersedes`, `core/same_as`, `core/authoritative_source`, `core/currency`, `core/evidence`, `core/period`, `core/valid_from`, `core/valid_to`, `core/on_behalf_of`, `core/confidence`, plus `document/hash` and `document/url`. Installed by `init`.
- **`packages/ecom-ops/`.** `supplier/`, `po/`, `shipment/`, `inventory/` (with `inventory/location`). An identity attribute for each per-source SKU ID (Shopify variant, ASIN, FNSKU, 3PL SKU); factory codes per OQ4; HS code as a plain attribute, since many SKUs share one.

**Exit:** both packages install on an empty store; installing twice changes nothing; registering a near-duplicate of a package attribute is refused.

### M4 — Skills

- **Catalogue SKILL.md** (`factstore-skills`): the six steps of §6, for the index contents chosen in OQ2. The first run reads exports, not live APIs: reproducible, and no live credentials in the loop. Live connectors come after the slice.
- **Ingestion skill** for supplier PDFs and chat exports (`factstore-ecom-ops`, §8). Fields of different confidence go in different transactions, each with `core/evidence` pointing at the document entity.
- **Ontology SKILL.md:** reads `stats`, proposes shapes, records a confirmed name on a shape entity. Its vocabulary (`shape/name`, and `shape/signature` referencing each defining attribute) ships with `factstore-skills`, installed like a package.
- **Stretch:** the landed-cost skill (§14).

**Exit**, on the fixture's exports: crosswalk precision and recall measured against the fixture's known crosswalk; a second catalogue run creates no new entities; the ontology skill recovers the fixture's known shapes; the ingestion skill extracts the fixture's PDFs with evidence on every transaction.

### M5 — Slice run and report

- Ingest the partner's Shopify, QuickBooks and 3PL exports, the supplier PDFs, and the WeChat and email export.
- Report the five measures of §18: crosswalk precision and recall; shapes against the operator's list; attributes registered beyond the package; new entities on re-run; the ten questions.
- Answer OQ5 from what the WeChat export yielded.
- Write design v0.5 from what broke.

**Exit:** report written; a go / change / stop decision on what comes next.

## Partner track

Runs from M0, alongside everything else.

- Sign a design partner matching §14. Agree how their personal data is handled: excision, backup retention, and deleting a person in the source system whenever they are excised from the store.
- Get exports: Shopify, QuickBooks, 3PL, a folder of supplier PDFs, a WeChat and email export.
- Get the operator's time for the ten questions (M0), a SKU crosswalk ground truth for a sample of SKUs, and their list of the kinds of thing the business tracks — supplier, PO, shipment and so on (both before M5).

## Critical path

M0 → M1 → M2 → M4 → M5, with M3 alongside M2. The partner track gates only M5; the synthetic fixture keeps M1–M4 independent of it.

## Risks

| Risk | Signal | Response |
|---|---|---|
| Key-value queries slow in Postgres | M2 budget missed at 10M facts | Partial indexes on the current-state table for hot attributes. The DuckDB batch tier (§11) is the later escape. |
| Single writer too slow for bulk ingestion | M1 throughput test | Larger transactions per call where provenance allows. The lock never limits reads. |
| Trigram search misses synonyms (`customer/email` vs `contact/mail`) | Attributes registered beyond the package (M5) | Tighten the catalogue skill's mapping step first. Embeddings are Platform layer and wait. |
| Models misuse the query language | M2 fresh-agent test | Fix the tool descriptions; if it persists, revisit OQ1 with the spike's runner-up. |
| WeChat exports unreadable | M4 / M5 ingestion yield | That is OQ5's answer, not a bug. Report it. |
| Partner data late | Partner track | Run M5 on the fixture plus whatever exports exist. Don't hold M1–M4. The fixture cannot answer OQ5. |

## Not in this plan

All of Part IV: the `once` write mode, write tiers, policies, definitions, scopes, compiled tools, agent-scoped servers, tool search, published shapes, vector search, the DuckDB batch tier, generated UI. Also: the CRM package, live connectors, sync, multi-tenant hosting, publishing to PyPI or an MCP registry.

## After the slice

Depending on the M5 report: either kernel changes first, if the slice broke something, or a second design partner in a different vertical with the CRM package, to test that the kernel holds without ecom-ops vocabulary. Part IV starts only at its own triggers (design §9–11).
