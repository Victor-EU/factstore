"""Scoring the slice (build plan M5) against the fixture's ground truth and the direct loader's world.

M4's scorers (evals/m4/score.py) cover the crosswalk, duplicates, personal data and the documents'
statements. This adds what only the slice needs: shapes against the operator's list in a store whose
sales-side names the catalogue chose, and the ten questions answered by an agent on the store the
skills built.
"""

import csv
import json
import mailbox
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import score
from score import has_attr, rows

NEW_YORK = ZoneInfo("America/New_York")

# --- shapes against the operator's list ----------------------------------------------------------


def _key(v) -> str:
    """An ID compared across stores, without Shopify's gid://shopify/Order/ prefix."""
    s = str(v)
    return s.rsplit("/", 1)[-1] if s.startswith("gid://") else s


def identity_values(conn) -> dict[str, set[str]]:
    return {ident: {_key(v) for (v,) in rows(conn, f'select v::text from current."{ident}"')}
            for (ident,) in rows(conn, "select ident from attr where uniq = 'identity' and ident not like 'fs/%%'")}


def operator_shapes(conn, reference, truth: Path) -> dict:
    """Each kind of thing on the operator's list (truth/shapes.json), found in the slice's store by
    its IDs rather than its attribute names, since the catalogue names the sales side itself.

    The kind's IDs are the values of its identity attribute in the direct loader's world. The slice
    attribute holding most of them is the kind's identity here. A line's key is a format the agent
    chooses, so a line kind no attribute's values match is found through its whole instead: the
    identity most entities carry that are core/part_of the whole's kind. The kind's signature is
    what every entity holding its identity carries, with or without bare fragments
    (kind_signatures). Each kind is then matched to the recorded shape with the closest signature
    (Jaccard; 1.0 is the same attributes)."""
    want = json.loads((truth / "shapes.json").read_text())
    here = identity_values(conn)
    names, recorded = {}, defaultdict(set)
    if has_attr(conn, "shape/name"):
        names = dict(rows(conn, 'select e, v from current."shape/name"'))
        for e, a in rows(conn, 'select s.e, i.v from current."shape/signature" s join current."fs/ident" i on i.e = s.v'):
            recorded[e].add(a)

    def by_values(ident):
        ids = {_key(v) for (v,) in rows(reference, f'select v::text from current."{ident}"')}
        n, found = max(((len(ids & vs), a) for a, vs in here.items()), default=(0, None))
        return (found if ids and n >= 0.5 * len(ids) else None), len(ids), n

    def by_whole(ident):
        """The identity of the slice's parts of whatever the world's parts of `ident` are part of."""
        whole = rows(reference, f"""
            select a.ident from current."{ident}" k join current."core/part_of" p on p.e = k.e
            join cur c on c.e = p.v join attr a on a.id = c.a where a.uniq = 'identity'
            group by 1 order by count(*) desc limit 1""")
        if not whole or not has_attr(conn, "core/part_of"):
            return None
        slice_whole = by_values(whole[0][0])[0]
        if slice_whole is None:
            return None
        part = rows(conn, f"""
            select a.ident, count(*) from current."core/part_of" p join current."{slice_whole}" w on w.e = p.v
            join cur c on c.e = p.e join attr a on a.id = c.a
            where a.uniq = 'identity' and a.ident not like 'fs/%%' group by 1 order by 2 desc limit 1""")
        return part[0][0] if part else None

    out = {}
    for kind, spec in want.items():
        ident = spec["always"][0]
        found, n_world, n_store = by_values(ident)
        if found is None and "core/part_of" in spec["always"]:
            found = by_whole(ident)
            n_store = rows(conn, f'select count(*) from current."{found}"')[0][0] if found else n_store
        if found is None:
            out[kind] = {"in_store": False, "identity": None, "ids_in_world": n_world,
                         "ids_in_store": n_store, "recorded_as": None, "jaccard": None}
            continue
        jaccard, e, signature = max(((len(sig & got) / len(sig | got), e, sig)
                                     for sig in kind_signatures(conn, found) for e, got in recorded.items()),
                                    default=(0, None, set()), key=lambda t: t[0])
        out[kind] = {"in_store": True, "identity": found, "ids_in_world": n_world, "ids_in_store": n_store,
                     "recorded_as": names.get(e) if jaccard else None, "jaccard": round(jaccard, 2),
                     "missing": sorted(signature - recorded.get(e, set())),
                     "extra": sorted(recorded.get(e, set()) - signature)}
    present = [k for k, v in out.items() if v["in_store"]]
    matched = {v["recorded_as"] for v in out.values() if v["jaccard"] == 1}
    return {"operator_list": len(want), "in_store": len(present),
            "exact": sum(out[k]["jaccard"] == 1 for k in present),
            "close": sum(out[k]["jaccard"] >= 0.8 for k in present),
            "recorded": len(names),
            "recorded_beyond_list": sorted(n for n in names.values() if n not in matched),
            "kinds": out}


