"""Load the default fixture world into a store for the OQ1 spike. Prints the credential and the
as-of marks as JSON."""
import json
import sys
from datetime import datetime

import factstore
from factstore import admin
from factstore_fixture.clock import US_EAST
from factstore_fixture.load import load, new_store
from factstore_fixture.simulate import Simulation

ADMIN = "postgresql://postgres:postgres@localhost:54329/postgres"
name = sys.argv[1] if len(sys.argv) > 1 else "fs_spike"

admin.drop_store(ADMIN, name)
cred = new_store(ADMIN, name)
reader = admin.create_actor(ADMIN, name, "spike reader")
store = factstore.connect(cred.dsn)
marks = [datetime(2026, 7, 1, tzinfo=US_EAST)]
stats = load(store, Simulation(7), batch=1000, marks=marks)
out = {"dsn": cred.dsn, "reader_dsn": reader.dsn, "facts": stats.facts, "transactions": stats.transactions,
       "seconds": round(stats.seconds, 1), "marks": {k.isoformat(): v for k, v in stats.marks.items()}}
print(json.dumps(out, indent=2))
