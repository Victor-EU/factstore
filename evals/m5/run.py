"""Build plan M5 on the fixture: the slice run, end to end, on one store.

    python run.py --reference                 # once: the direct loader's world, and its answers
    python run.py --tag a [--model sonnet]    # one slice, into store fs_m5_<tag>

No partner data has arrived, so the slice runs on the fixture's exports, as the build plan's risk
table says. Each stage is an agent in `claude -p`, set up as in evals/m4 (one skill in
.claude/skills, the factstore MCP server only, a sandboxed shell, a read-only copy of the sources
it reads), all on one store, in the order a company would run them:

1. catalogue: the catalogue skill over every export;
2. ingestion: the ingestion skill over the supplier PDFs, the WeChat chats and the ops inbox;
3. re-run: the catalogue skill again, a fresh agent with the same prompt;
4. ontology: the ontology skill, proposing names and recording them once the person confirms;
5. questions: a fresh agent with only the MCP server answers the ten questions.

Results go to results/<model>-<tag>.json, with every transcript and the agents' own scripts.
"""

import argparse
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(1, str(HERE.parent / "m4"))
_spec = importlib.util.spec_from_file_location("m4run", HERE.parent / "m4" / "run.py")
m4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m4)

import measure  # noqa: E402
import score  # noqa: E402  (evals/m4/score.py)
from factstore import admin, connect, packages  # noqa: E402
from factstore_fixture.exports import export  # noqa: E402
from factstore_fixture.load import load, new_store  # noqa: E402
from factstore_fixture.questions import JULY_1_MARK, QUESTIONS, World, answers  # noqa: E402
from factstore_fixture.simulate import Simulation  # noqa: E402

ADMIN, REPO = m4.ADMIN, m4.REPO
RESULTS = HERE / "results"
REFERENCE = "fs_m5_reference"
ECOM_OPS, ECOM_INDEX = REPO / "packages" / "ecom-ops", REPO / "packages" / "ecom-index"


def empty_store(store: str) -> None:
    """An empty store with the packages a company would install: core (by init), ecom-ops,
    ecom-index (after M5's decision) and factstore-skills."""
    admin.drop_store(ADMIN, store)
    admin.init_store(ADMIN, store)
    admin.install(ADMIN, store, [packages.load(ECOM_OPS), packages.load(ECOM_INDEX),
                                 packages.load(REPO / "factstore-skills")])

def allow_personal(store: str, attributes) -> None:
    """The business's owner allows these attributes to hold personal data, with a credential of
    their own, as packages/README.md says. No slice but one testing it allows any."""
    if attributes:
        owner = connect(admin.create_actor(ADMIN, store, "owner").dsn)
        owner.transact([{"e": ["fs/ident", a], "a": "core/personal", "v": True} for a in attributes])


INGEST_PROMPT = """\
Today is 1 October 2026. Our systems are already catalogued in the fact store. Ingest the supplier \
documents in ./exports/supplier_docs, our WeChat chats with suppliers in ./exports/wechat and the \
ops inbox in ./exports/email into the fact store with the ecom-ops-ingest-documents skill. The chat \
exports come from our ops manager's phone, so their timestamps are New York time."""

QUESTIONS_PROMPT = """\
Today is 1 October 2026. You have the company's fact store. Answer these questions from the \
operations manager.

{questions}

End your reply with the answers as JSON in a ```json block: {{"answers": [{{"question": 1, \
"rows": [["value", ...], ...]}}, ...]}}. One array per row, values in the order each question \
lists its columns, copied exactly from the query results. A question the store can't answer gets \
"rows": null; say why in your reply."""