def kind_signatures(conn, ident: str) -> list[set[str]]:
    """What every entity holding `ident` carries, outside fs/: once over all of them, and once
    leaving out those that hold nothing but the ID. A bare entity may be a real record that only an
    ID describes (a warehouse receipt with no PO reference), or a fragment: a join key whose value
    names no real record, such as five POs numbered "PO-1 / PO-2" in one run, which the ontology
    skill reports as a gap. The scorer doesn't decide which, so a shape may match either reading."""
    out = [score.data_signature(conn, ident)]
    members = f"""
        select k.e from current."{ident}" k where exists (
          select 1 from cur c join attr a on a.id = c.a
          where c.e = k.e and a.ident <> %s and a.ident not like 'fs/%%')"""
    n = rows(conn, f"select count(*) from ({members}) m", ident)[0][0]
    if n:
        attrs = rows(conn, f"""
            select a.ident, count(distinct c.e) from cur c join attr a on a.id = c.a
            where c.e in ({members}) and a.ident not like 'fs/%%' group by 1""", ident)
        out.append({a for a, k in attrs if k == n})
    return out


def unfilled(conn, *packages: Path) -> dict[str, list[str]]:
    """Each package's attributes that hold no value in this store."""
    out = {}
    for package in packages:
        manifest = json.loads((package / "manifest.json").read_text())
        out[manifest["name"]] = [a["ident"] for a in manifest["attributes"]
                                 if rows(conn, f'select count(*) from current."{a["ident"]}"')[0][0] == 0]
    return out


