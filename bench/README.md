# M1 load benchmark

How fast the kernel ingests the synthetic brand ([fixture](../fixture)) through `transact`. The build plan sets no threshold yet; these numbers feed its single-writer risk.

All runs: Apple Silicon (arm64), 8 GB RAM; Postgres 17 in Docker with 3.8 GB of VM memory and stock settings (128 MB `shared_buffers`, 1 GB `max_wal_size`); Python 3.13. Facts per second counts what the log grew by, including the kernel's two stamps per transaction. An order is about 5.4 facts.

## By transaction size and writers

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

## At 10M facts

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

## What it means for the plan

**The single-writer risk is not a risk at design-partner scale.** The default world, a brand doing about $4M a year, writes about 360k facts for nine months of orders plus fifteen months of purchasing history. That loads in about 40 seconds at the rate in the 10M run, and in about 11 at the 1,000-orders-a-transaction rate. A store 30 times that size still takes single-order writes in 3 ms.

## Reproduce

```bash
cd fixture
../factstore/.venv/bin/factstore-fixture bench --admin-dsn "$FACTSTORE_ADMIN_DSN" --out ../bench/results-batches.md
../factstore/.venv/bin/python ../bench/run_10m.py ../bench/results-10m.json   # about 20 minutes
```
