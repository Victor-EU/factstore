"""Build plan M4 exit, on the fixture's exports: crosswalk precision and recall against the known
crosswalk; a second catalogue run creates no new entities; the ontology skill recovers the known
shapes; the ingestion skill extracts the PDFs with evidence on every transaction.

    python run.py --part catalogue|ingest|ontology [--model sonnet] [--budget 15]

Each part runs `claude -p` in a fresh directory holding the part's skill (in .claude/skills) and,
for catalogue and ingest, a read-only copy of the exports it reads, without truth/. The tools are
the factstore MCP server, plus a shell and file tools for the parts that read files. Bash runs in
Claude Code's sandbox, writing only inside the directory; Write and Edit are allowed only there.
No other MCP servers or user settings load. The agent's credential is in FACTSTORE_DSN, for the
SDK. Results go to results/<model>-<part>.json, with transcripts and the agent's own files.
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import score
from factstore import admin, connect, packages
from factstore_fixture.exports import export
from factstore_fixture.load import load, load_reference, new_store
from factstore_fixture.simulate import Simulation

ADMIN = os.environ.get("FACTSTORE_ADMIN_DSN", "postgresql://postgres:postgres@localhost:54329/postgres")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENV = REPO / "factstore" / ".venv" / "bin"
SKILLS = packages.load(REPO / "factstore-skills")
ECOM_OPS = packages.load(REPO / "packages" / "ecom-ops")

CATALOGUE_PROMPT = """\
Today is 1 October 2026. The company's systems are exported in ./exports: Shopify, Amazon \
Seller Central, the 3PL warehouse, QuickBooks, supplier documents, WeChat chats with suppliers and \
the ops inbox. Catalogue them into the fact store with the factstore-catalogue skill."""

INGEST_PROMPT = """\
Today is 1 October 2026. Ingest the supplier documents in ./exports/supplier_docs into the fact \
store with the ecom-ops-ingest-documents skill. The store already holds our suppliers and our SKUs \
with their factory item codes."""

MESSAGES_PROMPT = """\
Today is 1 October 2026. Ingest our WeChat chats with suppliers in ./exports/wechat and the ops \
inbox in ./exports/email into the fact store with the ecom-ops-ingest-documents skill. The \
supplier PDFs are already ingested. The chat exports come from our ops manager's phone, so their \
timestamps are New York time."""

ONTOLOGY_PROMPT = """\
What kinds of thing does the fact store hold? Use the factstore-ontology skill, and propose names \
for me to confirm."""

ONTOLOGY_CONFIRM = "I confirm them all, as you proposed them. Please record them."

FILE_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill"]


def owner(store: str) -> psycopg.Connection:
    conn = psycopg.connect(make_conninfo(ADMIN, dbname=store), autocommit=True)
    conn.execute("set search_path = current, public")
    return conn


def workdir(root: Path, skills: list[Path], export_dir: Path | None, sources: list[str]) -> Path:
    """The agent's directory: its skills, and a read-only copy of the sources it is given."""
    work = root / "work"
    for skill in skills:
        name = (skill / "SKILL.md").read_text().split("name: ", 1)[1].split("\n", 1)[0]
        shutil.copytree(skill, work / ".claude" / "skills" / name)
    for source in sources:
        shutil.copytree(export_dir / source, work / "exports" / source)
    for path in sorted((work / "exports").rglob("*"), reverse=True) if sources else []:
        path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    (work / "exports").chmod(0o555) if sources else None
    return work


def run_claude(prompt: str, work: Path, dsn: str, model: str, transcript: Path, tools: list[str], budget: float,
               resume: str | None = None, keep_session: bool = False) -> dict:
    """Run one agent session. Sessions aren't saved, unless `keep_session` (to resume it) or `resume`."""
    config = work.parent / "config"
    config.mkdir(exist_ok=True)
    (config / "mcp.json").write_text(json.dumps({"mcpServers": {"factstore": {
        "command": str(VENV / "factstore-mcp"), "env": {"FACTSTORE_DSN": dsn}}}}))
    (config / "settings.json").write_text(json.dumps({
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False,
                    "network": {"allowLocalBinding": True}},
        "permissions": {"defaultMode": "dontAsk", "allow": [
            *[t for t in tools if t not in ("Write", "Edit")], "Write(./**)", "Edit(./**)", "mcp__factstore"]}}))
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTSTORE_")}
    env.update(FACTSTORE_DSN=dsn, PATH=f"{VENV}:{env['PATH']}")
    cmd = ["claude", "-p", prompt, "--model", model, "--mcp-config", str(config / "mcp.json"),
           "--strict-mcp-config", "--setting-sources", "project", "--settings", str(config / "settings.json"),
           "--tools", ",".join(tools), "--output-format", "stream-json", "--verbose",
           "--max-budget-usd", str(budget)]
    if resume:
        cmd += ["--resume", resume]
    elif not keep_session:
        cmd += ["--no-session-persistence"]
    started = time.time()
    proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=4 * 3600,
                          stdin=subprocess.DEVNULL)
    password = conninfo_to_dict(dsn).get("password")
    text = proc.stdout.replace(password, "<password>") if password else proc.stdout
    transcript.write_text(text)
    events = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
    out = next((e for e in reversed(events) if e.get("type") == "result"), {"result": text[-3000:]})
    out["tool_calls"] = sum(1 for e in events if e.get("type") == "assistant"
                            for c in e["message"]["content"] if c.get("type") == "tool_use")
    out["skill_used"] = [c["input"].get("skill") for e in events if e.get("type") == "assistant"
                         for c in e["message"]["content"] if c.get("type") == "tool_use" and c["name"] == "Skill"]
    out["wall_seconds"] = round(time.time() - started)
    out["stderr"] = proc.stderr[-2000:]
    return out


