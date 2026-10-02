"""Scoring the slice (build plan M5) against the fixture's ground truth and the direct loader's world.

M4's scorers (evals/m4/score.py) cover the crosswalk, duplicates, personal data and the documents'
statements. This adds what only the slice needs: shapes against the operator's list in a store whose
sales-side names the catalogue chose, and the ten questions answered by an agent on the store the
skills built.
"""

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
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


def unfilled(conn, package: Path) -> list[str]:
    """The package's attributes that hold no value in this store."""
    idents = [a["ident"] for a in json.loads((package / "manifest.json").read_text())["attributes"]]
    return [i for i in idents if rows(conn, f'select count(*) from current."{i}"')[0][0] == 0]


# --- the ten questions -------------------------------------------------------------------------

# The slice's store holds no transaction from before it was built, so question 3 asks for a date
# instead of the loader's mark: what an operator would ask.
SLICE_TEXT = {3: "As of 1 July 2026: which shipments had status departed or arrived, and what was each one's "
                 "ETA as recorded at that point? Give the booking number, status and ETA."}

# Questions whose data no export holds, so the slice can't answer them however well the skills run.
NO_SOURCE = {
    3: "The store's time is when a fact was written. The slice wrote the documents' history in October, so no "
       "transaction holds what was known on 1 July.",
    10: "No source counts stock at a factory or on the water. The direct loader writes those counts from the "
        "simulation; the documents give production status and shipment lines, not counts.",
}


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


def store_questions(conn, reference) -> dict:
    """The reference SQL on the slice's store against the direct loader's world, for the questions
    whose attribute names the packages fix (1, 2, 4–7) and question 8 when the catalogue chose the
    loader's names. A question whose SQL names an attribute this store lacks is reported as such."""
    ids = [1, 2, 4, 5, 6, 7] + ([8] if all(has_attr(conn, a) for a in ("order/customer", "shopify/customer_id")) else [])
    return score.questions(conn, reference, ids)


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
