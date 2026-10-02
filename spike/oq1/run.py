"""The spike's stand-in for the query tool. Reads one query on stdin and prints the result as JSON.

    python run.py sql|datalog|json [--as-of TX_OR_INSTANT] [--agent NAME] < query

Datalog rules, if any, follow the query vector in the same input. Every call is logged to
runs/<agent>.jsonl so the scoring can count attempts and errors.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import QueryError, load_db, to_json  # noqa: E402

MAX_ROWS = 1000


def run(lang: str, text: str, as_of=None):
    config = json.loads((HERE / "store.json").read_text())
    if lang == "sql":
        return run_sql(config["sql_reader_dsn"], text, as_of)
    if lang == "datalog":
        import datalog
        q = datalog.parse(text)
    elif lang == "json":
        import jsonpat
        q = jsonpat.parse(text)
    else:
        raise SystemExit(f"unknown language {lang}")
    from engine import Engine
    db = load_db(config["dsn"], as_of=_as_of(as_of))
    rows = Engine(db, q.rules).run(q)
    return q.columns, rows


def _as_of(as_of):
    if as_of is None:
        return None
    return int(as_of) if str(as_of).isdigit() else as_of


def run_sql(dsn, text, as_of):
    import psycopg

    with psycopg.connect(dsn) as conn:
        try:
            with conn.transaction():
                if as_of is not None:
                    if str(as_of).isdigit():
                        tx = int(as_of)
                    else:
                        tx = conn.execute('select max(e) from "fs/at" where v <= %s::timestamptz', (as_of,)).fetchone()[0] or 0
                    conn.execute("select set_config('factstore.as_of', %s, true)", (str(tx),))
                cur = conn.execute(text)
                if cur.description is None:
                    raise QueryError("the statement returned no rows")
                columns = [d.name for d in cur.description]
                rows = cur.fetchmany(MAX_ROWS + 1)
        except psycopg.Error as exc:
            raise QueryError(str(exc).strip())
    return columns, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lang", choices=["sql", "datalog", "json"])
    ap.add_argument("--as-of")
    ap.add_argument("--agent", default="manual")
    args = ap.parse_args()
    text = sys.stdin.read()
    started = time.perf_counter()
    entry = {"at": datetime.now(timezone.utc).isoformat(), "lang": args.lang, "as_of": args.as_of, "query": text}
    try:
        columns, rows = run(args.lang, text, args.as_of)
        truncated = len(rows) > MAX_ROWS
        rows = [[to_json(v) for v in row] for row in rows[:MAX_ROWS]]
        out = {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}
        entry.update(ok=True, row_count=len(rows))
    except QueryError as exc:
        out = {"error": str(exc)}
        entry.update(ok=False, error=str(exc))
    except RecursionError:
        out = {"error": "query too deep"}
        entry.update(ok=False, error=out["error"])
    entry["seconds"] = round(time.perf_counter() - started, 3)
    (HERE / "runs").mkdir(exist_ok=True)
    with open(HERE / "runs" / f"{args.agent}.jsonl", "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
