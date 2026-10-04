# M6: one use case at a time, on public data

Build plan M6. No design partner has data for us yet, and a partner may use factstore for part of their data rather than all of it. So each round tests one use case on one public dataset, from real companies, rather than a whole company at once. The fixture stays the only whole-company test (evals/m5).

## The rounds

| Round | Use case | Dataset | What it tests | How much | Answer key |
|---|---|---|---|---|---|
| 0 | The harness for public data | — | — | — | — |
| 1 | One product list across the marketplaces a brand sells on | An Indian clothing seller's reports: 7 CSVs, 70 MB | Catalogue: matching one product's codes across channels | All of it | Codes shared across files, by script; near matches checked by hand |
| 2 | One shop's orders, customers and products, with real junk in its ID columns | Online Retail II, a UK gift retailer: 1M order lines, 95 MB | Catalogue at scale; its step 7 checks on real junk: postage and fee codes, cancellations, lines with no customer | All of it | Counted from the raw file |
| 3 | A marketplace at scale, with a second dataset joined in and duplicate customers | Olist, a Brazilian marketplace, and its sales funnel: 11 CSVs, 126 MB | Catalogue; the ontology on a business it has no package for; questions | All of it | `customer_unique_id` says which customer IDs are one person |
| 4 | Read a supplier's orders and invoices, in layouts the skill hasn't seen | VRDU's ad-buy forms: 641 TV stations' orders, contracts and invoices for political airtime, 221 MB | Ingestion on layouts it hasn't seen, with no package; line items; one campaign under several names | 20 forms, then 100, then 500 | The labels: each form's fields and line items |
| 5 | One mailbox in another industry, with no vocabulary package | Enron, one gas trader's mailbox | Ingestion and the ontology with no package; the personal-data rule on real people | One trader's 103 messages, then a larger mailbox | Questions answered by hand; 50 facts checked by hand |

[rounds.py](rounds.py) has each round's source, licence and stages.
- The rounds run in this order: product matching first, the new industry last.
- Each round's columns, questions and answers are written once its data is in place.

**Left out:**
- US import records (bills of lading). ImportYeti's terms forbid automated retrieval, and OEC's bulk download is $1,999 a month.
- The Avocado email collection, which needs a paid LDC licence.
- MIDD, the first choice for round 4. Its public files hold only the annotations, not the invoice PDFs.
- DocILE, the second. Its bucket had nothing under the download token (2026-10-03), and its maintainers had left access requests unanswered since July.
- WeChat. Nothing public exists, so the fixture stays its only test.

**Licences.**
- **Round 1:** licence "other", with no terms stated. It is a re-upload from data.world, used for internal testing only (Victor, 2026-10-02).
- **Round 3:** Olist is CC BY-NC-SA 4.0. That fits, since factstore is MIT-licensed and not sold.
- **Round 4:** VRDU states no licence: its repo has no licence file and is archived. The forms are public records from the FCC's public files. Internal testing only (Victor, 2026-10-03).
- **Round 5:** Enron is CC BY 3.0 US, credited to ZL Technologies.

## Cadence

1. **One round at a time, in order.** A round's fixes change the shared skills, and the next round tests them.
2. **Three passes per round:**
   - A trial on a sample, about $1. It debugs the harness and the round's questions.
   - Run 1, the test. Its failures are fixed in the skills.
   - Run 2, which confirms the fixes.

   A round ends when a run finds nothing new, or at its budget. A run that finds something new earns one more.
3. **What grows with the data, and what doesn't.**
   - Exports run in full from run 1. The catalogue samples a file, then writes a script, so its cost doesn't grow with rows: about $1 a run on the fixture.
   - Documents and emails grow with their count, because the agent reads each one. Their samples grow only once the smaller one passes.
   - On the fixture, 135 PDFs, 163 emails and 811 chat messages cost $1.25 to $2.00. The fixture's PDFs come from a few templates, so real ones will cost more.
4. **After each round's fixes, the fixture's slice runs again** (`evals/m5/run.py --tag <x>`, about $4). It has to stay as it was: 10 of 10 questions, nothing registered beyond the packages, and a re-run that writes nothing.
5. **Each round is written before it runs:**
   - its ID columns and personal columns;
   - 5 to 8 questions someone with that use case would ask, about what the store holds;
   - their answers, computed by script from the raw files;
   - the pass mark.
6. **The data stays out of git.**
   - Downloads go to `data/<dataset>/` at the repo root, which git ignores.
   - So does each run's full record (`data/runs/`): transcripts, the agents' files, and the answers given, all of which quote the data.
   - [results/](results) holds the measures only: counts, scores and costs.

## Measures

Public data has no answer key for most of what M4 and M5 scored. [checks.py](checks.py) measures what doesn't need one:

