# factstore — Build Plan

**Status:** Draft v0.3 · 2026-10-03 · for [design v0.7](factstore-design.md)

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
| Query language (OQ1) | `query` (M2) | end of M0 | **Decided: SQL over views** of the current-state table and the log, by the spike ([spike/oq1](spike/oq1/README.md)). Datalog is the runner-up. |
| What the index holds (OQ2) | the ten questions (M0), the fixture's sales side (M1), the catalogue SKILL.md (M4) | end of M0 | Identifiers and join keys only. It is the reversible choice: fields can be copied in later, personal data cannot be un-copied. |
| Excision and backups (OQ3) | value storage and `excise` (M1), the catalogue SKILL.md (M4), partner data (M5) | end of M0 | Physical deletion, with slice backups kept short-lived so an excision reaches them by expiry. Switching to crypto-shredding later means reworking value storage — safe until partner data lands, after which old backups keep plaintext. Re-ingestion: excise only together with deletion in the source system, so the next catalogue run finds nothing to bring back. No identifier is kept and the kernel needs no change. |
| Composite identity (OQ4) | factory-code attributes (M3) | start of M3 | **Decided: the default.** One identity attribute holding `"<supplier code>:<factory code>"`: `factory/item_code` in factstore-ecom-ops ([packages](packages/README.md)). |

## Milestones

| | Milestone | Indicative | Depends on |
|---|---|---|---|
| M0 | Spec and decisions | 1 week | — |
| M1 | Write path | 3 weeks | M0 |
| M2 | Read path, MCP server, SDK | 2 weeks | M1 |
| M3 | Vocabulary packages | 1 week, alongside M2 | M1 registration |
| M4 | Skills | 2–3 weeks | M2, M3 |
| M5 | Slice run and report | 1–2 weeks | M4, partner data |
| M6 | One use case at a time, on public data | 5–6 weeks | M5 |

About ten weeks end to end. The partner track runs from M0 and is the likeliest source of delay. M6 was added after M5, while no partner has data.

### M0 — Spec and decisions

