"""The M1 throughput benchmark: how fast the kernel ingests the fixture, by transaction size
and number of concurrent writers. No pass/fail threshold yet; the numbers feed the build
plan's single-writer risk.

For each configuration: a fresh store; master data and purchasing history loaded untimed;
then this year's orders timed, `batch` orders to a transaction. Facts per second counts
what the log grew by, including the kernel's two stamps per transaction.
"""

import json
import os
import platform
import queue
import secrets
import statistics
import threading
import time
from dataclasses import asdict, dataclass

import psycopg

from factstore import admin, connect

from .load import load, order_batches
from .simulate import Simulation

FACTS_PER_SCALE = 350_000  # sales facts a scale-1 world writes, measured


@dataclass
class Result:
    batch: int
    writers: int
    orders: int
    transactions: int
    facts: int
    seconds: float
    facts_per_second: float
    transactions_per_second: float
    p50_ms: float
    p95_ms: float
    log_facts: int
    database_mb: float


def run(admin_dsn: str, *, facts: int, batch: int, writers: int = 1, seed: int = 7, cap_facts: int | None = None,
        progress=None) -> Result:
    """One configuration. `facts` sets the world's size; `cap_facts` stops the timed phase early."""
    scale = max(1.0, facts / FACTS_PER_SCALE)
    name = f"bench_{secrets.token_hex(3)}"
    admin.init_store(admin_dsn, name)
    try:
        cred = admin.create_actor(admin_dsn, name, "benchmark loader")
        with connect(cred.dsn) as store:
            load(store, Simulation(seed, scale, keep_outbound=False), sales=False)
            before = _log_size(store)
        max_orders = None if cap_facts is None else max(batch, int(cap_facts / 5.1))
        latencies: list[float] = []
        lock = threading.Lock()
        work: queue.Queue = queue.Queue(maxsize=writers * 4)
        failures: list[BaseException] = []
        tx_count = [0]

        def writer():
            try:
                with connect(cred.dsn) as s:
                    while (facts_batch := work.get()) is not None:
                        t = time.perf_counter()
                        result = s.transact(facts_batch)
                        elapsed = time.perf_counter() - t
                        with lock:
                            latencies.append(elapsed)
                            tx_count[0] += result.tx is not None
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                failures.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(writers)]
        started = time.perf_counter()
        for t in threads:
            t.start()
        orders = 0
        for facts_batch in order_batches(Simulation(seed, scale, keep_outbound=False), batch, max_orders):
            if failures:
                break
            work.put(facts_batch)
            orders += batch
            if progress and orders % (batch * 200) == 0:
                progress(orders)
        for _ in threads:
            work.put(None)
        for t in threads:
            t.join()
        seconds = time.perf_counter() - started
        if failures:
            raise failures[0]
        with connect(cred.dsn) as store:
            written = _log_size(store) - before
            total = _log_size(store)
        with psycopg.connect(admin_dsn) as conn:
            size = conn.execute("select pg_database_size(%s)", (name,)).fetchone()[0] / 2**20
        latencies.sort()
        return Result(batch, writers, orders, tx_count[0], written, round(seconds, 1), round(written / seconds),
                      round(tx_count[0] / seconds, 1), round(statistics.median(latencies) * 1000, 1),
                      round(latencies[int(len(latencies) * 0.95)] * 1000, 1), total, round(size))
    finally:
        admin.drop_store(admin_dsn, name)


def _log_size(store) -> int:
    return store.conn.execute("select count(*) from fact").fetchone()[0]


def report(results: list[Result], facts: int, path: str | None = None) -> str:
    lines = ["# Load benchmark", "",
             f"World sized for {facts:,} facts. Machine: {platform.machine()}, {platform.system()} "
             f"{platform.release()}, Python {platform.python_version()}, Postgres in Docker.", "",
             "| Orders per tx | Writers | Orders | Transactions | Facts written | Seconds | Facts/s | Tx/s "
             "| p50 ms | p95 ms | Log size | DB MB |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.batch} | {r.writers} | {r.orders:,} | {r.transactions:,} | {r.facts:,} | {r.seconds} | "
                     f"{r.facts_per_second:,} | {r.transactions_per_second} | {r.p50_ms} | {r.p95_ms} | "
                     f"{r.log_facts:,} | {r.database_mb:,.0f} |")
    text = "\n".join(lines) + "\n"
    if path:
        with open(path, "w") as fh:
            fh.write(text)
        with open(os.path.splitext(path)[0] + ".json", "w") as fh:
            json.dump([asdict(r) for r in results], fh, indent=2)
    return text


def scale_run(admin_dsn: str, *, facts: int, batch: int = 1000, seed: int = 7, samples: int = 2000,
              progress=print) -> dict:
    """Load a world of `facts` facts at `batch` orders a transaction, recording throughput as the log
    grows; then time single-order writes against the full store, the way an agent writes."""
    scale = max(1.0, facts / FACTS_PER_SCALE)
    name = f"bench_{secrets.token_hex(3)}"
    admin.init_store(admin_dsn, name)
    try:
        cred = admin.create_actor(admin_dsn, name, "benchmark loader")
        with connect(cred.dsn) as store:
            t = time.perf_counter()
            load(store, Simulation(seed, scale, keep_outbound=False), sales=False)
            records_seconds = time.perf_counter() - t
            before_sales = _log_size(store)
            windows, written, window_facts, window_start = [], before_sales, 0, time.perf_counter()
            started = time.perf_counter()
            for n, facts_batch in enumerate(order_batches(Simulation(seed, scale, keep_outbound=False), batch), 1):
                result = store.transact(facts_batch)
                window_facts += len(result.facts) + 2
                if n % 100 == 0:
                    now = time.perf_counter()
                    written += window_facts
                    windows.append((written, round(window_facts / (now - window_start))))
                    progress(f"{written:>12,} facts in the log, {windows[-1][1]:>7,} facts/s")
                    window_facts, window_start = 0, now
            sales_seconds = time.perf_counter() - started
            total = _log_size(store)

            # One order per transaction against the full store: fresh orders for existing SKUs.
            skus = [row[0] for row in store.conn.execute(
                "select v_string from cur where a = (select id from attr where ident = 'sku/code')")]
            latencies = []
            for i in range(samples):
                order = ["shopify/order_id", f"90000{i:08d}"]
                line = ["shopify/line_item_id", f"90000{i:08d}1"]
                facts_ = [{"e": order, "a": "order/customer", "v": ["shopify/customer_id", f"90000{i % 500:08d}"]},
                          {"e": line, "a": "core/part_of", "v": order},
                          {"e": line, "a": "line/sku", "v": ["sku/code", skus[i % len(skus)]]}]
                t = time.perf_counter()
                store.transact(facts_)
                latencies.append(time.perf_counter() - t)
            latencies.sort()
        with psycopg.connect(admin_dsn) as conn:
            size = conn.execute("select pg_database_size(%s)", (name,)).fetchone()[0] / 2**30
        return {"facts_in_log": total, "scale": round(scale, 2), "batch": batch,
                "records_seconds": round(records_seconds), "sales_seconds": round(sales_seconds),
                "sales_facts_per_second": round((total - before_sales) / sales_seconds),
                "windows": windows, "database_gb": round(size, 2),
                "single_order_p50_ms": round(statistics.median(latencies) * 1000, 1),
                "single_order_p95_ms": round(latencies[int(len(latencies) * 0.95)] * 1000, 1),
                "single_order_p99_ms": round(latencies[int(len(latencies) * 0.99)] * 1000, 1)}
    finally:
        admin.drop_store(admin_dsn, name)