def issue_dates(conn, export_dir: Path) -> dict:
    """The documents ingestion reads, by kind: how many the store records, how many carry
    document/issued_at, and how many carry the right one. A PDF's is the date the truth gives it, in
    China; a chat message's is its timestamp in the export (New York time, as the prompt says); an
    email's is its Date header."""
    china = ZoneInfo("Asia/Shanghai")
    pdf = {}
    for line in open(export_dir / "truth" / "statements.jsonl"):
        s = json.loads(line)
        if s["source"] == "pdf":
            pdf[s["ref"]] = datetime.fromisoformat(s["at"]).astimezone(china).date()
    chats = {}
    for f in sorted((export_dir / "wechat").glob("*.txt")):
        for n, msg in enumerate(re.split(r"\n(?=\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )", f.read_text())[1:], 1):
            chats[f"wechat/{f.name}#{n}"] = datetime.strptime(msg[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK)
    emails = {}
    for f in (export_dir / "email").glob("*.mbox"):
        for m in mailbox.mbox(str(f)):
            emails["mid:" + m["Message-ID"].strip("<>")] = parsedate_to_datetime(m["Date"])
    dated = dict(rows(conn, 'select u.v, d.v from current."document/url" u left join current."document/issued_at" d '
                            'using (e)')) if has_attr(conn, "document/issued_at") else \
        {u: None for (u,) in rows(conn, 'select v from current."document/url"')}
    out = {}
    for kind, truth, right in (("pdf", pdf, lambda got, want: got.astimezone(china).date() == want),
                               ("chat message", chats, lambda got, want: got == want),
                               ("email", emails, lambda got, want: got == want)):
        here = {u: d for u, d in dated.items() if u in truth}
        out[kind] = {"in_export": len(truth), "recorded": len(here),
                     "dated": sum(d is not None for d in here.values()),
                     "right": sum(d is not None and right(d, truth[u]) for u, d in here.items()),
                     "wrong": [[u, str(d), str(truth[u])] for u, d in here.items()
                               if d is not None and not right(d, truth[u])][:5]}
    return out


# --- the ten questions -------------------------------------------------------------------------

# The slice's store holds no transaction from before it was built, so question 3 asks for a date
# instead of the loader's mark: what an operator would ask.
SLICE_TEXT = {3: "As of 1 July 2026: which shipments had status departed or arrived, and what was each one's "
                 "ETA as recorded at that point? Give the booking number, status and ETA."}

# Question 3 on a backfilled store: the values whose evidence was issued before 1 July (New York),
# the latest issued winning (design Part II, business time). Slices a to d had no issue dates.
SLICE_SQL = {3: """
with known as (
  select ev.e as tx, max(d.v) as issued
  from "core/evidence" ev join "document/issued_at" d on d.e = ev.v
  group by 1),
status as (
  select distinct on (h.e) h.e, h.v
  from history."shipment/status" h join known k on k.tx = h.tx
  where h.op = 'assert' and k.issued < '2026-07-01T00:00:00-04:00'
  order by h.e, k.issued desc, h.tx desc),
eta as (
  select distinct on (h.e) h.e, h.v
  from history."shipment/eta" h join known k on k.tx = h.tx
  where h.op = 'assert' and k.issued < '2026-07-01T00:00:00-04:00'
  order by h.e, k.issued desc, h.tx desc)
select b.v, s.v, eta.v
from status s
join "shipment/booking_no" b on b.e = s.e
left join eta on eta.e = s.e
where s.v in ('departed', 'arrived')"""}

# Questions whose data no export holds, so the slice can't answer them however well the skills run.
# Slices a to d had two: question 3 (no business time) and question 10 (stock counts). The decision
# after M5 gave documents an issue date and made question 10 a derivation, so none are left.
NO_SOURCE: dict[int, str] = {}


def cell(v, exact_time=False) -> str:
    """A value as compared between an answer and a reference. An instant compares by its date in New
    York (documents give dates), or to the second in UTC when `exact_time`."""
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") if exact_time else \
            v.astimezone(NEW_YORK).date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        try:
            return str(Decimal(s).normalize())
        except InvalidOperation:
            return s
    if re.fullmatch(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d.*", s):
        try:
            return cell(datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1)), exact_time)
        except ValueError:
            return s
    return s


def same(given, expected, exact_time=False) -> bool:
    norm = lambda rs: Counter(tuple(cell(v, exact_time) for v in r) for r in rs)
    return norm(given) == norm(expected)


def q8_from_exports(export_dir: Path, customer: str = "8995877069469") -> list[tuple]:
    """Accounts in the customer's duplicate cluster that the exports show, and their orders there."""
    edges = defaultdict(set)
    for r in csv.DictReader(open(export_dir / "truth" / "duplicate_customers.csv")):
        edges[r["customer_id"]].add(r["same_person_as"])
        edges[r["same_person_as"]].add(r["customer_id"])
    group, stack = set(), [customer]
    while stack:
        x = stack.pop()
        if x not in group:
            group.add(x)
            stack.extend(edges[x])
    orders = Counter()
    with open(export_dir / "shopify" / "orders.jsonl") as f:
        for line in f:
            c = json.loads(line).get("customer")
            if c and (cid := c["id"].rsplit("/", 1)[1]) in group:
                orders[cid] += 1
    return [(len(orders), sum(orders.values()))]