def build_reference() -> dict:
    """The default world written by the direct loader, with the 1 July mark, and its ten answers."""
    admin.drop_store(ADMIN, REFERENCE)
    loader = new_store(ADMIN, REFERENCE)
    with connect(loader.dsn) as s:
        stats = load(s, Simulation(7), batch=1000, marks=[JULY_1_MARK])
        july_1 = stats.marks[JULY_1_MARK]
        world = answers(World(s.conn, july_1))
    out = {"store": REFERENCE, "july_1": july_1, "answers": {q: [list(r) for r in rs] for q, rs in world.items()}}
    (RESULTS / "world.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def stage(name: str, tag: str, model: str, budget: float, store: str, actor, prompt: str, work: Path,
          tools: list[str], full_text: bool = False, **kw) -> dict:
    with m4.owner(store) as conn:
        before = score.snapshot(conn)
    out = m4.run_claude(prompt, work, actor.dsn, model, RESULTS / f"{model}-{tag}-{name}.stream.jsonl", tools,
                        budget, **kw)
    with m4.owner(store) as conn:
        result = {**m4.summary(out), "session_id": out.get("session_id"), "wrote": score.since(conn, before)}
    if full_text:
        result["final"] = out.get("result") or ""
    dest = RESULTS / f"{model}-{tag}-{name}-files"
    shutil.rmtree(dest, ignore_errors=True)
    result["files_skipped"] = m4.keep_files(work, dest)
    if not any(dest.rglob("*")):
        shutil.rmtree(dest, ignore_errors=True)
    return result


STAGES = ["catalogue", "ingest", "rerun", "ontology", "questions"]
AGENTS = {"catalogue": "catalogue agent", "ingest": "ingestion agent", "rerun": "catalogue agent",
          "ontology": "ontology agent", "questions": "question agent"}