- **Registered beyond the packages:** each agent's registrations, by name.
- **Re-run:** new entities, transactions and facts. It should be none.
- **IDs:**
  - for each kind of record, its distinct IDs in the source;
  - the identity attribute holding most of them;
  - how many the store has and lacks, and how many it has that the source doesn't.
- **Bare records:** per identity, entities holding nothing else. This is context, not a failure. An order its lines point at holds only its ID, and so does a record a malformed join key created.
- **Personal data:**
  - values of the round's personal columns found in the store;
  - strings shaped like an email address. Message IDs, used as documents' URLs, don't count.
- **Documents:** how many were recorded, and how many carry a URL and an issue date. Also how many transactions cite one as evidence.
- **Questions:** right, out of those asked.
- **The round's own answer key,** where its dataset has one.
- **Cost and time.**

The checks reproduce slice g's counts on its store (fs_m5_g): receipts, FBA shipments, 3PL item codes and vendors all match the fixture's exports exactly.

## Running

```bash
cd evals/m6
../../factstore/.venv/bin/python run.py --round 1 --check                # data in place; IDs and answers compute
../../factstore/.venv/bin/python run.py --round 1 --tag t --sample 200   # the trial, into store fs_m6_r1_t
../../factstore/.venv/bin/python run.py --round 1 --tag a                # run 1
../../factstore/.venv/bin/python run.py --round 1 --tag a --stages questions   # one stage again, on the same store
../../factstore/.venv/bin/python run.py --round 1 --tag a --rescore      # score the store again, running no agent
```

- The agents run as in M5: `claude -p` with Sonnet, one skill, and the factstore MCP server only.
- Each gets a sandboxed shell and a read-only copy of the round's sources.

## Round 1: one product list across marketplaces

**Done, on run d.** Seven reports from one seller:
- Amazon's order report: 128,975 lines, 120,378 orders, 7,195 seller SKUs and 7,190 ASINs.
- The stock report: 9,170 codes.
- An international sales report: 37,432 lines with no ID but a customer's name.
- Two price lists: 1,330 codes in another scheme.
- A rate card and an expense sheet.

Between them, 9,817 products.

| Run | Packages, skills | Questions | ASINs on their own product, of 7,170 | Shared ASINs with both listings, of 10 | Products, of 9,817 | Junk, charges as products | Cost |
|---|---|---|---|---|---|---|---|
| t2, a sample | ecom-ops 0.3.0, skills 0.2.0 | 4 of 6 | 268 of 268 | 0 | all 321 | 0, 0 | $0.55 |
| a | the same | 5 of 6 | 7,170 | 0 | 9,745 | 0, 0 | $0.60 |
| b | + two catalogue fixes | 4 of 6 | 6,604 | 0 | 9,245 | 1, 0 | $0.82 |
| c | ecom-ops 0.4.0: listings | 6 of 6 | 7,170 | 10 | 9,817 | 12, 7 | $0.60 |
| d | + screening every ID column | 6 of 6 | 7,170 | 10 | 9,817 | 0, 0 | $0.73 |

Every run:
- put no ASIN on a wrong product, and linked no price-list code to a product;
- wrote no customer name;
- registered nothing beyond the packages;
- wrote nothing on its re-run.

A run took 3 to 7 minutes.

**What broke, and what changed:**
1. **Amazon lists 10 ASINs under two of the seller's codes each, and 5 seller SKUs moved to a new ASIN.**
   - ecom-ops put one ASIN on one product, so the agent left all 20 out, and question 6 had no answer.
   - Most of the pairs look like one product listed twice, but one is two styles (`AN208-MUSTARD-M`, `CH208-MUSTARD-M`). So "one product" isn't the answer either.
   - Victor chose to make a listing a record of its own (ecom-ops 0.4.0, ecom-index 0.2.0; [packages](../../packages/README.md)). From run c, both listings sit under the ASIN.
2. **What a seller SKU is varied between runs.** Run a made every seller SKU a product. Run b left 567 that match none of the seller's own lists as Amazon-only records, linked to nothing. With listings, the skill says a seller SKU is our code: one that matches nothing gets a product of its own, and the report names it.
3. **77 products that only the international report sells were dropped** (run a). The report's rows can't be indexed, since a customer's name is their only key, so the products they named went too. The skill now indexes what such a file names, in a scheme the store holds.
4. **That fix then let in 6 charge lines, a size range and category words as products** (run c). The skill now screens every ID column, not only join keys, for values that aren't IDs. Run d indexed none.
5. **The product's code took Amazon's doubled space** (runs t2 and a). The skill now says a product's code follows the pattern of the company's other codes.
   - Its first wording listed the defects it covered and left out a dropped zero. The fixture's regression slice h then kept one, and product matching fell to 0.98.
   - The rule now states the principle. Slice i went back to 1.0.
