# Benchmarks

How fast the kernel ingests the synthetic brand ([fixture](../fixture)) through `transact` (M1, no threshold; these numbers feed the single-writer risk), and how fast it answers the ten questions through `query` (M2, proposed budget: under 1 s each at 10M facts).

All runs: Apple Silicon (arm64), 8 GB RAM; Postgres 17 in Docker with 3.8 GB of VM memory and stock settings (128 MB `shared_buffers`, 1 GB `max_wal_size`); Python 3.13. Facts per second counts what the log grew by, including the kernel's two stamps per transaction. An order is about 5.4 facts.

## Writes by transaction size and writers

[results-batches.md](results-batches.md): a 350k-fact world, about 12,000 of the year's orders timed per configuration.

| Orders per tx | Writers | Facts/s | Tx/s | p50 ms | p95 ms |
|---|---|---|---|---|---|
| 1 | 1 | 2,207 | 295 | 3.2 | 4.5 |
| 10 | 1 | 7,389 | 130 | 7.3 | 11.9 |
| 100 | 1 | 17,910 | 33 | 28.9 | 40.7 |
| 1000 | 1 | 32,107 | 6 | 152 | 246 |
| 10 | 4 | 8,412 | 148 | 25.9 | 38.3 |
| 100 | 4 | 23,228 | 42 | 86.3 | 111 |
| 1000 | 4 | 32,160 | 6 | 567 | 725 |

- **Agent-style writes run at about 300 transactions a second** (one order each, p50 3 ms). The cost is per transaction: a lock, a schema read, and four to six round trips. Caching the schema per connection is the obvious next saving.
- **Bulk ingestion is about 15 times faster per fact** at 1,000 orders a transaction.
- **Concurrent writers help only in the middle.** Each writer's Python-side validation overlaps the others' database time. Writes themselves are serialized by design, so at 1,000 orders a transaction four writers gain nothing and simply wait longer.

## Writes at 10M facts

[results-10m.json](results-10m.json): a world at 28.6 times the default demand (1.9M orders), loaded at 1,000 orders a transaction by one writer. Single-order writes were then timed against the full store.

| | |
|---|---|
| Facts in the log | 10,265,109 |
| Database size | 4.5 GB |
| Purchasing history (untimed setup) | 73 s |
| Orders | 1,133 s, 9,044 facts/s sustained |
| Throughput from 0.5M to 10M facts | 11,097 → 10,570 facts/s per 550k-fact window, dipping to 7,092 mid-run |
| Single-order write on the full store | p50 2.8 ms, p95 3.8 ms, p99 6.4 ms |

Throughput holds as the log grows. Single-order latency on a 10M-fact store matches the small store, because lookups go through the identity index.

At this size the bulk rate is about a third of the small-world figure. The database and its indexes no longer fit in Postgres's 128 MB of buffers or the 3.8 GB VM. I have not tested whether tuning `shared_buffers` and `max_wal_size` closes the gap; that is the next thing to try.

## Reads at 10M facts

[results-read-10m.json](results-read-10m.json): the ten questions' reference SQL through `query`, against a 10,276,481-fact store built by [build_store.py](build_store.py) (the default world at 28.6 times the demand, 4.8M entities). Five timed runs each after a warm-up; question 8 uses a customer with a duplicate chain in that store.

| Question | Median | Max |
|---|---|---|
| 1. In transit for a SKU | 5 ms | 12 ms |
| 2. POs whose ETD slipped (history) | 2 ms | 4 ms |
| 3. In transit as of 1 July (as-of) | 4 ms | 4 ms |
| 4. Customs totals for a quarter | 9 ms | 10 ms |
| 5. Inspections by supplier and result | 2 ms | 3 ms |
| 6. Crosswalk for an ASIN | 11 ms | 14 ms |
| 7. Open PO value by supplier | 3 ms | 3 ms |
| 8. Orders across duplicate accounts (recursive) | 161 ms | 315 ms |
| 9. Who recorded an ETD, and when | 3 ms | 5 ms |
| 10. Stock at factories and on the water | 2 ms | 3 ms |

**All ten are within the budget.** One design fix got them there, and the trap is easy to fall back into:
- The first version of the views combined current state and the as-of fold in one `UNION ALL`. Postgres cannot flatten that into the query, so a join on `e` scanned whole attributes, and a two-hop join over `core/same_as` ran past the 10 s timeout.
- Each view is now a plain select over one table: `current` reads `cur`; `asof` folds the log with an anti-join. `query` chooses between them with `search_path`.
- String equality also needed a hash index, because the btree on string values covers only their first 200 characters.

**`stats` takes 53 s at this size.** It groups 10M current values by entity. No budget is set for it, and the ontology skill calls it a handful of times. Sampling it, or keeping signatures up to date as facts are written, is the fix when it matters.

## What it means for the plan

**The single-writer risk is not a risk at design-partner scale.** The default world, a brand doing about $4M a year, writes about 360k facts for nine months of orders plus fifteen months of purchasing history. That loads in about 40 seconds at the rate in the 10M run, and in about 11 at the 1,000-orders-a-transaction rate. A store 30 times that size still takes single-order writes in 3 ms.

## Reproduce

```bash
cd fixture
../factstore/.venv/bin/factstore-fixture bench --admin-dsn "$FACTSTORE_ADMIN_DSN" --out ../bench/results-batches.md
../factstore/.venv/bin/python ../bench/run_10m.py ../bench/results-10m.json   # about 20 minutes
cd ../bench
../factstore/.venv/bin/python build_store.py fs_10m                           # keeps the store; 20-35 minutes
../factstore/.venv/bin/python read_latency.py fs_10m results-read-10m.json
```
