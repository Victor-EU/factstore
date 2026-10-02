# factstore-fixture

A synthetic cross-border brand for testing and benchmarking factstore (build plan M1). It plays the role a design partner's data will play in M5, so M1–M4 never wait on one.

**Acme Hearth** sells kitchen and home goods made by eight factories in China, through Shopify and Amazon FBA, from a 3PL in Edison, NJ. All companies and people are fictional. Every email address uses a reserved `.example` domain and every phone number is in the 555-01xx fictional range.

## Run it

```bash
cd fixture
../factstore/.venv/bin/pip install -e .
../factstore/.venv/bin/factstore-fixture report                 # realism report for the default world
../factstore/.venv/bin/factstore-fixture export ./out           # source files plus ground truth
../factstore/.venv/bin/factstore-fixture load "<writer credential>"   # for a store with packages/ecom-ops installed
../factstore/.venv/bin/factstore-fixture bench --admin-dsn "$FACTSTORE_ADMIN_DSN"
../factstore/.venv/bin/pytest
```

`--seed` picks the world and `--scale` multiplies demand: scale 1 is a brand doing about $4M a year. Everything is deterministic for a given seed, scale and code version.

## How the world works

A day-by-day simulation from July 2025 to 09:00 on 1 October 2026 ([simulate.py](src/factstore_fixture/simulate.py)). Nothing is scripted; each record comes from the process that produces it in a real business.

- **Demand** follows the US retail calendar ([clock.py](src/factstore_fixture/clock.py)):
  - monthly seasonality and weekday patterns, plus brand growth;
  - Valentine's Day, Mother's Day, Memorial Day, the July 4 sale, Prime Day, back to school, Labor Day;
  - Black Friday/Cyber Monday and Prime Big Deal Days in the 2025 warm-up;
  - orders arrive at local times of day in shoppers' time zones.
- **Shopify orders:**
  - 26% from returning customers, and about 1.5% of new accounts are someone who already has one;
  - gift addresses, discount codes during sales, free shipping over $75, state sales tax;
  - cancellations (customer, fraud, inventory), returns, and partial refunds for broken ceramics and glass.
- **Amazon orders:** Prime Day deals, coupons and marketplace tax. Customers are opaque, as they are on Amazon.
- **Stock limits sales.** Shopify ships from the 3PL and Amazon from FBA. When a SKU runs out, the sale is lost.
- **Purchasing:**
  - A buyer reviews stock against a seasonal forecast every Monday. A supplier that needs a PO pulls the others on the same port forward, so they can share a container.
  - Minimum order quantities and order values apply, and quantities round to whole cartons.
  - Each supplier has its own PI number format, payment terms (30–50% deposit, 100% before shipment, or balance against a B/L copy), and currency (USD or RMB).
  - Announced price changes take effect on their dates.
- **Factories** work Monday to Saturday on China's calendar:
  - New Year, a three-week Chinese New Year shutdown and a slow restart, Qingming, Labour Day, Dragon Boat, Mid-Autumn and Golden Week;
  - quotes are optimistic, and January quotes ignore half the New Year shutdown;
  - production slips are announced in WeChat;
  - third-party AQL inspections fail at realistic rates for ceramics and glass, leading to rework and re-inspection.
- **Freight:**
  - weekly sailings per port and route to New York/Newark or Los Angeles, with LA cargo transloaded and railed to New Jersey;
  - the forwarder consolidates POs into 40HQ, 20GP or LCL by CBM;
  - container numbers carry valid ISO 6346 check digits;
  - bookings get rolled, vessels arrive late, and peak-season surcharges apply.
- **Customs:** entries carry an HTS duty, Section 301 duty, an additional China tariff, MPF with its minimum and maximum, and HMF. Rates are illustrative.
- **3PL:** receiving with short cartons and breakage, weekly FBA replenishment to East Coast fulfilment centres, Amazon receiving backlogs before Prime Day and in Q4, and a monthly invoice.
- **QuickBooks:** deposit, balance, freight, duty and 3PL bills, payments, and RMB bills at the day's exchange rate.

`factstore-fixture report` checks the outcome against how such a brand runs: lead times, slip rates, the container mix, duty share, stockouts and the returning-customer share. `tests/test_realism.py` holds those properties.