6. **The trial's first sample took the first 200 rows of each file, and those rows shared no codes.** The agent rightly couldn't tell the stock report held our codes. A round can now give its own sampler: round 1's keeps whole products.
7. **A parallel query on 530,000 facts failed in run b.** Docker gives Postgres 64 MB of shared memory by default. compose.yaml now sets 1 GB.
8. **The runs also found mistakes in the answer key.** Question 5 as first written couldn't be answered from any store, so it was replaced. "A shared ASIN is one product" was wrong. Five values the key counted as products are junk.

**Left open, reported only:**
- Run b and run d left out the 124 orders from the seller's own "Non-Amazon" channel; run a kept them as Amazon orders.
- A listing that moved ASIN gets only its latest one. The old ASIN stays in the history only if it was written first, and a single export carries both at once.

**The fixture's slice after each change:**

| Slice | After | Product matching | Kinds, of 18 | Questions | Re-run wrote | Cost |
|---|---|---|---|---|---|---|
| h | fixes 3 and 5, first wording | 0.984 | (16, before listings) | 10 of 10 | nothing | $4.44 |
| i | fix 5 reworded | 1.0 (catalogue stage; the run stopped after ingestion) | — | — | — | $2.66 |
| j | listings | 1.0 | 18, all exact | 10 of 10 | nothing | $3.83 |
| k | fix 4, the final text | 1.0 | 18, all exact | 10 of 10 | nothing | $3.60 |

Round 1 cost $3.71 in its runs, and $14.53 in fixture slices.

## Round 2: one shop's orders, customers and products

**Done, on run d.** One file: every line a UK gift retailer invoiced from December 2009 to December 2011.
- 1,067,371 lines on 53,628 invoices: 8,292 cancellations and 6 bad-debt adjustments among them.
- 5,942 customers, written as decimals (`13085.0`). 243,007 lines name no customer.
- 5,106 products, once case and spaces are set aside. 159 are spelled in two cases.
- 17 codes that aren't products: postage, carriage, fees, discounts, manual entries, tests. Also 9 gift vouchers.
- 45,950 lines repeat a product already on their invoice. 31,478 of those invoice-and-product pairs are identical rows.

No package covers the shop's system, so each run registers its invoice, customer and line IDs. That is reported, not failed.

| Run | Skills | Questions | The shop's IDs, on | Products, of 5,106 | Lines, of 1,021,415 pairs | Cost |
|---|---|---|---|---|---|---|
| t, a sample | 0.2.1 | 6 of 6 | its own attributes | all 3,889 | 78,242, of 76,057 | $0.62 |
| a | the same | 6 of 6 | its own | 5,106 | 1,067,365 | $0.47 |
| b | 0.2.2: lines keyed by IDs | 6 of 6 | **Shopify's** | 5,105 | 1,021,421, with the 6 adjustments | $0.47 |
| c | + no other system's IDs; every address | 4 of 6 | its own, the products' too | 5,106, with no hub | **339,982** | $0.60 |
| d | + our code on the hub; long loads in parts | 6 of 6 | its own | 5,106 | 1,021,415 | $0.62 |

Every run:
- put every customer in the store, none as a decimal;
- pointed every invoice that names a customer at it;
- split no product by its case, and took no postage, fee or test code for a product.

Every run but c wrote nothing on its re-run. A full run took 6 to 21 minutes.

**What broke, and what changed** (factstore-skills 0.2.2; [packages](../../packages/README.md)):
1. **Lines were keyed by their row's position** (the trial and run a). An invoice that lists a product twice got lines `/1` and `/2`, in the file's order. A re-export in another order would give the same line another key.
   - The skill now builds a line's key from the IDs it names, never from a position, a quantity or a price. Rows that repeat a key are one record.
   - Runs b and d wrote one line per pair.
2. **Run b filed the shop's invoices, customers and lines under Shopify's attributes,** and recorded Shopify as their authority. The prompt says only "our online shop". The skill now says an identifier holds only the IDs of the system its doc names. A source from a system no one names gets a namespace of its own, and the report says what the system was taken to be.
3. **That fix went too far** (run c). It put the shop's stock code in the shop's namespace too, so no product had a hub. The skill now says the company's own codes and the join keys belong to no system: `sku/code` holds our code whichever system it comes from.
4. **Run c's load outlasted the shell.** It ran alongside a fixture slice and took over 10 minutes. The shell moved it to the background, and the agent finished with a third of the lines written. Its re-run wrote 1,500 more.
   - The skill now estimates the full load's time from the sample and runs a long one in parts, by rows. It never finishes while a load is running.
   - Run d estimated it, and ran it whole.
5. **The fixture's slice l lost 10 of its 157 duplicate pairs.** Its script compared only the first mailbox and address each account had used. The duplicate rule hasn't changed since M5, so this was a run that read it narrowly. The skill now says to compare every one, and slice m found all 157 again.
6. **The answer key, and the harness.**
   - The trial's first key counted the 6 bad-debt adjustments as missing invoices. They are ledger entries, and are reported apart.
   - Rescoring the trial after its sampler changed scored it against files its agents never saw. run.py now records a fingerprint of the files a run was given, and refuses to rescore against others.