class Slice:
    """One slice on store fs_m5_<tag>. Each stage saves the results so far, so a later stage can be
    run again on the store the earlier ones left (`--stages`)."""

    def __init__(self, model: str, budget: float, root: Path, tag: str, fresh: bool, allow: list[str] = ()):
        self.model, self.budget, self.root, self.tag = model, budget, root, tag
        self.store = f"fs_m5_{tag}"
        self.out = RESULTS / f"{model}-{tag}.json"
        if fresh:
            empty_store(self.store)
            allow_personal(self.store, allow)
        self.result = {"model": model, "store": self.store, "stages": {}, "allowed": list(allow)}
        if not fresh and self.out.exists():
            self.result = json.loads(self.out.read_text())
        self.export_dir = root / "export"
        export(str(self.export_dir))
        self.sources = sorted(p.name for p in self.export_dir.iterdir() if p.is_dir() and p.name != "truth")
        self.actors = {name: self.actor(name) for name in sorted(set(AGENTS.values()))}

    def actor(self, name: str) -> admin.Credential:
        """The store's actor called `name`, with a new credential, or a new actor."""
        with m4.owner(self.store) as conn:
            found = score.rows(conn, 'select e from current."fs/name" where v = %s', name)
        if found:
            return admin.create_credential(ADMIN, self.store, found[0][0])
        return admin.create_actor(ADMIN, self.store, name)

    def run(self, stages: list[str]) -> dict:
        for name in stages:
            self.result["stages"][name] = getattr(self, name)()
            self.save()
        if all(name in self.result["stages"] for name in STAGES):
            self.result["measures"] = self.measures()
            self.save()
        return self.result

    def save(self) -> None:
        self.out.write_text(json.dumps(self.result, indent=1, default=str))

    def stage(self, name: str, prompt: str, work: Path, tools: list[str], agent: str, **kw) -> dict:
        return stage(name, self.tag, self.model, self.budget, self.store, self.actors[agent], prompt, work, tools, **kw)

    def catalogue_measures(self) -> dict:
        truth = self.export_dir / "truth"
        with m4.owner(self.store) as conn:
            return {"crosswalk": score.crosswalk(conn, truth),
                    "duplicates": score.duplicates(conn, truth, self.export_dir),
                    "personal_data": score.personal_data(conn, self.export_dir),
                    "indexed": score.index_counts(conn)}

    def catalogue(self, name: str = "catalogue") -> dict:
        work = m4.workdir(self.root / name, [REPO / "factstore-skills" / "catalogue"], self.export_dir, self.sources)
        return {**self.stage(name, m4.CATALOGUE_PROMPT, work, m4.FILE_TOOLS, AGENTS[name]), **self.catalogue_measures()}

    def ingest(self) -> dict:
        """The PDFs, chats and email, on what the catalogue left."""
        work = m4.workdir(self.root / "ingest", [REPO / "packages" / "ecom-ops" / "ingest-documents"],
                          self.export_dir, ["supplier_docs", "wechat", "email"])
        r = self.stage("ingest", INGEST_PROMPT, work, m4.FILE_TOOLS, AGENTS["ingest"])
        world = json.loads((RESULTS / "world.json").read_text())
        with m4.owner(self.store) as conn, m4.owner(REFERENCE) as reference:
            r.update(evidence=score.evidence(conn, self.actors[AGENTS["ingest"]].actor),
                     documents=score.documents(conn, self.export_dir / "supplier_docs"),
                     issue_dates=measure.issue_dates(conn, self.export_dir),
                     pdf_statements=score.pdf_statements(conn, self.export_dir),
                     message_statements=score.message_statements(conn, self.export_dir),
                     store_questions=measure.store_questions(conn, reference, world),
                     entities=measure.entity_counts(conn),
                     unfilled=measure.unfilled(conn, ECOM_OPS, ECOM_INDEX),
                     contacts=measure.contacts(conn),
                     in_production=measure.in_production(conn, reference))
        return r

    def rescore(self) -> dict:
        """Score the stores again, after a scorer changes, without running any agent."""
        s = self.result["stages"]
        with m4.owner(self.store) as conn, m4.owner(REFERENCE) as reference:
            s["ingest"].update(entities=measure.entity_counts(conn),
                               unfilled=measure.unfilled(conn, ECOM_OPS, ECOM_INDEX),
                               contacts=measure.contacts(conn),
                               in_production=measure.in_production(conn, reference))
            s["ontology"]["shapes"] = measure.operator_shapes(conn, reference, self.export_dir / "truth")
        self.result["measures"] = self.measures()
        self.save()
        return self.result

    def rerun(self) -> dict:
        """The catalogue again: a fresh agent, the same prompt, the same actor."""
        return self.catalogue("rerun")

    def ontology(self) -> dict:
        """Propose names, then record what the person confirms."""
        work = self.root / "ontology" / "work"
        shutil.copytree(REPO / "factstore-skills" / "ontology", work / ".claude" / "skills" / "factstore-ontology")
        first = self.stage("ontology-propose", m4.ONTOLOGY_PROMPT, work, ["Skill"], AGENTS["ontology"],
                           keep_session=True)
        with m4.owner(self.store) as conn:
            first["shape_names_before_confirming"] = rows_or_zero(conn, "shape/name")
        second = self.stage("ontology-record", m4.ONTOLOGY_CONFIRM, work, ["Skill"], AGENTS["ontology"],
                            resume=first["session_id"])
        with m4.owner(self.store) as conn, m4.owner(REFERENCE) as reference:
            return {"propose": first, "record": second,
                    "shapes": measure.operator_shapes(conn, reference, self.export_dir / "truth")}

    def questions(self) -> dict:
        """The ten questions, by a fresh agent holding only the MCP server."""
        text = "\n".join(f"{q['id']}. {measure.SLICE_TEXT.get(q['id'], q['text'])} Columns: {', '.join(q['columns'])}."
                         for q in QUESTIONS)
        work = self.root / "questions" / "work"
        work.mkdir(parents=True)
        r = self.stage("questions", QUESTIONS_PROMPT.format(questions=text), work, [], AGENTS["questions"],
                       full_text=True)
        block = re.findall(r"```json\s*(\{.*?\})\s*```", r["final"], re.S)
        given = {a["question"]: a["rows"] for a in json.loads(block[-1])["answers"]} if block else {}
        world = json.loads((RESULTS / "world.json").read_text())
        expected = {int(q): rs for q, rs in world["answers"].items()}
        expected[8] = measure.q8_from_exports(self.export_dir)
        with m4.owner(self.store) as conn:
            q9 = measure.q9_from_store(conn, self.export_dir)
        expected[9] = q9["rows"]
        return {**r, "answers": measure.score_answers(given, expected), "q9_provenance": q9}

    def measures(self) -> dict:
        """The five measures of design §18, and what the WeChat export yielded (open question 5)."""
        with m4.owner(self.store) as conn:
            registered = measure.registered_by(conn, {n: a.actor for n, a in self.actors.items()})
        s = self.result["stages"]
        return {
            "crosswalk": {k: s["rerun"]["crosswalk"][k] for k in ("precision", "recall")},
            "shapes": {k: s["ontology"]["shapes"][k] for k in ("operator_list", "in_store", "exact", "close", "recorded")},
            "registered_beyond_packages": registered,
            "rerun": {k: s["rerun"]["wrote"][k] for k in ("new_entities", "transactions", "facts")},
            "unfilled_package_attributes": s["ingest"].get("unfilled"),
            "issue_dates": {k: {x: v[x] for x in ("recorded", "dated", "right")}
                            for k, v in s["ingest"].get("issue_dates", {}).items()},
            "store_questions": {k: s["ingest"]["store_questions"][k] for k in ("agree", "asked")},
            "questions": {k: s["questions"]["answers"][k] for k in ("right", "answerable", "wrong")},
            "wechat": {k: v for k, v in s["ingest"]["message_statements"]["fields"].items() if k.startswith("wechat")},
            "cost_usd": round(sum(v.get("cost_usd") or 0 for v in walk(s)), 2),
            "wall_minutes": round(sum(v.get("wall_seconds") or 0 for v in walk(s)) / 60),
        }


