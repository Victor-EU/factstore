"""Build a store of about 10M facts and keep it, for timing reads (build plan M2's query budget).

    python build_store.py NAME [FACTS]

Writes the credential and the as-of marks to NAME.json beside this script (git-ignored: it holds
a password). Drop the store with `factstore drop NAME --yes` when done.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from factstore import connect
from factstore_fixture.bench import FACTS_PER_SCALE
from factstore_fixture.clock import US_EAST
from factstore_fixture.load import load, new_store
from factstore_fixture.simulate import Simulation

ADMIN = "postgresql://postgres:postgres@localhost:54329/postgres"

name = sys.argv[1]
facts = int(sys.argv[2]) if len(sys.argv) > 2 else 10_000_000
scale = max(1.0, facts / FACTS_PER_SCALE)

cred = new_store(ADMIN, name)
started = time.time()
with connect(cred.dsn) as store:
    stats = load(store, Simulation(7, scale, keep_outbound=False), batch=1000,
                 marks=[datetime(2026, 7, 1, tzinfo=US_EAST)],
                 progress=lambda s: s.orders % 100_000 == 0 and print(f"{s.orders:,} orders", flush=True))
    total = store.conn.execute("select count(*) from fact").fetchone()[0]
out = {"dsn": cred.dsn, "scale": round(scale, 2), "facts": total, "seconds": round(time.time() - started),
       "marks": {k.isoformat(): v for k, v in stats.marks.items()}}
Path(__file__).with_name(f"{name}.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