**Left open, reported only:**
- **Gift vouchers, and `PADS`** (pads sold with cushions), are products by judgement. The trial and run c made vouchers products; runs a, b and d didn't. Run b left out `PADS`.
- **Run b indexed the 6 adjustments as invoices;** the others left them out.

**The fixture's slice after each change:**

| Slice | After | Product matching | Duplicate pairs, of 171 visible | Kinds, of 18 | Questions | Re-run wrote | Cost |
|---|---|---|---|---|---|---|---|
| l | fix 1 | 1.0 | 147 | 18, all exact | 8 of 10 | nothing | $3.54 |
| m | fixes 2 and 5 | 1.0 | 157 | 18, all exact | 10 of 10 | nothing | $4.23 |
| n | fixes 3 and 4, the final text | 1.0 | 157 | 18, all exact | 10 of 10 | nothing | $3.88 |

Slice l missed two questions:
- Question 8 counts one person's orders across duplicate accounts (fix 5).
- Question 10 needs a PO's status from a WeChat message that ingestion didn't read. Ingestion recorded 96 chat messages in slice l, against 103 to 144 in slices e to k. It is unchanged since M5, so this is that variance, not a regression.

Round 2 cost $2.78 in its runs, and $11.65 in fixture slices.

## Round 3: a marketplace at scale, with its sales funnel

**Done, on runs a and b, with no change to the skills.** Olist, a Brazilian marketplace, 2016 to 2018, and its sales team's funnel. No package covers either.
- 99,441 orders, with 112,650 items, 103,886 payments and 99,224 reviews.
- 32,951 products and 3,095 sellers.
- 8,000 marketing leads, and 842 sellers the team closed. 462 of those sold nothing in the marketplace's export.
- A geolocation file of a million rows, with no ID.

What the round tested:
- **A customer ID per order.** The file's `customer_unique_id` says which IDs are one person: 2,997 people hold 6,342 of them, one person up to 17.
- **Items numbered by the source.** A product repeats on its order 10,225 times; an order of 21 items holds 3 products. Each item is a unit sold, so the catalogue's new rule has to keep them: the source's item number is an ID, not a row's position.
- **789 review IDs on more than one order,** so a review ID alone isn't a key.
- **Customers' review comments,** which must stay in the source.

| Run | Questions | People joined, of 2,997 | Items, of 112,650 | Review pairs, of 99,224 | Closed sellers linked to their lead, of 842 | Kinds the ontology named | Cost |
|---|---|---|---|---|---|---|---|
| t, a sample | 7 of 7 | all 109 | all 965 | all 812 | all 38 | 9 | $0.76 |
| a | 7 of 7 | 2,997, by a person record | 112,650 | 99,224 | 842 | 10 | $0.72 |
| b | 7 of 7 | 2,997, by `core/same_as` | 112,650 | 99,224 | 842 | 9 | $0.73 |

Every run:
- put every customer, order, product, seller and lead in the store, the funnel's sellers too;
- pointed every order at its customer, and every item at its product and seller;
- joined no two people;
- left the geolocation file in the source, and took no postcode or category for a record;
- wrote no review comment;
- used namespaces of its own (`olist/`, and `funnel/` or `olist/` for leads), not Shopify's;
- wrote nothing on its re-run.

A full run took 4 minutes.

**Judgements the runs made, reported only:**
- **The marketplace's products aren't our SKUs.** Every run gave them their own ID and a `line/product` ref, not `sku/code`, since the marketplace's sellers own them. Run a's report says linking them to our codes needs a source that has both.
- **Payments are indexed as records of their order.** Run a's report asks whether they belong in the ledger instead.
- **The funnel's landing pages and sales reps were left in the source,** and run a's report offers them as a proposal.
- **The ontology** named the kinds a person would: order, order line, payment, review, customer, product, seller, lead and document. Run a, which modelled people as records, added person.

Round 3 cost $2.21. Nothing changed, so the fixture's slice didn't run again.

## Round 4: a supplier's orders and invoices, in layouts the skill hasn't seen

**Passed, on run f.** Line items, short in three runs, reached 96% to 99% once the skill gave each of a table's columns an attribute. Run e's ingestion left four scans for its re-run; told to open a PDF itself rather than extract its images, run f read them all and met every part of the mark. DocILE had nothing under its download token, so VRDU's ad-buy forms stand in (Victor, 2026-10-03; [round4.py](round4.py)).
- 641 TV stations' orders, contracts and invoices for political airtime, from the FCC's public files for 2012 and 2020.
- Over 300 stations, dozens of layouts, and 12 line items to a form at the median.
- 35 scans, and some text layers so garbled that only the page image reads.