def walk(stages: dict):
    for v in stages.values():
        if "turns" in v:
            yield v
        else:
            yield from (x for x in v.values() if isinstance(x, dict) and "turns" in x)


def rows_or_zero(conn, ident: str) -> int:
    return score.rows(conn, f'select count(*) from current."{ident}"')[0][0] if score.has_attr(conn, ident) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", action="store_true", help="build the direct loader's world and its answers")
    ap.add_argument("--tag", help="names the slice's store, fs_m5_<tag>, and its results")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--budget", type=float, default=15.0, help="USD cap per agent session")
    ap.add_argument("--stages", help=f"comma-separated, from {','.join(STAGES)}; a list not starting with "
                                     "catalogue continues on the store the earlier stages left")
    ap.add_argument("--rescore", action="store_true", help="score the slice's store again, running no agent")
    ap.add_argument("--allow", action="append", default=[], help="an attribute the business's owner allows to "
                                                                  "hold personal data, before any agent runs")
    args = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    if args.reference:
        print(json.dumps(build_reference(), indent=1, default=str)[:3000])
    if args.tag and args.rescore:
        tmp = Path(tempfile.mkdtemp(prefix=f"m5-{args.tag}-"))
        try:
            print(json.dumps(Slice(args.model, args.budget, tmp, args.tag, fresh=False).rescore()["measures"],
                             indent=1, default=str))
        finally:
            m4.remove(tmp)
    elif args.tag:
        stages = args.stages.split(",") if args.stages else STAGES
        tmp = Path(tempfile.mkdtemp(prefix=f"m5-{args.tag}-"))
        try:
            result = Slice(args.model, args.budget, tmp, args.tag, fresh=stages[0] == "catalogue",
                           allow=args.allow).run(stages)
        finally:
            m4.remove(tmp)
        print(json.dumps(result.get("measures", {k: v.get("cost_usd") for k, v in result["stages"].items()}),
                         indent=1, default=str))
