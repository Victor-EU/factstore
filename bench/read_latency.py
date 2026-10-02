"""Build plan M2 budget: each of the ten questions under 1 s at 10M facts.

    python read_latency.py fs_10m [out.json]

Runs each question's reference SQL through query against a store built by build_store.py, five
times, after one warm-up run. The 10M world is the default world at higher demand, so its answers
differ; question 8's customer is replaced by one with a duplicate chain in this store, so it does
real work. Also times stats.
"""
import json
import statistics
import sys
import time
from pathlib import Path

from factstore import connect
from factstore_fixture.questions import REFERENCE_SQL

HERE = Path(__file__).resolve().parent
name = sys.argv[1]
config = json.loads((HERE / f"{name}.json").read_text())
july_1 = next(iter(config["marks"].values()))

with connect(config["dsn"]) as store:
    chained = store.query('select c.v from "core/same_as" s join "core/same_as" s2 on s2.e = s.v'
                          ' join "shopify/customer_id" c on c.e = s.v limit 1').rows[0][0]
    results = {}
    for qid, (sql, as_of) in REFERENCE_SQL.items():
        sql = sql.replace("8995877069469", chained)
        as_of = july_1 if as_of == "july_1" else as_of
        store.query(sql, as_of=as_of)
        times, rows = [], 0
        for _ in range(5):
            t = time.perf_counter()
            rows = len(store.query(sql, as_of=as_of).rows)
            times.append(time.perf_counter() - t)
        results[qid] = {"median_ms": round(statistics.median(times) * 1000), "max_ms": round(max(times) * 1000),
                        "rows": rows}
        print(f"Q{qid:<2} median {results[qid]['median_ms']:>6} ms  max {results[qid]['max_ms']:>6} ms  rows {rows}",
              flush=True)
    t = time.perf_counter()
    stats = store.stats()
    stats_seconds = round(time.perf_counter() - t, 1)
    print(f"stats: {stats_seconds} s, {stats.entities:,} entities, {len(stats.signatures)} signatures")
    total = store.conn.execute("select count(*) from fact").fetchone()[0]

out = {"store": name, "facts": total, "questions": results, "stats_seconds": stats_seconds}
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(json.dumps(out, indent=2))