No package covers airtime, so ingestion runs on the general skill, `factstore-ingest`. The labels give each form's fields and line items. A label that doesn't read as its type, such as a date cut in two, is left out of the key and counted. The six questions' answers were read from the PDFs by hand.

| Run | Forms | Questions | Contract number | Station | Advertiser | Gross | Line items | Cost |
|---|---|---|---|---|---|---|---|---|
| t | 20 | 3 of 6 | 100% | 95% | 90% | 100% | 1% | $1.53 |
| t2 | 20 | 5 of 6 | 100% | 95% | 85% | 100% | 81% | $1.79 |
| t3 | 20 | 6 of 6 | 95% | 100% | 100% | 100% | 97% | $1.92 |
| a | 100 | 5 of 6 | 99% | 98% | 92% | 100% | 36% | $7.05 |
| b | the same | 6 of 6 | 99% | 95% | 96% | 98% | 86% | $12.20 |
| c | the same | 4 of 6 | 100% | 95% | 97% | 99% | 78% | $12.06 |
| e | the same | 6 of 6 | 99% | 97% | 97% | 100% | 99% | $25.04 |
| f | the same | 6 of 6 | 99% | 97% | 92% | 99% | 96% | $21.85 |

The pass mark asks 90% of each. Every run wrote no email address, phone number or salesperson's name, and wrote nothing on its re-run. Each recorded every form once with its issue date, scans included, except run b, which left out one scan, run c, which left five scans and two forms undated, and run e, whose ingestion left four scans to its re-run (below). Run e's measures include what its re-run wrote. t and t2 were scored before the scorer's last fixes, below.