## Messy on purpose

These are the problems the catalogue and ingestion skills will meet:

- **SKU codes:**
  - Shopify variant SKUs are sometimes reformatted;
  - the 3PL's client SKUs are sometimes blank or mistyped;
  - Amazon seller SKUs sometimes carry `-FBA`;
  - factory item codes repeat across factories;
  - HS codes are shared by many SKUs.
- **Names:** QuickBooks vendor names differ from legal names, and PO references in memos come in four spellings.
- **Supplier documents:** factories describe items in their own words, Chinese first.
- **WeChat:**
  - mixed Chinese and English, with dates written as `3/8` or `3月8号`;
  - voice notes, photos, stickers and small talk;
  - timestamps in New York time, from the ops manager's phone.
- **Customers:** duplicate Shopify accounts made with plus aliases or another email provider.

## Outputs

| Directory | What | Shape |
|---|---|---|
| `shopify/` | products and variants; orders and line items | GraphQL bulk-operation JSONL with `__parentId` |
| `amazon/` | All Orders report, FBA inventory, inbound shipments | Seller Central tab-delimited flat files, CSV |
| `3pl/` | inventory snapshot, receipts, outbound | the warehouse's CSVs |
| `quickbooks/` | vendor list, transaction list by vendor | QuickBooks Online report CSVs |
| `supplier_docs/` | proforma invoices, commercial invoices with packing lists, QC reports | PDF, Chinese and English |
| `wechat/` | one chat export per supplier | text |
| `email/` | forwarder, broker and 3PL mail | mbox |
| `truth/` | SKU crosswalk, vendors, duplicate customers, statements in the documents and chats, shapes | CSV, JSONL, JSON |

Orders cover the year to date. Purchasing history starts in July 2025.

## The direct loader

`load` writes the world through `transact` the way the skills eventually will:

- **Full facts** for what the store is primary for: suppliers, SKUs and their crosswalk identifiers, POs, inspections, shipments, customs entries, and stock at factories and on the water.
- **Identifiers and join keys only** for what Shopify, Amazon and the 3PL own (the design's default for open question 2).
- **Nothing from QuickBooks**, which holds the general ledger.

Every entity is addressed through an identity attribute, so loading twice creates no new entities. The purchasing history is replayed in order, so a second load re-records past status changes.

Duplicate Shopify accounts get `core/same_as` pointing at the account they duplicate, as the catalogue skill would record after resolving them. Some form chains.

The store stamps transactions with the time they are written, not the simulated time, so as-of reads cannot use simulated dates directly. `load(..., marks=[instant])` reports the last transaction written before each simulated instant.

## The ten questions

[questions.py](src/factstore_fixture/questions.py) holds the ten questions of build plan M0, an operator's questions about the supply side. Each comes with a reference answer, computed by a naive fold over the log, and reference SQL. The OQ1 spike chose the query language with them, and `tests/test_questions.py` answers them through `query`.

The loader writes with 93 attributes:
- 13 from factstore-core, which `init` installs;
- 69 from factstore-ecom-ops, which the store needs installed (`new_store` in [load.py](src/factstore_fixture/load.py) makes one that has it);
- 11 sales-side identifiers it registers itself ([vocabulary.py](src/factstore_fixture/vocabulary.py)), as the catalogue skill would on its first run.

The kernel's near-match check flags 18 pairs among them, each declared with `distinct_from` in the manifests or in `vocabulary.py`. Some are real overlaps, such as `amazon/order_id` against `shopify/order_id`. Others are false positives from shared namespaces or templated docs, such as `sku/code` against `sku/hs_code`, and `qc/inspector` against `qc/inspected_on`.

## Assumptions and simplifications

- Tariff rates, the RMB/USD path and Prime Day 2026's dates are assumptions. The Chinese holiday dates follow the published 2026 schedule.
- PDFs use Adobe's predefined Chinese font without embedding it. Text extracts correctly everywhere; viewers without Chinese fonts show blank glyphs.
- One 3PL, one forwarder, one broker. No returns to suppliers, Amazon fees, payouts, or advertising.
- Duplicate Amazon order IDs are possible in principle (random IDs) but vanishingly rare at these volumes.
