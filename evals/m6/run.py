"""Build plan M6: one use case on one public dataset per round (rounds.py, README).

    python run.py --round 1 --check                    # the data is in place; its IDs and answers compute
    python run.py --round 1 --tag t --sample 200       # a trial on a sample, into store fs_m6_r1_t
    python run.py --round 1 --tag a [--model sonnet]   # a run on everything the round gives

Each stage is an agent in `claude -p`, set up as in evals/m4: one skill in .claude/skills, the
factstore MCP server only, a sandboxed shell, and a read-only copy of the round's sources. The stages
are the round's, in order, on one store that starts with core and the round's packages:

- catalogue: the catalogue skill over the sources;
- ingest: the round's ingestion skill over the sources;
- rerun: the first of those again, a fresh agent with the same prompt;
- ontology: the ontology skill, proposing names and recording them once the person confirms;
- questions: a fresh agent with only the MCP server answers the round's questions.

The full record quotes the data: the transcripts, the agents' files and the answers given go to
data/runs/r<round>-<model>-<tag>/, which git ignores. results/r<round>-<model>-<tag>.json holds the
measures only: counts, scores and costs, nothing from the data.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[1:1] = [str(HERE.parent / "m4"), str(HERE.parent / "m5")]
_spec = importlib.util.spec_from_file_location("m4run", HERE.parent / "m4" / "run.py")
m4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m4)

import checks  # noqa: E402
import measure  # noqa: E402  (evals/m5/measure.py)
import score  # noqa: E402  (evals/m4/score.py)
from factstore import admin, packages  # noqa: E402
from rounds import ROUNDS, Round  # noqa: E402

ADMIN, REPO = m4.ADMIN, m4.REPO
DATA = REPO / "data"
RESULTS = HERE / "results"

QUESTIONS_PROMPT = """\
You have the company's fact store. Answer these questions.

{questions}

