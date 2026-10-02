"""Scoring: compare answers with the reference, value by value, ignoring row order.

    python score.py reference            # compute and save the reference answers
    python score.py handwritten          # check the hand-written queries in every language
    python score.py answers FILE...      # score agents' final answers
"""

import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def norm(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float, Decimal)):
        return str(Decimal(str(v)).normalize())
    s = str(v).strip()
    try:
        return str(Decimal(s).normalize()) if s and s.replace(".", "", 1).lstrip("-").isdigit() else _time(s)
    except InvalidOperation:
        return s


def _time(s):
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) > 10 and s[4] == "-" and s[10] in "T ":
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return s


def same(rows, expected) -> bool:
    return Counter(tuple(norm(v) for v in r) for r in rows) == Counter(tuple(norm(v) for v in r) for r in expected)


def reference():
    import psycopg

    from questions import World, answers

    store = json.loads((HERE / "store.json").read_text())
    with psycopg.connect(store["dsn"]) as conn:
        ref = answers(World(conn))
    out = {str(k): [[norm(v) for v in r] for r in rows] for k, rows in ref.items()}
    (HERE / "reference.json").write_text(json.dumps(out, indent=1))
    return out


def load_reference():
    return {int(k): v for k, v in json.loads((HERE / "reference.json").read_text()).items()}


def handwritten():
    from handwritten import ALL
    from run import run

    ref = load_reference()
    ok = True
    for lang, queries in ALL.items():
        for qid, (text, as_of) in queries.items():
            try:
                _, rows = run(lang, text, as_of)
                good = same(rows, ref[qid])
            except Exception as exc:  # noqa: BLE001 - report every failure
                rows, good = repr(exc), False
            ok &= good
            print(f"{lang:8} Q{qid:<2} {'ok' if good else 'WRONG'}" + ("" if good else f"  got {rows!r}"))
    return ok


def score_answers(paths):
    """One row per agent: answers right, which were wrong, and how much querying it took."""
    ref = load_reference()
    table = []
    for path in sorted(paths):
        agent = Path(path).stem
        data = json.loads(Path(path).read_text())
        answers = {int(a["question"]): a for a in data["answers"]}
        right = [qid for qid in ref if qid in answers and same(answers[qid].get("rows", []), ref[qid])]
        log = [json.loads(line) for line in open(HERE / "runs" / f"{agent}.jsonl")]
        errors = sum(1 for r in log if not r["ok"])
        table.append({"agent": agent, "right": len(right), "wrong": sorted(set(ref) - set(right)),
                      "queries": len(log), "errors": errors})
    print("| Agent | Right | Wrong | Queries | Errors |")
    print("|---|---|---|---|---|")
    for t in table:
        print(f"| {t['agent']} | {t['right']}/10 | {', '.join(map(str, t['wrong'])) or '-'} | {t['queries']} | {t['errors']} |")
    (HERE / "results.json").write_text(json.dumps(table, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "reference":
        reference()
    elif cmd == "handwritten":
        sys.exit(0 if handwritten() else 1)
    elif cmd == "answers":
        score_answers(sys.argv[2:])