- **Tool descriptions and input schemas** for all six MCP tools, before any code (`query`'s once the spike has chosen its language). They are the primary documentation (design §2), so they are the spec. Edge cases are settled in them: what `transact` returns on a uniqueness conflict, what `dry_run` reports, what `register_attribute` returns when it refuses.
- **Postgres schema draft:** facts with one value column per type, transactions, the current-state table, the four indexes.
- **The ten questions** from §18, written with the partner's operator — or from the stress test until a partner is signed. With the OQ2 default, they ask about data the store holds (the supply side), since `query` cannot reach fields left in Shopify. At least one asks as-of.
- **Query language spike.** Three candidates: a JSON pattern language (the tool's input schema), Datalog, and SQL over views of the current-state table and the log (as-of needs the log). Write a one-page doc for each; a model writes the ten questions' queries from that doc alone; score against hand-written references. The candidate that models get right most often wins.

**Exit:** OQ1 decided; OQ2 and OQ3 decided or their defaults adopted; tool descriptions reviewed; ten questions written.

**Status, 2026-10-02:**
- The ten questions are written from the stress test ([questions.py](fixture/src/factstore_fixture/questions.py)), pending a partner's operator.
- OQ1 is decided by the spike.
- OQ2 and OQ3 run on their defaults.

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

**Status, 2026-10-02: exit met.**
- `query` is SQL over per-attribute views, as decided in M0.
- The property test checks the views against the reference reader.
- The ten questions answer correctly in at most 315 ms each at 10.3M facts ([bench](bench/README.md)).
- A fresh Sonnet agent passes both parts of the last test ([evals/m2](evals/m2/README.md)).
- A fresh Haiku agent answers the ten questions, but its ingestion still double-books an amended shipment and registers extra attributes. That is M4's ingestion skill.

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

**Status, 2026-10-02: exit met.**
- Both packages are manifests in [packages/](packages/README.md). `factstore install` installs them, and `init` installs core.
- The [tests](packages/tests/test_packages.py) check the exit:
  - each package installs in one transaction, by an actor named after it;
  - installing twice writes nothing;
  - 15 near-duplicates of package attributes are refused.
- The fixture installs ecom-ops and registers only 11 sales-side identifiers itself.
- Two core docs were reworded so `order/part_of` and `po/currency` are refused.
- Synonyms such as `inventory/qty_on_hand` still pass registration, though search finds the package attribute for them.
- The fixture's commercial invoices carry fields the package has no attributes for. M4's ingestion skill decides what they need.

**Exit:** both packages install on an empty store; installing twice changes nothing; registering a near-duplicate of a package attribute is refused.

### M4 — Skills

- **Catalogue SKILL.md** (`factstore-skills`): the six steps of §6, for the index contents chosen in OQ2. The first run reads exports, not live APIs: reproducible, and no live credentials in the loop. Live connectors come after the slice.
- **Ingestion skill** for supplier PDFs and chat exports (`factstore-ecom-ops`, §8). Fields of different confidence go in different transactions, each with `core/evidence` pointing at the document entity.
- **Ontology SKILL.md:** reads `stats`, proposes shapes, records a confirmed name on a shape entity. Its vocabulary (`shape/name`, and `shape/signature` referencing each defining attribute) ships with `factstore-skills`, installed like a package.
- **Stretch:** the landed-cost skill (§14).

**Status, 2026-10-02: exit met on the fixture, with Sonnet** ([evals/m4](evals/m4/README.md)).
- **The skills.** [factstore-skills](factstore-skills/README.md) holds the catalogue and ontology skills, and its shape vocabulary installs like a package. The ingestion skill is in factstore-ecom-ops 0.2.0. Each skill is a `SKILL.md` an agent loads.
- **Crosswalk:** precision and recall 1.0 for every SKU's nine IDs.
- **Second catalogue run:** no new entities.
  - In one of four pairs of runs, the second run indexed sources the first had left to ingestion. The skill now keeps a re-run to the scope the store shows.
- **Ontology:** all 18 shapes, recorded only after the person confirmed.
- **Ingestion:** all 504 statements in the 135 PDFs, each in a transaction whose evidence is its PDF.
- **Beyond the exit:**
  - Chats and email put 217 of 221 statements on the right entities.
  - The six of the ten questions whose data comes from documents give the same answers on the ingested store as on the world the direct loader wrote.
- **What the runs changed:**
  - **Skills.** The catalogue's scope: lines, a join key's values, the general ledger, and the scope of re-runs. The PO lifecycle in ingestion.
  - **ecom-ops 0.2.0.** `shipment/hbl` is an identity, and shipment lines are keyed by house bill and PO line.
  - **Installer.** A new package version can make an attribute many or identity.
  - **Fixture.** It printed the final ETD on proforma invoices, and gave one email address to several shoppers. Both are fixed.
- **Still open:**
  - Attribute names vary from run to run, so M5's count of attributes registered beyond the package will too.
  - Not built: the landed-cost skill (stretch).

**Exit**, on the fixture's exports: crosswalk precision and recall measured against the fixture's known crosswalk; a second catalogue run creates no new entities; the ontology skill recovers the fixture's known shapes; the ingestion skill extracts the fixture's PDFs with evidence on every transaction.

### M5 — Slice run and report

- Ingest the partner's Shopify, QuickBooks and 3PL exports, the supplier PDFs, and the WeChat and email export.
- Report the five measures of §18: crosswalk precision and recall; shapes against the operator's list; attributes registered beyond the package; new entities on re-run; the ten questions.
- Answer OQ5 from what the WeChat export yielded.
- Write design v0.5 from what broke.

**Exit:** report written; a go / change / stop decision on what comes next.

**Status, 2026-10-02: exit met on the fixture** ([evals/m5](evals/m5/README.md)). No partner data has arrived, so the slice ran on the fixture's exports, as the risk table says. **Decision (Victor): change, then go.**
- **How it ran.** Four slices, each from an empty store, with Sonnet: catalogue, ingestion of the PDFs, chats and email, a second catalogue run, the ontology, then a fresh agent answering the ten questions through `query`.
- **The five measures.**
  - Crosswalk precision and recall: 1.0 in every slice.
  - Shapes: 14 to 16 of the operator's 18 kinds.
  - Attributes registered beyond the packages: 12 to 16, all sales-side identifiers.
  - New entities on re-run: none.
  - Questions: 7 or 8 right of the 8 the sources can answer. The other two have no answer in any source, and every agent said so.
- **OQ5.** On the fixture's chats, the skill put 66 of 70 ETD changes and all 15 container numbers on the right records. The pain question waits for a partner.
- **What broke was skill text, never the kernel.** Each of the first three slices found a failure the one before hadn't, and the fourth, with every fix, found none. The fixes are in factstore-ecom-ops 0.2.1 and factstore-skills 0.1.1. They change skill text only.
- **Design v0.5:**
  - OQ2 resolved as identifiers and join keys only;
  - a new OQ6, business time for backfilled history;
  - stock at factories and in transit is derived;
  - a proposed package for the sales side's identifiers.
- **Recommendation: change, then go.** First:
  - document dates (OQ6);
  - the sales-side package;
  - ecom-ops's stock attributes;
  - the catalogue checking its own output.

  Then run the slice on a partner's exports, at least twice. Accepted as recommended.
- **The changes** ([evals/m5](evals/m5/README.md#after-the-decision), design v0.6):
  - core 0.2.0 adds `document/issued_at`, and OQ6 is resolved as a convention;
  - factstore-ecom-index 0.1.0 holds the sales side's identifiers;
  - ecom-ops 0.3.0 drops the stock attributes, and question 10 derives stock;
  - factstore-skills 0.2.0 gives the catalogue a step that checks its own output.
- **The slice again, on the changes:** slices e, f and g.
  - Crosswalk 1.0 / 1.0.
  - All 16 of the operator's kinds.
  - Nothing registered beyond the packages, against 12 to 16 before.
  - All ten questions scored. g got all ten right on the first try.
  - Every document dated, each date right.
  - Two failures, both fixed in text:
    - question agents found the business-time pattern reliably only once the as-of error carried it;
    - one re-run retracted true duplicates, so the checks only report on a re-run.

    The last slice ran with both fixes. One gap it found is fixed but not yet run: suppliers name orders by their PI number.
- **Next: go.** Run the slice on a partner's exports, at least twice, with the partner's operator writing the ten questions and the list of kinds. Partner data is the only thing blocking.
- **Parked until a pilot (Victor, 2026-10-02).** No company's data is available yet. Meanwhile M6 tests one use case at a time on public data.
- **Against the risk table.**
  - Trigram search never let a synonym of a package attribute through: everything registered was outside the packages.
  - The chats were readable, apart from voice notes.
  - Partner data was late, and M5 ran on the fixture.

### M6 — One use case at a time, on public data

A partner may use factstore for part of their data, not all of it: one channel's product list, or one inbox. So, until a pilot brings real data, each round tests one use case on one public dataset from a real company ([evals/m6](evals/m6/README.md)).

| Round | Use case | Dataset |
|---|---|---|
| 0 | The harness for public data | — |
| 1 | One product list across the marketplaces a brand sells on | An Indian clothing seller's reports (Kaggle) |
| 2 | One shop's orders, customers and products, with real junk in its ID columns | Online Retail II, a UK gift retailer |
| 3 | A marketplace at scale, with a second dataset joined in and duplicate customers | Olist and its sales funnel |
| 4 | Read a supplier's orders and invoices, in layouts the skill hasn't seen | VRDU's ad-buy forms: TV stations' orders and invoices for airtime (DocILE had nothing under its token) |
| 5 | One mailbox in another industry, with no vocabulary package | Enron, one person's mailbox |

- **One round at a time, in order.** A round's fixes change the shared skills, so the next round tests them.
- **Each round's pieces are written before it runs:** questions about what the store holds, their answers computed from the raw files, and a pass mark.
- **Each round runs three times:** a trial on a sample, a run, and a run that confirms the fixes.
- **After each round's fixes, the fixture's slice runs again**, and has to stay as it was.
- **Exports run in full.** Documents and emails grow in samples, since the agent reads each one.
- **The data and the transcripts stay out of git.** Results hold counts, scores and costs.
- **Licences:**
  - Round 1's terms are unstated, so it is used for internal testing only.
  - Olist's licence is non-commercial, which fits: factstore is MIT-licensed and not sold (Victor, 2026-10-02).

**Exit:** each round's use case passes its own mark, the fixture's slice is unchanged, and design v0.7 is written from what broke.

**Status, 2026-10-03:** rounds 0 to 3 and 5 are done ([evals/m6](evals/m6/README.md)).
- **Round 1:** one product list across a real seller's Amazon, international-sales and stock reports. Run d passed every part of the mark:
  - all six questions;
  - every ASIN on its own product, and both listings under each ASIN Amazon lists twice;
  - no junk code, charge or price-list code taken for a product;
  - no customer name in the store, and a re-run that writes nothing.
- **Its changes:**
  - Amazon listings became records of their own (ecom-ops 0.4.0, ecom-index 0.2.0; Victor's choice).
  - Three catalogue fixes (factstore-skills 0.2.1).
  - compose.yaml gives Postgres 1 GB of shared memory.
- **The fixture's slice stayed as it was, at slice k:** product matching 1.0, all 18 kinds, 10 of 10 questions, and a re-run that writes nothing.
- **Round 2:** a million order lines from a real shop, with no package for its system. Run d passed every part of the mark:
  - all six questions;
  - every customer, invoice and product, none split by its spelling;
  - one line per invoice and product;
  - no postage, fee or test code taken for a product;
  - no ID on another system's attributes, and a re-run that writes nothing.
- **Its changes:** four catalogue fixes (factstore-skills 0.2.2). They cover:
  - lines keyed by the IDs they name, not their row's position;
  - an identifier holding only its own system's IDs;
  - long loads run in parts;
  - duplicates compared on every address an account has used.
- **The fixture's slice stayed as it was, at slice n.** Slice l, on the first fix alone, missed two questions: one on duplicates, fixed by the fourth change, and one from WeChat ingestion's known variance.
- **Round 3:** a marketplace and its sales funnel, at 100,000 orders, with no package. The trial and both runs passed every part of the mark with no change to the skills:
  - all seven questions;
  - each person's customer IDs joined, and no two people joined;
  - every item the source numbers kept;
  - every review on each of its orders;
  - every closed seller linked to its lead;
  - no review comment in the store.

  The ontology named the kinds a person would.
- **Round 5** (run before round 4; Victor, 2026-10-03): an Enron gas trader's mailbox, ingested with no package for the industry. Run f passed every part of the mark:
  - all eight questions;
  - each of 103 messages recorded once, though the mail client kept them as 249 files;
  - every fact citing its message, and all 50 checked by hand right;
  - no personal data, and a re-run that writes nothing.
- **Its changes:**
  - The store's MCP instructions state its rules: values, not copies of text; no personal data; each document once; every fact cites its document. With one line of instructions, agents had put people in the store.
  - A general ingestion skill, `factstore-ingest` (factstore-skills 0.3.0). Under the rules alone, what an agent recorded swung from 8 of 8 questions to 2.
  - The fixture's slice stayed as it was under the new instructions (slice o).
- **Round 4 ran on VRDU's ad-buy forms** (Victor, 2026-10-03). DocILE's download had nothing under its token, so TV stations' orders, contracts and invoices for political airtime, from the FCC's public files, stood in. It stopped short of its mark:
  - In three runs on 100 forms, contract number, station, advertiser and gross were at 92% or more. Each form was recorded once, with no person's email, phone or role, and each re-run wrote nothing.
  - Line items reached 36%, 86% and 78%. Most misses in the last two are an invoice line's ordered dates, kept beside when the spot aired in neither.
  - Its fixes to `factstore-ingest` (0.3.2 to 0.3.5) cover tables' rows, page images, batches, withdrawing a value and variant spellings.
  - The evals stopped at the $35 Victor set (2026-10-04), at $33.10. Round 5 hasn't passed again on the final skill text: its last run, held to $2, answered 6 of 8.
- **Design v0.7 is drafted** from rounds 1, 2, 3 and 5. It adds two open questions. One is personal data where the store is the source, which the business that owns the store decides; the default is none. The other is a vocabulary with no package. Round 4's findings are in it too.
- **Question 7 is built** (core 0.3.0, ecom-ops 0.4.1, factstore-skills 0.3.1). The business's owner or a manager allows an attribute with `core/personal`, using their own credential, and the server's rule names the exception. It needed no kernel code.
  - With nothing allowed, round 5 (run g) passed every part of its mark, and the fixture's slice (p) wrote no personal data.
  - With the contact's name allowed (slice q), ingestion filled it for all 8 suppliers, each right, and put no other person in the store.
  - Slice p answered 9 of 10 questions. It skipped a WeChat reply ingestion has skipped before (slice l), and the change didn't touch that.
- **Chat replies are read with the message they answer** (ecom-ops 0.4.2). A new measure found p's miss was wider: slices l to q recorded 30 to 43 of the 43 production starts the chats state, and the questions caught it in two. Slices r, s and t, on the new skill text, each recorded 43 and answered 10 of 10, against 3 of the 6 before it.

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