def summary(out: dict) -> dict:
    return {"turns": out.get("num_turns"), "tool_calls": out["tool_calls"], "cost_usd": out.get("total_cost_usd"),
            "wall_seconds": out["wall_seconds"], "skill_used": out["skill_used"], "subtype": out.get("subtype"),
            "final": (out.get("result") or "")[-4000:]}


def scratchpads(work: Path) -> list[Path]:
    """Claude Code gives each session a scratchpad outside its directory, named after the directory."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(work.resolve()))
    return sorted(Path("/private/tmp").glob(f"claude-*/{slug}/*/scratchpad"))


KEEP = {".py", ".md", ".sh", ".sql"}


def keep_files(work: Path, dest: Path) -> list[str]:
    """Copy the agent's scripts and notes, from its directory or its scratchpad, next to the results.
    Returns the other files it left, such as extracted text, which are not kept."""
    skipped = []
    found = [(p, p.relative_to(work)) for p in work.rglob("*")]
    found += [(p, Path("scratchpad") / p.relative_to(pad)) for pad in scratchpads(work) for p in pad.rglob("*")]
    for path, rel in found:
        if not path.is_file() or rel.parts[0] in ("exports", ".claude"):
            continue
        if path.suffix not in KEEP or path.stat().st_size > 512 * 1024:
            skipped.append(f"{rel} ({path.stat().st_size // 1024} KB)")
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest / rel)
    return skipped


def remove(path: Path) -> None:
    """rmtree, after giving back the write permission the exports' copy was stripped of."""
    for p in [path, *path.rglob("*")]:
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
    shutil.rmtree(path)


def fresh(store: str) -> None:
    admin.drop_store(ADMIN, store)
    admin.init_store(ADMIN, store)
    admin.install(ADMIN, store, [ECOM_OPS, SKILLS])


def catalogue_part(model: str, budget: float, root: Path) -> dict:
    store = "fs_m4_catalogue"
    fresh(store)
    agent = admin.create_actor(ADMIN, store, "catalogue agent")
    export_dir = root / "export"
    export(str(export_dir))
    sources = sorted(p.name for p in export_dir.iterdir() if p.is_dir() and p.name != "truth")
    work = workdir(root, [REPO / "factstore-skills" / "catalogue"], export_dir, sources)
    result = {"model": model, "runs": []}
    for n in (1, 2):
        with owner(store) as conn:
            before = score.snapshot(conn)
        out = run_claude(CATALOGUE_PROMPT, work, agent.dsn, model,
                         HERE / "results" / f"{model}-catalogue-run{n}.stream.jsonl", FILE_TOOLS, budget)
        with owner(store) as conn:
            run = {"run": n, **summary(out), "wrote": score.since(conn, before),
                   "crosswalk": score.crosswalk(conn, export_dir / "truth"),
                   "duplicates": score.duplicates(conn, export_dir / "truth", export_dir),
                   "personal_data": score.personal_data(conn, export_dir),
                   "indexed": score.index_counts(conn),
                   "registered": score.registered_beyond(conn, agent.actor)}
        result["runs"].append(run)
        dest = HERE / "results" / f"{model}-catalogue-run{n}-files"
        shutil.rmtree(dest, ignore_errors=True)
        run["files_skipped"] = keep_files(work, dest)
        if n == 1:  # the second run is a fresh agent in a fresh directory
            remove(work)
            work = workdir(root / "second", [REPO / "factstore-skills" / "catalogue"], export_dir, sources)
    return result


