# M5: the slice, on the fixture

The build plan's M5 runs the first vertical slice (design §18) on a design partner's exports and reports five measures:
- crosswalk precision and recall;
- shapes against the operator's list;
- attributes registered beyond the package;
- new entities on re-run;
- the ten questions.

It also answers open question 5 from what the WeChat export yielded, and ends in a go / change / stop decision.

No partner data has arrived. The build plan's risk table covers this case: "Run M5 on the fixture plus whatever exports exist." So this run uses the fixture's exports, and two things it cannot do are left for partner data (see [What the fixture can't tell](#what-the-fixture-cant-tell)).

## How it runs

[run.py](run.py) builds one store per slice, from empty, the way a company would:

| Stage | Agent | Reads | Skill |
|---|---|---|---|
| 1. catalogue | catalogue agent | every export | [`factstore-catalogue`](../../factstore-skills/catalogue/SKILL.md) |
| 2. ingest | ingestion agent | `supplier_docs/`, `wechat/`, `email/` | [`ecom-ops-ingest-documents`](../../packages/ecom-ops/ingest-documents/SKILL.md) |
| 3. re-run | catalogue agent, fresh session | every export | `factstore-catalogue` |
| 4. ontology | ontology agent | only the store | [`factstore-ontology`](../../factstore-skills/ontology/SKILL.md) |
| 5. questions | question agent | only the store | none: the MCP server alone, as in [M2](../m2/README.md) |

- **Store.** It starts with core, factstore-ecom-ops and factstore-skills installed, and nothing else. Their attributes are the same in every slice; only the skill text changed ([Results](#results)).
- **Agents.** Each stage is `claude -p` with Sonnet, set up as in [M4](../m4/README.md):
  - its one skill in `.claude/skills`;
  - the factstore MCP server and no other, with no user settings;
  - for the catalogue and ingestion, a sandboxed shell and a read-only copy of the exports it reads, never `truth/`.
- **Prompts.**
  - The catalogue's prompt is M4's.
  - Ingestion is told that the systems are already catalogued, and that chat timestamps are New York time.
  - The ontology agent proposes names, and the person confirms them all in a second turn.
  - The question agent gets the ten questions and the answer format, as in M2. It may answer a question with no rows if the store can't answer it.
- **What differs from M4.**
  - Ingestion works on what the catalogue built, not on reference data the fixture wrote.
  - The catalogue's second run comes after ingestion, so the store it re-reads holds documents, POs and shipments too.
  - The ontology reads a store that agents built, not the direct loader's world.

[measure.py](measure.py) scores each stage, using M4's [scorers](../m4/score.py) where they already exist:

| Measure | Scored against |
|---|---|
| Crosswalk | `truth/crosswalk.csv`: each SKU's IDs in nine systems, as links to our SKU code, after the re-run. |
| Shapes | `truth/shapes.json`, the operator's list of 18 kinds of thing. Each kind is found in the store by its IDs, since the catalogue names the sales side itself. Its signature is what every entity of it carries in this store. It must match a recorded shape exactly. |
| Attributes registered | Everything the four agents registered. The fixture's direct loader registers 11. |
| New entities on re-run | Entities the re-run created, leaving out transactions, attributes and actors. |
| The ten questions | The question agent's answers, against the direct loader's world ([results/world.json](results/world.json)). Two exceptions: question 8 is checked against what the exports show, and question 9 against this store's own log, since it asks who wrote a value here. |

## Results

Four slices, `a` to `d`, each from an empty store. Each of the first three found a failure the one before it hadn't, and I fixed the skill text before the next, so they ran different versions. d, with every fix, found nothing new.

| Slice | Skills |
|---|---|
| a, b | As M4 left them: factstore-ecom-ops 0.2.0, factstore-skills 0.1.0. |
| c | Ingestion's read rule and its PO and supplier fields; the catalogue's check of join-key values. |
| d | And the catalogue's mailbox rule. |

The five measures:

| Measure | a | b | c | d |
|---|---|---|---|---|
| Crosswalk precision / recall | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |
| The operator's 18 kinds: held in the store, and matching a recorded shape | 15, 14 | 15, 14 | 16, 16 | 16, 16 |
| Attributes registered beyond the packages | 12 | 13 | 16 | 14 |
| New entities on re-run | 0 | 0 | 0 | 0 |
| Questions right, of the 8 the sources can answer | 8 | 8 | 7 | 8 |

And beside them:

| | a | b | c | d |
|---|---|---|---|---|
| Duplicate customers marked: precision / recall | 1.0 / 0.92 | 1.0 / 0.92 | 0.15 / 0.50 | 1.0 / 0.92 |
| Bogus records a join key created | 0 | 5 POs | 0 | 0 |
| PDF statements whose own PDF is the evidence, of 504 | 338 | 338 | 504 | 504 |
| Package attributes left empty, of 69 | 18 | 17 | 14 | 14 |
| Personal values in the store | 0 | 0 | 0 | 0 |
| Cost and wall time | $3.60, 14 min | $3.10, 16 min | $4.12, 17 min | $3.51, 15 min |

### Each measure

- **Crosswalk: exact in every slice.** Each of the 49 SKUs has its nine IDs on one hub: UPC, Shopify variant, 3PL item code, factory item code, HS code and supplier, plus the three Amazon IDs for the 25 SKUs listed there.
- **Shapes.** Two of the operator's 18 kinds are stock: locations and stock positions. No slice holds them, and by design none should:
  - Stock at the 3PL and at Amazon stays in those systems, which own the counts (open question 2).
  - No source counts stock at a factory or on the water ([Questions](#questions)).

  Of the other 16:
  - **a and b hold 15 and match 14.** Both skipped the 3PL's outbound file because its rows have no ID of their own. Yet it is the only source of FBA inbound lines: an outbound line names either a Shopify order or an FBA shipment. Without the lines, the FBA shipments were bare IDs, and the ontology agent rightly reported them as fragments, not a shape.
  - **c and d hold and match all 16.** They indexed the outbound lines, and the person confirmed one shape for them ("Warehouse outbound line", "Outbound line") covering both kinds of line.
  - Every slice also recorded two shapes the operator didn't list: documents and the 3PL's receipt lines.
- **Attributes registered: 12 to 16, all by the catalogue.** All are sales-side identifiers and join keys. Ingestion, the ontology and the questions registered nothing, so the packages covered the supply side.
  - The count measures each run's choices more than any gap in the vocabulary. The same thing gets a different name from run to run: `amazon/fba_shipment_id` (a, d) and `amazon/inbound_shipment_id` (b, c); `quickbooks/vendor_name` and `quickbooks/vendor` (d).
  - c and d registered a key for the 3PL's outbound lines, which a and b skipped. b, c and d registered Shopify's order name. c also registered Shopify's SKU field and the 3PL's client SKU.
- **Re-run: nothing new, and nothing written, in every slice.** The re-run came after ingestion. So the store it read held documents, POs and shipments it hadn't written, and it left them to ingestion.
- **Questions.** See [Questions](#questions).

### Questions

| | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| a | ✓ | ✓ | none | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | none |
| b | ✓ | ✓ | none | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | none |
| c | ✓ | ✓ | none | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | none |
| d | ✓ | ✓ | none | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | none |

- **Eight of the ten are answerable from the sources.** a, b and d answered all eight. c got question 8 wrong, from its bad duplicate merges: it found 2 accounts and 3 orders for the person, where the exports show 3 and 6.
- **Question 9 asks who wrote PO-2026-0023's current ETD, and from what.** It is checked against the slice's own log. Every slice answered: the ingestion agent, from a WeChat message.
- **Questions 3 and 10 have no answer in any source.** Every question agent said so with a reason, and none guessed.
  - **Question 3 asks what the store held on 1 July.** Store time is when a fact was written. The slice wrote a year of documents in October, so nothing in the store is from before October. Every first install backfills like this. [Design v0.5](../../factstore-design.md) proposes that documents carry their own date (open question 6).
  - **Question 10 asks for stock at each factory and on the water.** The direct loader writes these counts from the simulation, but no export counts them. They follow from POs and shipment lines: a PO's quantity sits at the factory until it ships, then on the water until it is received. The design now calls this stock derived (§14).

### What the runs found, and the fixes

Each failure was fixed in skill text. None needed a change to the kernel or to a package's attributes.

| Found in | Failure | Fix | Since |
|---|---|---|---|
| a, b | **Ingestion skipped all 41 commercial invoices and packing lists.** The catalogue had read them for item and HS codes and recorded their hashes, and the ingestion skill took a recorded hash to mean "already read". The shipped quantities came from the forwarder's emails instead, so they were right but cited the wrong evidence. | A document is read when the store holds the facts it gives, with it as their evidence. The skill gives the query that checks this. | c |
| a, b | **A PO's placed date, and a supplier's legal name, currency and port, were never written.** The skill didn't say where they come from. | The PO is placed on the date of our "new PO" chat message. The rest comes from the proforma invoice. | c |
| b | **A receipt's "PO-1 / PO-2" was written as one PO number,** making 5 bogus POs. M4's skill already said to split lists; the agent didn't check. | Before a script writes a join key, it prints the values that don't look like IDs: blanks, lists and odd spellings. | c |
| c | **Dots were dropped from every mailbox, not only at Gmail.** That merged `ann.lee@` with `annlee@`, often two people with the same name. 568 accounts were marked duplicates, and 482 were wrong. | Drop dots only at providers that ignore them. | d |
| a, b | **The 3PL's outbound lines were skipped,** and with them the FBA inbound lines, because the rows have no ID of their own. c and d indexed them unprompted, keyed by order and item, and by tracking number and item. | A record with no ID of its own is still indexed when it names other records, under a key built from the fields that make it unique. | not yet run on an empty store |

**What varies.** The slices agree on what held: the crosswalk, the re-run, the questions the sources answer, and personal data. The first three each found a different failure, though. One run is a sample, not a verdict. On a partner's data, run the slice at least twice, and check the store for what these failures leave behind:
- bare records that a join key created;
- `core/same_as` chains that are long or tie many accounts to one;
- documents recorded but cited by nothing.

### Open question 5: what the chats yielded

The fixture's WeChat export is 8 chats and 811 messages. The truth lists 120 statements in them:

| Statement | Count | Package attribute | Landed on the right record |
|---|---|---|---|
| A PO's new ETD | 70 | `po/etd` | 66 in every slice |
| A shipment's container number | 15 | `shipment/container_no` | 15 in every slice |
| A sample's air waybill | 15 | none | not recorded |
| A PO closed | 16 | none | not recorded |
| A price change | 4 | none | not recorded |

- **The four ETDs missed are durations,** such as "ok we rework, about 9 days". The truth derives a date that the chat never states. The skill doesn't invent dates, and shouldn't.
- **The chat is often not the evidence.** It often repeats a value an earlier document had already put in the store. The kernel writes nothing for an unchanged value, so the first document stays the evidence: 18 of the 66 ETDs cite their chat message. In c and d, the containers cite the packing lists, which ingestion now reads first.
- **The 21 voice notes are unreadable,** by construction. They carry no statements in the fixture.
- **35 statements have no attribute in the package:** sample air waybills, closures and price changes. Nothing in the ten questions needs them. A partner's operator would say whether they matter.

So, on the fixture, the skill reads the chats. Whether the pain is sharp enough to pay for is the part only a partner can answer.

## Decision: go, change or stop

**Recommendation: change, then go.**

- **No reason to stop.**
  - The kernel took the whole slice without a change.
  - The crosswalk was exact four times.
  - Re-runs created nothing.
  - No personal data reached the store.
  - Every question the sources can answer was answered through `query`.
- **Change these before partner data:**
  1. **Business time for backfilled history** (open question 6). Add `document/issued_at` to core and have the ingestion skill write it, so "as of 1 July" has an answer on a first install. This is a convention, not a kernel change.
  2. **A package for the sales side's identifiers.** These are Shopify's and Amazon's order, customer and line IDs, and the 3PL's receipts and outbound lines. Their names would stop varying, and "registered beyond the package" would measure what is new about the company.
  3. **Ecom-ops: stock.** Drop the stock-position and location attributes, or keep them for a skill that derives stock from POs and shipment lines (§14). No source fills them as they are.
  4. **The catalogue checks its own output** for the leftovers listed under "What varies" before it reports.
- **Then go:** run the slice on a partner's exports, at least twice. Have the partner's operator write the ten questions and the list of kinds.

The decision is Victor's.

## Reproduce

```bash
cd evals/m5
../../factstore/.venv/bin/python run.py --reference          # fs_m5_reference and results/world.json
../../factstore/.venv/bin/python run.py --tag a              # one slice, into store fs_m5_a
../../factstore/.venv/bin/python run.py --tag a --rescore    # score fs_m5_a again, running no agent
```

- `--stages ingest,rerun` continues on the store the earlier stages left.
- `--budget` caps each agent session's spend, at $15 by default.
- Each slice writes `results/<model>-<tag>.json`, with every transcript (`*.stream.jsonl`) and the agents' own scripts (`*-files/`), and leaves its store for inspection.
- A slice costs about $3–4 and 15 minutes. M5's runs, including a smoke test, cost about $14.50.

## What the fixture can't tell

- **Open question 5** asks whether the supply-side pain is sharp enough to pay for. That is a question for a partner. The fixture can show only whether the skill reads the chats.
- **Realism.** The skills were written against this fixture, and every fix in M4 came from a run on it. A partner's exports will have problems the fixture doesn't have.
