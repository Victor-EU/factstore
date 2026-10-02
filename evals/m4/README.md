# M4 exit: the skills on the fixture's exports

The build plan's M4 exit reads: "on the fixture's exports: crosswalk precision and recall measured against the fixture's known crosswalk; a second catalogue run creates no new entities; the ontology skill recovers the fixture's known shapes; the ingestion skill extracts the fixture's PDFs with evidence on every transaction."

## How it runs

[run.py](run.py) runs each skill in `claude -p` with Sonnet, in a fresh directory.
- **The skill.** Its one skill sits in `.claude/skills/`, and Claude Code loads it. The prompt names the skill and the task, nothing more.
- **Tools.**
  - The factstore MCP server is the only MCP server, and no user settings load (`--strict-mcp-config`, `--setting-sources project`).
  - The catalogue and ingestion parts also get Bash, Read, Write, Edit, Glob and Grep.
  - Bash runs in Claude Code's sandbox, so it can write only in its directory and its scratchpad, and can reach the local Postgres.
  - The agent's credential is in `FACTSTORE_DSN`, for the SDK.
- **Sources.** The agent gets a read-only copy of the exports it reads, never `truth/`.

[score.py](score.py) then scores the store against the export's `truth/`. The end-to-end check also compares it with the same world written by the direct loader.

| Part | Store before | The agent reads | Scored on |
|---|---|---|---|
| catalogue | Empty, with core, ecom-ops and factstore-skills installed. | All the exports. | Crosswalk precision and recall: each of a SKU's IDs in nine systems, as a link to our SKU code. Entities created by a second run (a fresh agent, same prompt). Duplicate customers. Personal data written. |
| ingest | The same, plus the reference data a perfect catalogue leaves: suppliers, SKUs with their IDs, and locations. | `supplier_docs/`: 135 PDFs. | The 504 statements the truth says the PDFs make. Each must be on the right entity, in a transaction whose evidence is that PDF. Evidence and confidence on every transaction. |
| messages | What ingest left. | `wechat/` and `email/`. | The 221 statements the chats and emails make that the package has attributes for. The 6 of the ten questions whose data comes from the documents, against the direct loader's world. |
| ontology | The whole default world, written by the direct loader, with factstore-skills installed. | Nothing: `stats` and `query`. | The shapes recorded after the person confirms, against the 18 kinds of thing the fixture writes. |

Every transcript is in `results/*.stream.jsonl`, with the DSN's password scrubbed. The scripts the agents wrote are in `results/*-files/`.

## Results

These are for the skills as committed: catalogue v4, ingestion v2, ontology v1.

| Exit test | Result | Cost |
|---|---|---|
| **Crosswalk** | Precision 1.0 and recall 1.0 over 49 SKUs and nine IDs: UPC, Shopify variant, Amazon seller SKU, ASIN, FNSKU, 3PL item code, factory item code (with the supplier prefix), HS code and supplier. | $1.13 |
| **Second catalogue run** | 0 new entities and 0 transactions. It checked the exports' hashes and record counts against the store and stopped. | $0.16 |
| **Ontology** | All 18 shapes, with exactly the attributes every member carries. Nothing was recorded until the person confirmed. | $0.37 |
| **Ingestion of the PDFs** | All 504 statements, each in a transaction whose evidence is its PDF. All 135 transactions carry evidence and confidence. All 135 PDFs are recorded under their true hash. No attributes registered. | $0.58 |

**The exit is met.**

What else the runs measured:
- **Duplicate Shopify accounts.**
  - Precision is 1.0 and recall 0.89: 152 of the 171 duplicate pairs whose accounts both appear in the exports.
  - Another 112 duplicates point at an account that last ordered in 2025, and the year-to-date exports don't show those accounts.
  - The misses are mostly sign-ups with another email provider that share no address with the first account. They look exactly like two people with the same name.
- **Personal data.** No customer email, name, phone or address is in the store.
- **Attributes registered beyond the packages.** 15 by the catalogue: the sales-side IDs and join keys, the 3PL's line keys, and the QuickBooks vendor name. 0 by ingestion. The fixture's direct loader registers 11.
- **Chats and email,** which the exit doesn't require:
  - 217 of the 221 statements are on the right entity.
  - All 263 transactions carry evidence and confidence, and nothing was registered.
  - The four misses are new ETDs that suppliers implied ("ok we rework, about 9 days") without stating a date.
  - 123 statements are backed by their own message. The other 94 repeated a value an earlier document had already put in the store, such as the PI's ETD repeated in the chat. The kernel writes nothing for an unchanged value, so the earlier document stays the evidence.
- **End to end.** Six of the ten questions (1, 2, 4, 5, 6 and 7) get their data from these documents. On the store that ingestion built from the PDFs, chats and email, all six give the same answers as on the world the direct loader wrote.
- **Ontology against `shapes.json`.** It matches 16 of 18, because that file was written before the data. Its Purchase order and PO line list the PI number, ETD and unit price as optional, but every PO in the default world has them by 1 October.

## Every run