def ingest_part(model: str, budget: float, root: Path) -> dict:
    store = "fs_m4_ingest"
    fresh(store)
    loader = admin.create_actor(ADMIN, store, "fixture loader")
    with connect(loader.dsn) as s:
        load_reference(s, Simulation(7))
    agent = admin.create_actor(ADMIN, store, "ingestion agent")
    export_dir = root / "export"
    export(str(export_dir))
    work = workdir(root, [REPO / "packages" / "ecom-ops" / "ingest-documents"], export_dir, ["supplier_docs"])
    with owner(store) as conn:
        before = score.snapshot(conn)
    out = run_claude(INGEST_PROMPT, work, agent.dsn, model, HERE / "results" / f"{model}-ingest.stream.jsonl",
                     FILE_TOOLS, budget)
    with owner(store) as conn:
        result = {"model": model, **summary(out), "wrote": score.since(conn, before),
                  "evidence": score.evidence(conn, agent.actor),
                  "documents": score.documents(conn, export_dir / "supplier_docs"),
                  "statements": score.pdf_statements(conn, export_dir),
                  "indexed": score.index_counts(conn),
                  "registered": score.registered_beyond(conn, agent.actor)}
    dest = HERE / "results" / f"{model}-ingest-files"
    shutil.rmtree(dest, ignore_errors=True)
    result["files_skipped"] = keep_files(work, dest)
    return result


def messages_part(model: str, budget: float, root: Path) -> dict:
    """Chats and email, on the store the ingest part left: beyond the M4 exit, for M5 and OQ5."""
    store = "fs_m4_ingest"
    with owner(store) as conn:
        if not score.has_attr(conn, "document/hash") or not rows_exist(conn):
            raise SystemExit("run --part ingest first: this part continues from its store")
        before = score.snapshot(conn)
    agent = admin.create_actor(ADMIN, store, "message agent")
    export_dir = root / "export"
    export(str(export_dir))
    work = workdir(root, [REPO / "packages" / "ecom-ops" / "ingest-documents"], export_dir, ["wechat", "email"])
    out = run_claude(MESSAGES_PROMPT, work, agent.dsn, model, HERE / "results" / f"{model}-messages.stream.jsonl",
                     FILE_TOOLS, budget)
    with owner(store) as conn, owner(reference_store()) as reference:
        result = {"model": model, **summary(out), "wrote": score.since(conn, before),
                  "evidence": score.evidence(conn, agent.actor),
                  "statements": score.message_statements(conn, export_dir),
                  "questions": score.questions(conn, reference),
                  "indexed": score.index_counts(conn),
                  "registered": score.registered_beyond(conn, agent.actor)}
    dest = HERE / "results" / f"{model}-messages-files"
    shutil.rmtree(dest, ignore_errors=True)
    result["files_skipped"] = keep_files(work, dest)
    return result


def reference_store() -> str:
    """The default world written by the direct loader: what the documents describe. Built once."""
    name = "fs_m4_reference"
    try:
        owner(name).close()
    except psycopg.OperationalError:
        loader = new_store(ADMIN, name)
        with connect(loader.dsn) as s:
            load(s, Simulation(7), batch=1000)
    return name


def rows_exist(conn) -> bool:
    return conn.execute('select count(*) from current."document/hash"').fetchone()[0] > 0


def ontology_part(model: str, budget: float, root: Path) -> dict:
    store = "fs_m4_ontology"
    admin.drop_store(ADMIN, store)
    loader = new_store(ADMIN, store)
    admin.install(ADMIN, store, [SKILLS])
    with connect(loader.dsn) as s:
        load(s, Simulation(7), batch=1000)
    agent = admin.create_actor(ADMIN, store, "ontology agent")
    export_dir = root / "export"
    export(str(export_dir))  # for truth/shapes.json
    work = workdir(root, [REPO / "factstore-skills" / "ontology"], None, [])
    work.mkdir(exist_ok=True)
    first = run_claude(ONTOLOGY_PROMPT, work, agent.dsn, model, HERE / "results" / f"{model}-ontology-propose.stream.jsonl",
                       ["Skill"], budget, keep_session=True)
    with owner(store) as conn:
        recorded_before_confirming = score.shapes(conn, export_dir / "truth")["recorded"]
    second = run_claude(ONTOLOGY_CONFIRM, work, agent.dsn, model, HERE / "results" / f"{model}-ontology-record.stream.jsonl",
                        ["Skill"], budget, resume=first.get("session_id"))
    with owner(store) as conn:
        return {"model": model, "propose": summary(first), "record": summary(second),
                "recorded_before_confirming": recorded_before_confirming,
                "shapes": score.shapes(conn, export_dir / "truth")}


PARTS = {"catalogue": catalogue_part, "ingest": ingest_part, "messages": messages_part, "ontology": ontology_part}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=[*PARTS, "all"], default="all")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--budget", type=float, default=15.0, help="USD cap per agent session")
    args = ap.parse_args()
    (HERE / "results").mkdir(exist_ok=True)
    for part in PARTS if args.part == "all" else [args.part]:
        tmp = Path(tempfile.mkdtemp(prefix=f"m4-{part}-"))
        try:
            result = PARTS[part](args.model, args.budget, tmp)
        finally:
            remove(tmp)
        (HERE / "results" / f"{args.model}-{part}.json").write_text(json.dumps(result, indent=1, default=str))
        print(json.dumps(result, indent=1, default=str)[:6000])