End your reply with the answers as JSON in a ```json block: {{"answers": [{{"question": 1, \
"rows": [["value", ...], ...]}}, ...]}}. One array per row, values in the order each question \
lists its columns, copied exactly from the query results. A question the store can't answer gets \
"rows": null; say why in your reply."""

AGENTS = {"catalogue": "catalogue agent", "ingest": "ingestion agent", "ontology": "ontology agent",
          "questions": "question agent"}


def sample(source: Path, dest: Path, n: int | None) -> None:
    """Copy a source folder; with `n`, only the first n rows of each CSV and the first n other files."""
    if n is None:
        shutil.copytree(source, dest)
        return
    dest.mkdir(parents=True)
    others = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() != ".csv")
    for path in sorted(source.rglob("*.csv")) + others[:n]:
        target = dest / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".csv":
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as f, open(target, "w") as out:
                for i, line in enumerate(f):
                    if i > n:
                        break
                    out.write(line)
        else:
            shutil.copy2(path, target)


class Run:
    """One run of a round on store fs_m6_r<round>_<tag>. Each stage saves the record so far, so a
    later stage can be run again on the store the earlier ones left (`--stages`)."""

    def __init__(self, rnd: Round, model: str, budget: float, root: Path, tag: str, n: int | None, fresh: bool):
        self.round, self.model, self.budget, self.root, self.n = rnd, model, budget, root, n
        self.store = f"fs_m6_r{rnd.number}_{tag}"
        self.name = f"r{rnd.number}-{model}-{tag}"
        self.private = DATA / "runs" / self.name
        self.private.mkdir(parents=True, exist_ok=True)
        self.record_path = self.private / "record.json"
        if fresh:
            admin.drop_store(ADMIN, self.store)
            admin.init_store(ADMIN, self.store)
            admin.install(ADMIN, self.store, [packages.load(REPO / p) for p in rnd.packages])
        self.record = {"round": rnd.number, "use_case": rnd.use_case, "model": model, "store": self.store,
                       "sample": n, "stages": {}}
        if not fresh and self.record_path.exists():
            self.record = json.loads(self.record_path.read_text())
        self.exports = root / "exports"
        if n and rnd.sampler:
            rnd.sampler(DATA / rnd.dataset, self.exports, n)
        else:
            for source in rnd.sources:
                sample(DATA / rnd.dataset / source, self.exports / source, n)
        # The files the agents were given. Rescoring against other files, after a sampler or the
        # data changed, would score the store against what it never saw.
        given = fingerprint(self.exports)
        if self.record.setdefault("exports_sha256", given) != given:
            sys.exit(f"{self.name}: the sources differ from those its agents were given (a sampler or the "
                     "data changed since); score it on those, or run it again")
        self.actors = {}
        for stage in rnd.stages:  # every agent the round has, so measures() counts what each registered
            self.actor(AGENTS.get(stage) or AGENTS[rnd.stages[0]])

    def actor(self, name: str) -> admin.Credential:
        if name not in self.actors:
            with m4.owner(self.store) as conn:
                found = score.rows(conn, 'select e from current."fs/name" where v = %s', name)
            self.actors[name] = (admin.create_credential(ADMIN, self.store, found[0][0]) if found
                                 else admin.create_actor(ADMIN, self.store, name))
        return self.actors[name]

    def run(self, stages: list[str]) -> dict:
        for name in stages:
            self.record["stages"][name] = getattr(self, name)()
            self.save()
        self.record["measures"] = self.measures()
        self.save()
        return self.record

    def save(self) -> None:
        self.record_path.write_text(json.dumps(self.record, indent=1, default=str))
        if "measures" in self.record:
            RESULTS.mkdir(exist_ok=True)
            (RESULTS / f"{self.name}.json").write_text(json.dumps(
                {k: self.record[k] for k in ("round", "use_case", "model", "sample", "measures")}, indent=1))

    def stage(self, name: str, agent: str, prompt: str, work: Path, tools: list[str], full_text: bool = False,
              **kw) -> dict:
        with m4.owner(self.store) as conn:
            before = score.snapshot(conn)
        out = m4.run_claude(prompt, work, self.actor(agent).dsn, self.model,
                            self.private / f"{name}.stream.jsonl", tools, self.budget, **kw)
        with m4.owner(self.store) as conn:
            result = {**m4.summary(out), "session_id": out.get("session_id"), "wrote": score.since(conn, before)}
        if full_text:
            result["final"] = out.get("result") or ""
        dest = self.private / f"{name}-files"
        shutil.rmtree(dest, ignore_errors=True)
        result["files_skipped"] = m4.keep_files(work, dest)
        return result

    def store_checks(self) -> dict:
        with m4.owner(self.store) as conn:
            return {"ids": checks.id_counts(conn, self.exports, self.round.ids), "bare": checks.bare(conn),
                    "personal": checks.personal(conn, self.exports, self.round.personal),
                    "documents": checks.documents(conn), "size": checks.size(conn)}

    def catalogue(self, name: str = "catalogue") -> dict:
        work = m4.workdir(self.root / name, [REPO / "factstore-skills" / "catalogue"], self.exports,
                          list(self.round.sources))
        r = self.stage(name, AGENTS["catalogue"], self.round.prompts["catalogue"], work, m4.FILE_TOOLS)
        return {**r, **self.store_checks()}

    def ingest(self, name: str = "ingest") -> dict:
        skills = [REPO / self.round.ingest_skill] if self.round.ingest_skill else []  # none: the tools' descriptions only
        work = m4.workdir(self.root / name, skills, self.exports, list(self.round.sources))
        r = self.stage(name, AGENTS["ingest"], self.round.prompts["ingest"], work, m4.FILE_TOOLS)
        with m4.owner(self.store) as conn:
            r["evidence"] = score.evidence(conn, self.actor(AGENTS["ingest"]).actor)
        return {**r, **self.store_checks()}

    def rerun(self) -> dict:
        """The round's first stage again: a fresh agent, the same prompt, the same actor."""
        return self.catalogue("rerun") if "catalogue" in self.round.stages else self.ingest("rerun")

    def ontology(self) -> dict:
        work = self.root / "ontology" / "work"
        shutil.copytree(REPO / "factstore-skills" / "ontology", work / ".claude" / "skills" / "factstore-ontology")
        first = self.stage("ontology-propose", AGENTS["ontology"], m4.ONTOLOGY_PROMPT, work, ["Skill"],
                           keep_session=True)
        second = self.stage("ontology-record", AGENTS["ontology"], m4.ONTOLOGY_CONFIRM, work, ["Skill"],
                            resume=first["session_id"])
        with m4.owner(self.store) as conn:
            names = [r[0] for r in score.rows(conn, 'select v from current."shape/name" order by v')] \
                if score.has_attr(conn, "shape/name") else []
        return {"propose": first, "record": second, "shapes": names}

    def questions(self) -> dict:
        if not self.round.questions:
            return {"skipped": "the round's questions are written when it starts"}
        text = "\n".join(f"{q['id']}. {q['text']} Columns: {', '.join(q['columns'])}." for q in self.round.questions)
        work = self.root / "questions" / "work"
        work.mkdir(parents=True)
        r = self.stage("questions", AGENTS["questions"], QUESTIONS_PROMPT.format(questions=text), work, [],
                       full_text=True)
        block = re.findall(r"```json\s*(\{.*?\})\s*```", r["final"], re.S)
        given = {a["question"]: a["rows"] for a in json.loads(block[-1])["answers"]} if block else {}
        expected = self.round.answers(self.exports)
        same = self.round.judge or measure.same
        r["answers"] = {q: {"right": same(given.get(q) or [], expected[q]),  # no rows, or null, for []
                            "given": given.get(q), "expected": expected[q]} for q in expected}
        return r

    def rescore(self) -> dict:
        """Score the store again, after a scorer changes, running no agent."""
        last = next(k for k in ("rerun", "catalogue", "ingest") if k in self.record["stages"])
        self.record["stages"][last].update(self.store_checks())
        if answers := self.record["stages"].get("questions", {}).get("answers"):  # the given answers, judged again
            expected, same = self.round.answers(self.exports), self.round.judge or measure.same
            for q, a in answers.items():
                a["right"] = same(a["given"] or [], expected[int(q)])
        self.record["measures"] = self.measures()
        self.save()
        return self.record

    def measures(self) -> dict:
        """Counts, scores and costs only: what results/ commits."""
        s = self.record["stages"]
        with m4.owner(self.store) as conn:
            registered = measure.registered_by(conn, {n: a.actor for n, a in self.actors.items()})
            truth = self.round.truth(conn, self.exports) if self.round.truth else None
        last = next((s[k] for k in ("rerun", "catalogue", "ingest") if k in s), {})
        out = {
            "registered_beyond_packages": registered,
            "rerun": {k: s["rerun"]["wrote"][k] for k in ("new_entities", "transactions", "facts")} if "rerun" in s else None,
            **{k: last.get(k) for k in ("ids", "bare", "personal", "documents", "size")},
            "evidence": {k: v for k, v in last.get("evidence", {}).items() if k != "without_evidence"} or None,
            "shapes": len(s["ontology"]["shapes"]) if "ontology" in s else None,
            "truth": truth,
            "cost_usd": round(sum(v.get("cost_usd") or 0 for v in walk(s)), 2),
            "wall_minutes": round(sum(v.get("wall_seconds") or 0 for v in walk(s)) / 60),
        }
        if s.get("questions", {}).get("answers"):
            a = s["questions"]["answers"]
            out["questions"] = {"right": sum(v["right"] for v in a.values()), "asked": len(a),
                                "wrong": [q for q, v in a.items() if not v["right"]]}
        return out


def fingerprint(folder: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(folder)).encode() + b"\0")
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
    return h.hexdigest()


def walk(stages: dict):
    for v in stages.values():
        if "turns" in v:
            yield v
        else:
            yield from (x for x in v.values() if isinstance(x, dict) and "turns" in x)


def check(rnd: Round) -> dict:
    """Before a round: its data is in place, and its IDs, personal columns and answers compute."""
    root = DATA / rnd.dataset
    missing = [s for s in rnd.sources if not (root / s).is_dir()]
    if missing:
        return {"missing": [str(root / s) for s in missing], "origin": rnd.origin}
    out = {"files": {s: sorted(str(p.relative_to(root)) for p in (root / s).rglob("*") if p.is_file())[:50]
                     for s in rnd.sources},
           "ids": {i.kind: len(checks.column_values(root, i.file, i.column)) for i in rnd.ids},
           "personal_values": sum(len(checks.column_values(root, p, c)) for p, c in rnd.personal),
           "questions": len(rnd.questions)}
    if rnd.answers:
        out["answers_rows"] = {q: len(rs) for q, rs in rnd.answers(root).items()}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True, choices=sorted(ROUNDS))
    ap.add_argument("--check", action="store_true", help="check the round's data and answers; run no agent")
    ap.add_argument("--tag", help="names the run's store, fs_m6_r<round>_<tag>, and its results")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--budget", type=float, default=15.0, help="USD cap per agent session")
    ap.add_argument("--sample", type=int, help="the round's sample of N (rounds.py), or the first N rows of "
                                               "each CSV and the first N other files")
    ap.add_argument("--stages", help="comma-separated, from the round's stages; a list not starting with "
                                     "the round's first stage continues on the store the earlier ones left")
    ap.add_argument("--rescore", action="store_true", help="score the run's store again, running no agent")
    args = ap.parse_args()
    rnd = ROUNDS[args.round]
    if args.check or not args.tag:
        print(json.dumps(check(rnd), indent=1))
        sys.exit()
    if args.rescore:
        tmp = Path(tempfile.mkdtemp(prefix=f"m6-r{rnd.number}-{args.tag}-"))
        try:
            record = json.loads((DATA / "runs" / f"r{rnd.number}-{args.model}-{args.tag}" / "record.json").read_text())
            result = Run(rnd, args.model, args.budget, tmp, args.tag, record["sample"], fresh=False).rescore()
        finally:
            m4.remove(tmp)
        print(json.dumps(result["measures"].get("truth"), indent=1, default=str))
        sys.exit()
    stages = args.stages.split(",") if args.stages else list(rnd.stages)
    if unknown := [s for s in stages if s not in rnd.stages]:
        sys.exit(f"round {rnd.number} has no stage {', '.join(unknown)}; its stages are {', '.join(rnd.stages)}")
    tmp = Path(tempfile.mkdtemp(prefix=f"m6-r{rnd.number}-{args.tag}-"))
    try:
        result = Run(rnd, args.model, args.budget, tmp, args.tag, args.sample, fresh=stages[0] == rnd.stages[0]).run(stages)
    finally:
        m4.remove(tmp)
    print(json.dumps(result["measures"], indent=1, default=str))