| Run | Crosswalk P / R | New on second run | Duplicates P / R | Registered | Cost, both runs |
|---|---|---|---|---|---|
| catalogue v1 | 1.0 / 0.73 | 0 | 0.07 / 0.55 (fixture bug, below) | 12 | $1.18 |
| catalogue v2 | 1.0 / 1.0 | 0 | 1.0 / 0.92 | 15 | $1.72 |
| catalogue v3 | 1.0 / 1.0 | **136** | 1.0 / 0.92 | 18 | $1.98 |
| **catalogue v4** | **1.0 / 1.0** | **0** | **1.0 / 0.89** | **15** | **$1.29** |

| Run | PDF statements | Chat and email statements | Questions agreeing | Evidence | Cost |
|---|---|---|---|---|---|
| ingest v1 + messages v1 | 504 / 504 | 217 / 221 | 4 of 6 | every transaction | $0.41 + $1.11 |
| **ingest v2 + messages v2** | **504 / 504** | **217 / 221** | **6 of 6** | **every transaction** | **$0.58 + $1.28** |

The ontology ran once: $0.37. All runs together cost about $10.

## What the runs found, and the fixes

Each failure was fixed in the skill, or in the fixture where the fixture was wrong, not with hints in the prompt.

**Catalogue**
1. **v1 left out order lines, HS codes and suppliers.**
   - The skill said the store holds records "that other records join to". Nothing joins to an order line, so the agent skipped all 81,000 of them, though they carry the sales side's join to products.
   - It also treated a SKU's HS code and supplier as ingestion's, but design §14 counts them in the crosswalk.
   - The skill now says every record that takes part in a join. A product's crosswalk includes its supplier and HS code.
2. **v1 marked 1,917 duplicate customers, at precision 0.07. The fixture was wrong, not the agent.**
   - The fixture gave 2,032 email addresses to more than one shopper. Shopify allows one account per address, so the agent rightly took one mailbox and one name to be one person.
   - The fixture now gives each shopper an address of their own (`brian.wright2@...`), with no other change to the world.
3. **v2 made POs out of a free-text column.** It linked 3PL receipts to POs straight from their Reference column.
   - Blank references made a PO numbered "", and lists made one numbered "PO-2025-0149 / PO-2025-0145 / PO-2025-0150".
   - The second run found the bogus POs and reported them rather than writing.
   - The skill now says to check a join key's values as you would an identifier's: skip blanks, split lists, normalize spellings.
4. **v3's second run created 136 entities.**
   - The first run had left the chats, emails and inspection reports to the ingestion skill, as the skill said. The second read "their IDs in each system" more widely and indexed bookings, customs entries and inspections from them.
   - The first run also indexed QuickBooks bills, which is the general ledger, and named join keys `record/po` and `record/shipment`.
   - The skill now draws the lines:
     - Systems are the catalogue's.
     - Documents and messages are ingestion's, except to complete a hub's crosswalk.
     - The general ledger is never indexed.
     - A re-run keeps the scope the store shows.
     - A join key is named for the record it is on.

**Ingestion**

5. **v1 never moved a PO past "confirmed",** and never set its ETD to the actual departure. So question 7 (open PO value) and question 2 (slipped ETDs) disagreed with the world. The skill now gives the PO lifecycle: confirmed, then in production, ready, shipped and received. It also covers the warehouse's receipt emails.

**Vocabulary and fixture, before the runs**
- **Shipment line keys** (ecom-ops 0.2.0, [packages](../../packages/README.md)). Shipment lines were keyed by booking number, which no document listing shipment lines carries. They are now keyed by house bill and PO line, and the house bill is an identity.
- **Proforma invoices** printed a PO's final ETD instead of the one quoted on the day. The fixture now prints the quoted one, which the truth file always had.

## What varies between runs

- **Attribute names.** The four first runs of the catalogue registered 12, 15, 18 and 15 attributes, and named the same things differently: `amazon/order_line`, `amazon/order_line_key`; `quickbooks/vendor`, `quickbooks/vendor_name`. The re-run reused whatever the first run chose, which is the point of registration. But the count M5 measures will move from run to run.
  - The sales-side identifiers are the same for every Shopify or Amazon seller. A package for them would fix the names, at the cost of the M3 decision to leave them to the catalogue.
- **Bare entities from join keys.** A ref by lookup creates the record it names. v4's catalogue left 26 POs and 29 shipments that only the 3PL's receipts mention, holding nothing but their numbers, for ingestion to fill in. The ontology skill reports such fragments as gaps rather than shapes.

## Reproduce

```bash
cd evals/m4
../../factstore/.venv/bin/pip install pypdf          # the agents extract PDF text with it
../../factstore/.venv/bin/python run.py --part catalogue --model sonnet
../../factstore/.venv/bin/python run.py --part ingest
../../factstore/.venv/bin/python run.py --part messages   # continues from ingest's store
../../factstore/.venv/bin/python run.py --part ontology
```

Each part writes `results/<model>-<part>.json` and leaves its store for inspection: `fs_m4_catalogue`, `fs_m4_ingest`, `fs_m4_ontology`, and `fs_m4_reference` (the world the questions are compared against). `--budget` caps each agent session's spend, at $15 by default.
