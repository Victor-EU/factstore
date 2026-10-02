"""The M1 benchmark at full size: a 10M-fact world. Writes bench/results-10m.json."""
import json
import sys
import time

from factstore_fixture.bench import scale_run

started = time.time()
result = scale_run("postgresql://postgres:postgres@localhost:54329/postgres", facts=10_000_000,
                   progress=lambda line: print(line, flush=True))
result["wall_seconds"] = round(time.time() - started)
with open(sys.argv[1] if len(sys.argv) > 1 else "results-10m.json", "w") as fh:
    json.dump(result, fh, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "windows"}, indent=2))
