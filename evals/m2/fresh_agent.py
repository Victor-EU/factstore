"""Build plan M2 exit: a fresh agent given only the MCP server, with no extra prompt, answers the
ten questions and ingests a further sample using the attributes already registered.

    python fresh_agent.py [--model sonnet] [--part questions|ingest|both]

Each part runs `claude -p` in an empty directory with the factstore MCP server as its only tool:
no built-in tools, no other MCP servers, no project files. The store is the default fixture
world, loaded fresh for each part, with a new actor for the agent so its writes can be told
apart. Results go to results/<model>-<part>.json.
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from factstore import admin, connect
from factstore_fixture.load import load, new_store
from factstore_fixture.questions import JULY_1_MARK, QUESTIONS, World, answers
from factstore_fixture.simulate import Simulation

ADMIN = os.environ.get("FACTSTORE_ADMIN_DSN", "postgresql://postgres:postgres@localhost:54329/postgres")
HERE = Path(__file__).resolve().parent
SERVER = str(Path(__file__).resolve().parents[2] / "factstore" / ".venv" / "bin" / "factstore-mcp")

QUESTIONS_PROMPT = """\
Today is 1 October 2026. You have the company's fact store. Answer these questions from the \
operations manager.

{questions}

End your reply with the answers as JSON in a ```json block: {{"answers": [{{"question": 1, \
"rows": [["value", ...], ...]}}, ...]}}. One array per row, values in the order each question \
lists its columns, copied exactly from the query results."""

# What the sample should leave in the store: (entity lookup, attribute, value).
EXPECTED = [
    *[(["po/number", "PO-2026-0030"], a, v) for a, v in [
        ("po/supplier", ["supplier/code", "NBBW"]), ("po/placed_on", "2026-10-01"), ("core/currency", "USD"),
        ("po/pi_number", "MT261001-08"), ("po/etd", "2026-11-25"), ("po/status", "confirmed")]],
    *[(["po_line/key", f"PO-2026-0030/{n}"], a, v) for n, sku, qty, price in
      [(1, "AH-KTL-0001-SGE", "600", "11.20"), (2, "AH-CSR-0003-RED", "300", "16.50")]
      for a, v in [("core/part_of", ["po/number", "PO-2026-0030"]), ("po_line/sku", ["sku/code", sku]),
                   ("po_line/quantity", qty), ("po_line/unit_price", price)]],
    (["po/number", "PO-2026-0025"], "po/etd", "2026-10-27"),
    *[(["qc/report_no", "LCI-261001-047"], a, v) for a, v in [
        ("qc/po", ["po/number", "PO-2026-0023"]), ("qc/inspected_on", "2026-10-01"), ("qc/result", "PASS"),
        ("qc/inspector", "Linkcheck Inspection Services"), ("qc/sample_size", "200")]],
    *[(["shipment/booking_no", "PBLXMN2610032"], a, v) for a, v in [
        ("shipment/hbl", "PBLHB2600032"), ("shipment/mode", "20GP"), ("shipment/status", "booked"),
        ("shipment/origin", "CNXMN"), ("shipment/destination", "USNYC"), ("shipment/vessel", "MV Coral Meridian 112E"),
        ("shipment/etd", "2026-10-09T10:00:00+00:00"), ("shipment/eta", "2026-11-12T13:00:00+00:00"),
        ("shipment/freight_cost", "2850"), ("core/currency", "USD")]],
    *[(["shipment_line/key", f"PBLXMN2610032/{n}"], a, v) for n, qty, ctns in
      [(1, "660", "55"), (2, "1100", "55"), (3, "384", "32"), (4, "440", "22")]
      for a, v in [("core/part_of", ["shipment/booking_no", "PBLXMN2610032"]),
                   ("shipment_line/po_line", ["po_line/key", f"PO-2026-0023/{n}"]),
                   ("shipment_line/quantity", qty), ("shipment_line/cartons", ctns)]],
]


def setup(name: str):
    admin.drop_store(ADMIN, name)
    loader = new_store(ADMIN, name)
    with connect(loader.dsn) as store:
        stats = load(store, Simulation(7), batch=1000, marks=[JULY_1_MARK])
        july_1 = stats.marks[JULY_1_MARK]
        reference = answers(World(store.conn, july_1))
    agent = admin.create_actor(ADMIN, name, "fresh agent")
    return agent, july_1, reference


def run_claude(prompt: str, dsn: str, model: str, transcript: Path) -> dict:
    """Run the agent; keep its full transcript (every tool call and result) in `transcript`."""
    with tempfile.TemporaryDirectory() as empty:
        config = Path(empty) / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {"factstore": {
            "command": SERVER, "env": {"FACTSTORE_DSN": dsn}}}}))
        started = time.time()
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--mcp-config", str(config), "--strict-mcp-config",
             "--tools", "", "--allowedTools", "mcp__factstore", "--output-format", "stream-json", "--verbose",
             "--no-session-persistence"],
            cwd=empty, capture_output=True, text=True, timeout=3600)
        transcript.write_text(proc.stdout)
        events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
        out = next((e for e in reversed(events) if e.get("type") == "result"), {"result": proc.stdout[-3000:]})
        out["tool_calls"] = sum(1 for e in events if e.get("type") == "assistant"
                                for c in e["message"]["content"] if c.get("type") == "tool_use")
        out["wall_seconds"] = round(time.time() - started)
        out["stderr"] = proc.stderr[-2000:]
        return out


def norm(v):
    s = str(v).strip()
    try:
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return str(Decimal(s).normalize())
        if len(s) > 10 and s[4] == "-" and s[10] in "T ":
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    return s


def same(rows, expected):
    return Counter(tuple(norm(v) for v in r) for r in rows) == Counter(tuple(norm(v) for v in r) for r in expected)


def questions_part(model: str) -> dict:
    agent, july_1, reference = setup("fs_m2_questions")
    text = "\n".join(f"{q['id']}. {q['text'].format(july_1=july_1)} Columns: {', '.join(q['columns'])}."
                     for q in QUESTIONS)
    out = run_claude(QUESTIONS_PROMPT.format(questions=text), agent.dsn, model,
                     HERE / "results" / f"{model}-questions.stream.jsonl")
    block = re.findall(r"```json\s*(\{.*?\})\s*```", out.get("result", ""), re.S)
    given = {a["question"]: a["rows"] for a in json.loads(block[-1])["answers"]} if block else {}
    right = [q for q in reference if q in given and same(given[q], reference[q])]
    return {"model": model, "right": len(right), "wrong": sorted(set(reference) - set(right)),
            "answers": given, "turns": out.get("num_turns"), "tool_calls": out["tool_calls"], "cost_usd": out.get("total_cost_usd"),
            "wall_seconds": out["wall_seconds"], "final": out.get("result", "")[-3000:]}


def ingest_part(model: str) -> dict:
    agent, _, _ = setup("fs_m2_ingest")
    with connect(agent.dsn) as store:
        attrs_before = {r[0] for r in store.conn.execute("select ident from attr")}
    out = run_claude((HERE / "sample.md").read_text(), agent.dsn, model,
                     HERE / "results" / f"{model}-ingest.stream.jsonl")
    with connect(agent.dsn) as store:
        checks = [check(store, e, a, v) for e, a, v in EXPECTED]
        new_attrs = sorted({r[0] for r in store.conn.execute("select ident from attr")} - attrs_before)
        forced = store.query('select i.v from "fs/distinct_from" d join "fs/ident" i on i.e = d.e').rows
        written = store.query('select count(*) from "fs/actor" where v = %d' % agent.actor).rows[0][0]
        # The rebooking must move PO-2026-0023's cargo, not book it twice.
        booked_twice = store.query("""
            select pl.v, count(*) from "shipment_line/po_line" sl join "po_line/key" pl on pl.e = sl.v
            where pl.v like 'PO-2026-0023/%' group by pl.v having count(*) > 1""").rows
    return {"model": model, "expected": len(checks), "present": sum(c["ok"] for c in checks),
            "missing": [c for c in checks if not c["ok"]], "new_attributes": new_attrs,
            "registered_with_distinct_from": [r[0] for r in forced if r[0] in new_attrs],
            "lines_booked_twice": booked_twice,
            "agent_transactions": written, "turns": out.get("num_turns"), "tool_calls": out["tool_calls"], "cost_usd": out.get("total_cost_usd"),
            "wall_seconds": out["wall_seconds"], "final": out.get("result", "")[-3000:]}


def check(store, lookup, attribute, expected) -> dict:
    """Is `expected` a current value of `attribute` on the entity `lookup` names?"""
    rows = store.query(
        'select a.v::text from "%s" a join "%s" k using (e) where k.v = \'%s\'' % (attribute, lookup[0], lookup[1])).rows
    if isinstance(expected, list):  # a ref, given as a lookup
        target = store.query("select e::text from \"%s\" where v = '%s'" % (expected[0], expected[1])).rows
        want = target[0][0] if target else None
    else:
        want = expected
    got = [r[0] for r in rows]
    ok = want is not None and any(norm(g) == norm(want) for g in got)
    return {"entity": lookup, "attribute": attribute, "expected": expected, "got": got, "ok": ok}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--part", choices=["questions", "ingest", "both"], default="both")
    args = ap.parse_args()
    (HERE / "results").mkdir(exist_ok=True)
    for part in (["questions", "ingest"] if args.part == "both" else [args.part]):
        result = questions_part(args.model) if part == "questions" else ingest_part(args.model)
        (HERE / "results" / f"{args.model}-{part}.json").write_text(json.dumps(result, indent=1, default=str))
        print(json.dumps({k: v for k, v in result.items() if k not in ("final", "answers")}, indent=1, default=str))