def q9_from_store(conn, export_dir: Path) -> dict:
    """Who wrote PO-2026-0023's current ETD in this store, and whether that transaction's evidence is
    the document the truth says last stated it."""
    from factstore_fixture.questions import REFERENCE_SQL
    found = rows(conn, REFERENCE_SQL[9][0])
    evidence = []
    if found:
        evidence = [r[0] for r in rows(conn, """
            select u.v from current."core/evidence" ev join current."document/url" u on u.e = ev.v
            where ev.e = %s""", found[0][1])]
    stated = [json.loads(line) for line in open(export_dir / "truth" / "statements.jsonl")]
    stated = [s for s in stated if s["subject"] == "PO-2026-0023" and s["field"] == "etd"]
    last = stated[-1] if stated else None
    return {"rows": [tuple(r) for r in found], "evidence": evidence, "last_statement": last}


def score_answers(given: dict, expected: dict) -> dict:
    """`given` and `expected` map question ids to rows; questions in NO_SOURCE are reported, not scored."""
    out = {}
    for q in range(1, 11):
        rows_given = given.get(q, given.get(str(q)))
        if q in NO_SOURCE:
            out[q] = {"scored": False, "why": NO_SOURCE[q], "given": rows_given, "world": expected.get(q)}
            continue
        ok = rows_given is not None and same(rows_given, expected[q], exact_time=(q == 9))
        out[q] = {"scored": True, "right": ok, "given": rows_given, "expected": expected[q]}
    scored = [q for q, v in out.items() if v["scored"]]
    return {"right": sum(out[q]["right"] for q in scored), "answerable": len(scored),
            "wrong": [q for q in scored if not out[q]["right"]], "questions": out}


def store_questions(conn, reference, world: dict | None = None) -> dict:
    """The reference SQL on the slice's store against the direct loader's world, for the questions
    whose attribute names the packages fix (1, 2, 4–7, 10) and question 8 when the store has the
    loader's names. Question 3 runs SLICE_SQL against the world's answer, when the store has issue
    dates."""
    ids = [1, 2, 4, 5, 6, 7] + ([8] if all(has_attr(conn, a) for a in ("order/customer", "shopify/customer_id")) else [])
    ids += [10]
    out = score.questions(conn, reference, ids)
    if world is not None and has_attr(conn, "document/issued_at"):
        got = Counter(tuple(cell(v) for v in r) for r in rows(conn, SLICE_SQL[3]))
        want = Counter(tuple(cell(v) for v in r) for r in world["answers"]["3"])
        out["questions"][3] = {"agree": got == want, "rows": sum(want.values()),
                               "missing": [list(r) for r in (want - got)][:5], "extra": [list(r) for r in (got - want)][:5]}
        out["agree"] += got == want
        out["asked"] += 1
    return out


# --- the store as a whole ----------------------------------------------------------------------


def registered_by(conn, actors: dict[str, int]) -> dict:
    """Attributes each agent registered, and all of them together."""
    by = {name: score.registered_beyond(conn, actor) for name, actor in actors.items()}
    return {"total": sum(len(v) for v in by.values()), "by_agent": by}


def entity_counts(conn) -> dict:
    """Entities of the supply-side kinds, and ones holding nothing but an identifier."""
    out = {}
    for ident in ("po/number", "po_line/key", "shipment/booking_no", "shipment/hbl", "shipment_line/key",
                  "qc/report_no", "customs/entry_no", "document/hash"):
        if not has_attr(conn, ident):
            continue
        total = rows(conn, f'select count(*) from current."{ident}"')[0][0]
        bare = rows(conn, f"""
            select count(*) from current."{ident}" k
            where not exists (select 1 from cur c join attr a on a.id = c.a
                              where c.e = k.e and a.ident <> %s and a.ident not like 'fs/%%')""", ident)[0][0]
        out[ident] = {"entities": total, "bare": bare}
    # Shipments known under one identifier only and under another only: one shipment split in two.
    if has_attr(conn, "shipment/hbl") and has_attr(conn, "shipment/booking_no"):
        out["shipments_without_booking"] = rows(conn, """
            select count(*) from current."shipment/hbl" h
            where h.e not in (select e from current."shipment/booking_no")""")[0][0]
        out["shipments_without_hbl"] = rows(conn, """
            select count(*) from current."shipment/booking_no" b
            where b.e not in (select e from current."shipment/hbl")""")[0][0]
    return out