**What broke, and the fixes** (factstore-skills 0.3.2; 0.3.3 after run b; 0.3.6 after run c; 0.3.7 after run e):
- **Line items (t).** The skill, written from a mailbox, said nothing about tables. The agent kept each order's totals and left its lines out. The skill now makes a table's rows records of their own, keyed by their record and row number, and checks that they add up to the printed total.
- **Garbled text layers (t2).** The agent read a form's garbled text layer instead of its page images, which read cleanly, and lost its schedule. The skill now reads such a PDF from its images, as it does a scan.
- **Scale (a).** At 20 forms the agent read each one. At 100 it wrote parsers for the layouts it knew and left 69 forms with their headers only, which its report said. The skill now works in batches of about 20, finishing each, lines included, before the next. A document a script can't parse, the agent reads itself.
- **Withdrawing a value (a).** Correcting its first reads of the scans, the agent retracted the earlier transactions' evidence too, so the log lost why those values were written. The skill now retracts the value alone, citing the document read again.
- **A row's dates (b).** Batches worked: every form but one has its lines. But on 24 invoices that list each spot as it aired, the agent kept when it aired and left out the dates the line was ordered for, which the row also prints. That is 168 of the 219 lines missed. The skill now keeps every value a row prints.
- **Tidying names (b).** The agent merged 13 spellings of agencies' names into one each, and retracted the variants with no document cited, which its report said. The skill now settles spellings before writing; a variant found later stays, and points at the record it duplicates with `core/same_as`, citing a document.
- **One scan (b).** Asked for one page of a PDF, the reader failed (`pdftoppm` isn't installed), so the agent took page images to be out of reach and wrote its own decoders. They read three scans; a fourth, in JBIG2, stayed unread and unrecorded, as its report said. Opening the whole PDF works. The skill now says to, when asking for pages fails.
- **Run c, on 0.3.3.** Every form was in the store, every transaction cited its form, and agencies' names stayed as printed. Three things fell short:
  - **Line dates.** The row fix didn't take. The same 24 invoices again kept when each spot aired and not the dates its line was ordered for, 168 lines as in run b; the report calls them "one per aired spot". A few garbled forms' order lines lost their dates too.
  - **It doubted its own reading.** It read the five scans whole, as 0.3.3 says, and recorded them. When one scan's lines didn't add up to its total, it concluded that all five reads "came back empty", retracted every value and left those forms with their file alone. It dropped lines from four garbled forms on the same doubt. The same reads gave right values in runs t3 and a, question 6's included. Run c lost question 6 and 52 lines this way.
  - **Question 4** asks for an order's net amount, which the form prints and run c didn't record.

**Advertisers a station labels by their candidate,** such as "POL/Ben Salango/Governor/WV/Dem", are a person's name. They are 139 of the 635 labelled forms.
- t2 kept them out, as the store's rule says. It didn't borrow the committee's name from other forms either, since no form it was citing states it.
- Question 5 had asked for that campaign, so it moved to the Congressional Leadership Fund, which three spellings name and no form names by a person.
- The mark counts these labels apart: recorded or kept out, either follows the rule.
- Whether a political-ad tracker's store holds candidates' names is the business's decision, through `core/personal` (design §15, question 7).

**The scorer's fixes:**
- **One ref.** An advertiser or station is kept once, so its name sits on a fact citing the first form that named it. A later form's facts reach it by ref.
- **Call signs.** "WSB" matches "WSB-TV".
- **Local offices** count as a candidate's label, such as a magistrate.

- **Run d, on 0.3.6.** The skill now lists a table's columns and gives each an attribute, and checks it did; a reading that disagrees with a total is read again. Run d was stopped at 30 minutes, the session's limit for a background job, with 54 forms recorded, so it has no measures of its own. On those 54 forms, line items were 94%, against 78% for run b and 77% for run c on the same forms. Invoice lines held their ordered dates beside when each spot aired. It read about half as fast as run c. Its cost wasn't recorded; at run c's rate, about $13.

- **Run e, on 0.3.6, run detached past the limit** (Victor's choice, 2026-10-04). It met every part of the mark but one: all six questions; all 100 forms once, each dated; every transaction citing its form; contract number, station, advertiser and gross at 97% or more; line items at 99%; no person's email, phone or role. Its ingestion reported four scans it "could not open": it had extracted their images to TIFF files, which the reader doesn't take, and never opened the PDFs themselves. The re-run opened each PDF whole, read all four, and wrote 1,677 facts. It took 46 minutes and cost $25.04, twice run c, since it maps every column.

- **Run f, on 0.3.7** (Victor's choice, 2026-10-04). The skill now says to open a PDF file itself with the reader, not its extracted images. Run f met every part of the mark: all six questions; all 100 forms once, each dated, all five scans read in ingestion; every transaction citing its form; contract number, station, advertiser and gross at 92% or more; line items at 96%; no person's email, phone or role; and a re-run that wrote nothing. It took 44 minutes and cost $21.85.

**Run f's misses, checked by hand.** Of its six advertiser misses, four are the scorer's or follow the rule. Two labels are cut off mid-name ("…Action P" for the stored "…Action PAC"). Two are candidates' bare names, which the agent kept out as the rule says and the scorer doesn't recognise as candidates. The other two are real: forms printing "Tom Steyer for President-D" were linked to the committee's record from other forms, "Tom Steyer 2020", without their own spelling. The scorer is unchanged, so 92% stands; by hand it is 97%.

Round 4 cost $83.44 in its runs, and about $13 more in run d, whose cost wasn't recorded. Its changes are to `factstore-ingest`, which the fixture's slice doesn't use, so round 5 ran again instead (below).

**Misses checked by hand:**
- Run t3's one contract-number miss is real. The form's flattened text puts its "External #" before "Contract #", and the agent took the wrong one.
- Its station misses were the call-sign match, fixed above.

## Round 5: one mailbox, with no package and no skill

**Done, on run f; on the skill round 4 changed, every part of the mark but one question, whose answer the store holds (run k).** Runs h to k re-ran it after round 4's changes to `factstore-ingest`; i and j at $2 a session to fit the evals' $35 (Victor, 2026-10-04), k at $5. Round 5 ran before round 4, since DocILE needs a download token (Victor, 2026-10-03). One gas trader's mailbox from Enron's West desk: custodian south-s, a 10.9 MB PST, read with libpst's `readpst`.
- 103 messages, from June 2000 to April 2001.
- The mail client kept most of them in two to four folders, so they arrive as 249 files.
- Pipeline notices, deal and invoice queries, nominations, a credit watch list, storage reports, and personal mail.

The ingesting agent first had no skill, only what the store's MCP server tells it (Victor's choice). From run d it has `factstore-ingest`, a general ingestion skill written for this round (Victor's choice). The ontology stage has its skill, as in every round. Questions 1 to 8 ask for:
- two deal numbers;
- a nomination;
- a credit listing;
- a capacity restriction;
- an open season's close;
- a bid deadline;
- a curtailment notice.

Their answers were read from the messages by hand.

| Run | What the agent had | Questions | Attributes it registered | Facts citing their message | Values naming a person, holding an address | Re-run wrote | 50 facts checked by hand | Cost |
|---|---|---|---|---|---|---|---|---|
| t, 41 messages | the store's one-line instructions | 8 of 8 | 12, `email/` only, the bodies verbatim | none | 38, 23 | nothing | — | $1.56 |
| a | the same | 8 of 8 | 41: deals, notices, restrictions, open seasons, nominations, proceedings, organisations, people | every fact it read; not the headers | 124, 65 | nothing | 43 right, 5 citing the wrong message, 2 wrong | $3.99 |
| b | + the store's four rules | 6 of 8 | 21: deals, counterparties, notices, restrictions, nominations | all | 0, 0 | nothing | 50 right | $2.14 |
| c | the same | 2 of 8 | 6: deal and notice numbers, by pattern | all | 0, 0 | nothing | — | $2.18 |
| d | + `factstore-ingest` | 8 of 8 | 134 | all, with a confidence | 0, 0 | nothing | 50 right | $2.56 |
| e | the same | 8 of 8 | 112 | all, with a confidence | 0, 0 | **21 facts** | — | $3.17 |
| f | + every document recorded | 8 of 8 | 147, the notices' attachments read too | all, with a confidence | 0, 0 | nothing | 50 right | $2.90 |
| g | + personal data only where the business allows it (none here) | 8 of 8 | 107 | all, with a confidence | 0, 0 | nothing | — | $2.27 |
| h | `factstore-ingest` 0.3.2, after round 4: tables' rows, batches | 8 of 8 | 126 | all, with a confidence | 0, 0 | **685 facts** | — | $3.27 |
| i | 0.3.4: + nothing skimmed | 8 of 8 | 148 | every value; **65 messages that state nothing, uncited** | 0, 0 | nothing | — | $2.64 |
| j | 0.3.5: + a message created alone cites itself; **$2 a session** | 6 of 8 | 171 | all, with a confidence | 0, 0 | nothing | — | $2.93 |
| k | 0.3.6, after round 4's run c; $5 a session | 7 of 8 | 177 | all, with a confidence | 0, 0 | nothing | — | $4.29 |

Every run:
- recorded each message once, whichever folders hold it;
- dated every message but the 7 drafts. The export dates those 30 November 2002, since they were never sent, and every run left them undated;
- wrote nothing on its re-run, until run h.

**What broke, and what changed:**
1. **People went into the store** (the trial and run a). Run a made records of people: names, roles, employers. Both runs copied each message's sender and recipients, and run a's notes name people too.
   - The design keeps personal data in the source. Nothing an agent without a skill reads said so, and the transact tool's example attribute was `customer/email`.
   - Victor chose to put the store's rules where every agent reads them: the MCP server's instructions. There are four:
     - record identifiers, refs and the values someone will look up, not copies of text;
     - no personal data;
     - each document once;
     - every fact cites its document.
   - The transact tool's examples now use `po/etd`.
   - Runs b and c wrote no name, address or phone number, and every fact cites its message. Run b's 50 facts are all right.
2. **Prose as facts** (the trial and run a): bodies, summaries and notes beside the values. Under the rules, runs b and c wrote none.
3. **What an agent records still depends on the run.** Under the same rules:
   - Run b recorded deals, counterparties, notices, restrictions and nominations. It left out the Wild Goose open season and Southwest Gas's bid deadline as "not clear enough to record as facts".
   - Run c recorded only deal and notice numbers, found by pattern. It said it left quantities out "because the store has no attribute for them yet", though it could have registered one.

   The rules settle what must stay out. What should go in, with no package, was the agent's choice.
4. **A general ingestion skill, `factstore-ingest`** (factstore-skills 0.3.0; Victor's choice). It is domain-free. It names nothing from this mailbox, and its examples come from other trades. It covers:
   - copies of a message are one document;
   - mail sent to many is still read;
   - list every value a document states, and register an attribute for each rather than leave it out;
   - key records by their IDs, never by a person;
   - a fact cites only a document that states it;
   - confidence on interpreted values.

   Runs d, e and f answered all eight questions, and every fact cited its message with a confidence. Run d's and run f's 50 facts are all right.
5. **Run e recorded a document only with its first fact** (the skill said so then). Its re-run found two messages no document stood for, read them, and wrote 21 facts the first run had judged not worth recording. The skill now records every document it reads, even one that states nothing. A re-run reads only the documents the store lacks. Run f's re-run wrote nothing.
6. **The answer key.** Question 8's notice is "2001042" in the email and "2001-042" in its attachment. Runs d and e gave the attachment's spelling, which is as right. The judge now accepts an identifier with or without its separators. Run h gave the notice's key, `kern-river/2001-042`, and the judge now also accepts an identifier that ends a key. No other run's score changed.
7. **A skimmed attachment (h).** Round 4 taught the skill to record a table's rows. A Northwest Pipeline notice prints 69 rows of capacity for sale, and run h's first pass "only skimmed" that attachment, as its report said. Its re-run read it and recorded the rows. The skill now counts a document it could open but only skimmed as unfinished (factstore-skills 0.3.4).
8. **A message created alone, uncited (i).** Runs f and g cited a message that states nothing in the transaction creating it. Run i didn't, for 65 of its 72, and the skill had never said to. It does now (0.3.5).
9. **Run j ran out of budget.** Its ingestion reported that it stopped before its final checks "because of the $2 budget", and left some attachments unread. It read the credit watch spreadsheet, so 101 companies are on No Trades, and the question asks which one the list's message placed there. Southwest Gas's bid solicitation wasn't recorded. Earlier ingestion sessions cost $1.06 to $1.99, so a fair run needs a higher cap.
10. **Run k missed question 4 with the answer in the store.** It recorded the credit watch spreadsheet's 101 companies on No Trades, and flagged the one entry the sheet marks as revised: NUI Utilities, the company the message says was placed there. The question agent found the flag and declined to name it, since nothing said the flag was what the question meant.
11. **The harness.**
   - A question's judge now accepts an answer in any common form: "2,220 MMcf/d", "4/26", "NUI Utilities, Inc.".
   - Rescoring judges the stored answers again.
   - A message counts as recorded when any value on its document names it, URL-encoded or not.

**The fixture's slice under the new rules (slice o)** stayed as slice n: product matching 1.0, 157 duplicate pairs, all 18 kinds, 10 of 10 questions, no personal value, and a re-run that writes nothing ($3.41).

Round 5 cost $18.50 in runs t to f, and $3.41 in the fixture's slice. Runs h to k, after round 4, cost $13.13. The ingestion skill is separate from the e-commerce skills the fixture uses, so the slice didn't run again for it.

## After design v0.7: personal data the business allows

Design v0.7's open question 7 found that the server's rule kept personal data out of every store, including where the store is the source, such as a supplier's contact. Whether a store holds personal data is the decision of the business that owns it (Victor, 2026-10-03). [packages](../../packages/README.md#allowing-personal-data) has what changed: `core/personal` in core 0.3.0, the server's rule, ecom-ops 0.4.1 and factstore-skills 0.3.1. The default is still none.

| Run | What it tests | Result | Cost |
|---|---|---|---|
| Round 5, run g | The new rule, on the round that tests it most | Passed every part of the mark: 8 of 8 questions, each message once, every fact citing its message, no personal data, no allowance written, and a re-run that wrote nothing | $2.27 |
| Fixture slice p | The fixture's slice, with nothing allowed | No personal value and no allowance. Product matching 1.0, 157 duplicate pairs, all 18 kinds (17 exact), nothing registered beyond the packages, and a re-run that wrote nothing. **9 of 10 questions** | $4.15 |
| Fixture slice q | The owner allows `supplier/contact_name`; then the catalogue and ingestion run | Ingestion filled the contact's name for all 8 suppliers, each right. No other person's name or address anywhere, and no customer's | $2.99 |
| Fixture slices r, s and t | Ecom-ops 0.4.2, below, with nothing allowed | Each: **10 of 10 questions**, and 43 of 43 POs in production. Product matching 1.0, 157 duplicate pairs, all 18 kinds exact, nothing registered beyond the packages, every transaction citing its document, no personal data, and a re-run that wrote nothing | $3.78, $4.09, $4.00 |

- **Slice p's miss was not the change, but it was larger than one question.**
  - Question 10 needs PO-2026-0028 in production. That comes from the supplier's WeChat reply "Received, thank you", which acknowledges the deposit only when read after the message before it.
  - Ingestion's script matched only `收到，谢谢`, so it skipped the reply. Slice l, before any of this, did the same. Ingestion's only change for p was one bullet on contact names, in its proforma invoice section.
  - A new measure counts the POs a store ever put in production. The chats state 43 of the world's 47; the other 4 have no message saying so:

    | Slice | l | m | n | o | p | q | r | s | t |
    |---|---|---|---|---|---|---|---|---|---|
    | In production, of 43 | 30 | 40 | 43 | 43 | 30 | 43 | 43 | 43 | 43 |
    | Chat messages recorded | 96 | 106 | 124 | 124 | 111 | 124 | 124 | 124 | 124 |

  - Half the slices missed some, and the questions caught it only in l and p. Slices a to k's stores are gone, so they can't be measured.
- **The fix, ecom-ops 0.4.2.** Its skill says what an acknowledgement moves, how to find its PO, and to read the replies after each of our messages and check the script against them. Its examples are phrasings the fixture doesn't use ([packages](../../packages/README.md#decisions)).
  - Slices r, s and t ran on it, and each reached 43 of 43. Before it, 3 of l to q's 6 did. At that rate, three in a row would happen one time in eight, so three runs make the fix likely, not certain.
  - Each report shows the agent reading replies in context. r gave 8 replies 0.8 instead of 0.9, because other messages sat between our deposit message and the reply. s listed the three phrasings it took as acknowledgements, in Chinese and English. t weighed two plain "OK" replies against the acknowledgements that followed them.
- **Round 5's evidence count** had counted a transaction that only improved two attributes' docs. A schema change cites no document, so the measure now leaves such transactions out, and rescoring recomputes it.

## Status

Every round has run. Rounds 0, 1, 2, 3 and 5 passed their marks. Round 4, on VRDU's ad-buy forms, passed its mark on run f. On the skill text round 4 left, round 5's run k met every part of its mark but one question, whose answer the store holds. The evals spent $33.10 of the $35 Victor first set (2026-10-04), then about $64 more on the runs he approved after it. [Design v0.7](../../factstore-design.md) has every round's findings.
