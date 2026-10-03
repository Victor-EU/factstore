"""Scoring the M4 skills against the fixture's ground truth (export's truth/ directory).

Each scorer reads a store through its owner's connection, with `current` on the search path, so
"po/etd" is the current-state view and history."po/etd" the log.
"""

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from itertools import combinations
from pathlib import Path

# Crosswalk systems: truth column, store attribute, and whether the attribute is an identity.
SYSTEMS = [
    ("upc", "sku/upc"),
    ("shopify_variant_id", "shopify/variant_id"),
    ("amazon_seller_sku", "amazon/seller_sku"),
    ("asin", "amazon/asin"),
    ("fnsku", "amazon/fnsku"),
    ("tpl_item_code", "tpl/item_code"),
    ("factory_code", "factory/item_code"),
    ("hs_code", "sku/hs_code"),
    ("supplier", "sku/supplier"),
]


def rows(conn, sql, *args):
    return conn.execute(sql, args).fetchall()


def has_attr(conn, ident) -> bool:
    return rows(conn, "select 1 from attr where ident = %s", ident) != []


def survivors(conn) -> dict[int, int]:
    """Each entity that is core/same_as another, mapped to the end of its chain."""
    same = dict(rows(conn, 'select e, v from current."core/same_as"'))
    root = {}
    for e in same:
        seen, x = set(), e
        while x in same and x not in seen:
            seen.add(x)
            x = same[x]
        root[e] = x
    return root


# --- catalogue -------------------------------------------------------------------------------


def crosswalk(conn, truth: Path) -> dict:
    """Precision and recall of every system's ID for each SKU, as links from the ID to our SKU
    code. A link counts when the ID sits on the hub whose sku/code is the true SKU (following
    core/same_as to the surviving hub). An Amazon ID reaches the hub through its listing (ecom-ops
    0.4.0): the seller SKU and FNSKU sit on the listing, which points at the SKU, and the ASIN is a
    record the listing points at. In a store from before, they sit on the hub itself. Factory codes count when the part after the supplier
    prefix matches, since the agent chooses supplier codes; `factory_prefix_exact` says how many
    used the fixture's own code."""
    xw = list(csv.DictReader(open(truth / "crosswalk.csv")))
    vendors = {r["supplier_code"]: r["legal_name"] for r in csv.DictReader(open(truth / "vendors.csv"))}
    root = survivors(conn)
    code_of = {}  # hub entity -> sku code
    for e, code in rows(conn, 'select e, v from current."sku/code"'):
        code_of[e] = code
    def hub_code(e):
        r = root.get(e, e)
        return code_of.get(r, code_of.get(e))
    listing_sku = dict(rows(conn, 'select e, v from current."listing/sku"')) if has_attr(conn, "listing/sku") else {}
    asin_listings = defaultdict(list)
    if has_attr(conn, "listing/asin"):
        for listing, asin in rows(conn, 'select e, v from current."listing/asin"'):
            asin_listings[asin].append(listing)
    def hubs_of(e):
        """The hubs an ID's entity stands for: itself, or through a listing."""
        if e in listing_sku:
            return [listing_sku[e]]
        if e in asin_listings:
            return [listing_sku[x] for x in asin_listings[e] if x in listing_sku]
        return [e]
    truth_pairs = {}
    for r in xw:
        for col, attr in SYSTEMS:
            if r[col]:
                truth_pairs.setdefault(attr, {})[r["sku"]] = r[col]
    suppliers = {}
    if has_attr(conn, "supplier/code"):
        suppliers.update({e: ("code", v) for e, v in rows(conn, 'select e, v from current."supplier/code"')})
    names = dict(rows(conn, 'select e, v from current."supplier/name"')) if has_attr(conn, "supplier/name") else {}
    out, total_correct, total_stored, total_truth = {}, 0, 0, 0
    prefix_exact = 0
    for col, attr in SYSTEMS:
        want = truth_pairs.get(attr, {})
        stored = rows(conn, f'select e, v::text from current."{attr}"') if has_attr(conn, attr) else []
        on_hubs = [(hub_code(h), v, e) for e, v in stored for h in hubs_of(e) if hub_code(h) is not None]
        correct = set()
        for code, v, e in on_hubs:
            t = want.get(code)
            if t is None:
                continue
            if attr == "factory/item_code":
                ok = v.split(":", 1)[-1] == t
                if ok and v == f"{next(r['supplier'] for r in xw if r['sku'] == code)}:{t}":
                    prefix_exact += 1
            elif attr == "sku/supplier":
                v = int(v)
                kind = suppliers.get(v)
                ok = (kind is not None and kind[1] == t) or names.get(v) == vendors.get(t)
            else:
                ok = v == t
            if ok:
                correct.add(code)
        n_stored = len(on_hubs)
        out[col] = {"truth": len(want), "stored": n_stored, "correct": len(correct),
                    "precision": round(len(correct) / n_stored, 3) if n_stored else None,
                    "recall": round(len(correct) / len(want), 3) if want else None}
        total_correct += len(correct)
        total_stored += n_stored
        total_truth += len(want)
    hubs = Counter(hub_code(e) for e in code_of)
    return {"systems": out,
            "precision": round(total_correct / total_stored, 3) if total_stored else None,
            "recall": round(total_correct / total_truth, 3),
            "skus_in_truth": len(xw),
            "hubs": len({root.get(e, e) for e in code_of}),
            "hubs_with_true_code": sum(1 for r in xw if r["sku"] in hubs),
            "factory_prefix_exact": prefix_exact}


def duplicates(conn, truth: Path, exports: Path) -> dict:
    """Pairwise precision and recall of duplicate Shopify accounts, as clusters joined by core/same_as.
    Recall counts only pairs whose accounts both appear in the exports: orders cover the year to
    date, so an account that last ordered in 2025 can't be matched from them."""
    if not has_attr(conn, "shopify/customer_id"):
        return {"marked": 0}
    present = set()
    with open(exports / "shopify" / "orders.jsonl") as f:
        for line in f:
            c = json.loads(line).get("customer")
            if c:
                present.add(c["id"].rsplit("/", 1)[1])
    ids = dict(rows(conn, 'select e, v from current."shopify/customer_id"'))
    root = survivors(conn)
    clusters = defaultdict(set)
    for e, cid in ids.items():
        clusters[root.get(e, e)].add(cid)
    predicted = {frozenset(p) for c in clusters.values() for p in combinations(sorted(c), 2)}
    edges = defaultdict(set)
    for r in csv.DictReader(open(truth / "duplicate_customers.csv")):
        edges[r["customer_id"]].add(r["same_person_as"])
        edges[r["same_person_as"]].add(r["customer_id"])
    seen, truth_pairs = set(), set()
    for start in edges:
        if start in seen:
            continue
        group, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x not in group:
                group.add(x)
                stack.extend(edges[x])
        seen |= group
        truth_pairs |= {frozenset(p) for p in combinations(sorted(group), 2)}
    visible = {p for p in truth_pairs if p <= present}
    hit = predicted & truth_pairs
    return {"truth_pairs": len(truth_pairs), "visible_pairs": len(visible), "marked_pairs": len(predicted),
            "correct": len(hit),
            "precision": round(len(hit) / len(predicted), 3) if predicted else None,
            "recall": round(len(hit & visible) / len(visible), 3) if visible else None}


def personal_data(conn, exports: Path) -> dict:
    """String values in the store that are a Shopify customer's email, name, phone or street address."""
    pii = set()
    with open(exports / "shopify" / "orders.jsonl") as f:
        for line in f:
            o = json.loads(line)
            c, a = o.get("customer") or {}, o.get("shippingAddress") or {}
            for v in (c.get("email"), c.get("phone"), o.get("email"), a.get("name"), a.get("address1"),
                      " ".join(filter(None, (c.get("firstName"), c.get("lastName"))))):
                if v and len(v) > 4:
                    pii.add(v.lower())
    found = [v for (v,) in rows(conn, "select distinct v_string from fact where v_string is not null")
             if v.lower() in pii]
    emails = [v for (v,) in rows(conn, "select distinct v_string from fact where v_string like '%%@%%'")
              if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]+", v)]
    return {"personal_values": len(found), "examples": found[:5], "values_with_at_sign": emails[:10]}


def index_counts(conn) -> dict:
    """How many records of each kind the catalogue indexed, by identity attribute."""
    out = {}
    for (ident,) in rows(conn, "select ident from attr where uniq = 'identity' and ident not like 'fs/%%' order by 1"):
        out[ident] = rows(conn, f'select count(*) from current."{ident}"')[0][0]
    return {k: v for k, v in out.items() if v}


def snapshot(conn) -> dict:
    return {"max_e": rows(conn, "select coalesce(max(e), 0) from fact")[0][0],
            "max_tx": rows(conn, "select max(id) from tx")[0][0],
            "attributes": rows(conn, "select count(*) from attr")[0][0]}


def since(conn, before: dict) -> dict:
    """What a run wrote after `before`: new entities (not transactions, attributes or actors), new
    attributes, transactions and facts."""
    new_entities = rows(conn, """
        select count(distinct e) from fact
        where e > %s and e not in (select id from tx) and e not in (select id from attr)
        and e not in (select e from cur where a = 10)""", before["max_e"])[0][0]
    txs, facts = rows(conn, "select count(distinct tx), count(*) from fact where tx > %s", before["max_tx"])[0]
    return {"new_entities": new_entities,
            "new_attributes": [r[0] for r in rows(conn, "select ident from attr order by id offset %s",
                                                  before["attributes"])],
            "transactions": txs, "facts": facts}


def registered_beyond(conn, actor: int) -> list[str]:
    return [r[0] for r in rows(conn, """
        select a.ident from attr a join fact f on f.e = a.id and f.a = 1 join tx on tx.id = f.tx
        where tx.actor = %s order by a.id""", actor)]


# --- ingestion -------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(conn, actor: int) -> dict:
    """Of the transactions the agent wrote, how many carry core/evidence pointing at a document, and
    core/confidence. Registrations (transactions asserting fs/ident) are left out."""
    txs = [r[0] for r in rows(conn, """
        select id from tx where actor = %s
        and id not in (select tx from fact where a = 1)""", actor)]
    with_evidence = {r[0] for r in rows(conn, """
        select ev.e from current."core/evidence" ev join current."document/hash" h on h.e = ev.v""")}
    with_confidence = {r[0] for r in rows(conn, 'select e from current."core/confidence"')}
    return {"transactions": len(txs), "with_evidence": sum(t in with_evidence for t in txs),
            "with_confidence": sum(t in with_confidence for t in txs),
            "without_evidence": [t for t in txs if t not in with_evidence][:10]}


def documents(conn, folder: Path) -> dict:
    """The folder's files recorded as documents under their true hash, and other document entities."""
    hashes = {sha256(p): p.name for p in folder.iterdir() if p.is_file()}
    stored = dict(rows(conn, 'select v, e from current."document/hash"'))
    urls = dict(rows(conn, 'select e, v from current."document/url"'))
    matched = {h: stored[h] for h in hashes if h in stored}
    url_ok = sum(1 for h, e in matched.items() if urls.get(e, "").endswith(hashes[h]))
    return {"files": len(hashes), "recorded": len(matched), "url_names_file": url_ok,
            "other_documents": len(stored) - len(matched)}


def pdf_statements(conn, export_dir: Path) -> dict:
    """Each statement the truth says a PDF makes, checked in the store: is the value on the right
    entity (anywhere in its history), and was it written in a transaction whose evidence is that
    PDF?"""
    doc_of = dict(rows(conn, 'select v, e from current."document/hash"'))
    by_doc = defaultdict(set)  # document entity -> transactions it backs
    for tx, doc in rows(conn, 'select e, v from current."core/evidence"'):
        by_doc[doc].add(tx)
    has = {a: has_attr(conn, a) for a in ("po/number", "po/pi_number", "po/etd", "po_line/unit_price", "qc/result",
                                          "shipment_line/quantity", "shipment/hbl", "shipment/container_no",
                                          "factory/item_code", "qc/po", "shipment_line/po_line")}
    po = dict(rows(conn, 'select v, e from current."po/number"'))
    # PO lines by (PO entity, factory code), via po_line/sku -> factory/item_code.
    lines = defaultdict(set)
    for line, po_e, code in rows(conn, """
            select l.e, p.v, f.v from current."core/part_of" p join current."po_line/sku" l using (e)
            join current."factory/item_code" f on f.e = l.v"""):
        lines[(po_e, code.split(":", 1)[-1])].add(line)
    qc_by_po = defaultdict(set)
    for e, v in rows(conn, 'select e, v from current."qc/po"'):
        qc_by_po[v].add(e)
    shipment_by_ref = {}
    for attr in ("shipment/hbl", "shipment/container_no"):
        if has_attr(conn, attr):
            for e, v in rows(conn, f'select e, v from history."{attr}"'):
                shipment_by_ref[v] = e
    ship_lines = defaultdict(set)  # (shipment, PO line) -> shipment lines
    for sl, ship, pl in rows(conn, """
            select p.e, p.v, l.v from current."core/part_of" p join current."shipment_line/po_line" l using (e)"""):
        ship_lines[(ship, pl)].add(sl)

    def history(attr, entities):
        if not entities or not has.get(attr, has_attr(conn, attr)):
            return []
        return rows(conn, f"""select v::text, tx from history."{attr}" where op = 'assert' and e = any(%s)""",
                    list(entities))

    tally = defaultdict(Counter)
    misses = defaultdict(list)
    for line in open(export_dir / "truth" / "statements.jsonl"):
        s = json.loads(line)
        if s["source"] != "pdf":
            continue
        field, _, code = s["field"].partition(":")
        path = export_dir / s["ref"]
        doc = doc_of.get(sha256(path))
        txs = by_doc.get(doc, set())
        po_e = po.get(s["subject"])
        if field in ("pi_number", "etd"):
            entities, attr = {po_e} - {None}, f"po/{field}"
        elif field == "unit_price":
            entities, attr = lines.get((po_e, code), set()), "po_line/unit_price"
        elif field == "qc_result":
            report = path.stem
            entities, attr = qc_by_po.get(po_e, set()), "qc/result"
            named = {e for e, v in rows(conn, 'select e, v from current."qc/report_no"') if v == report}
            entities = entities & named if named else entities
        elif field == "shipped":
            ship = shipment_by_ref.get(path.stem.rsplit("_", 1)[-1])
            entities = set().union(*(ship_lines.get((ship, pl), set()) for pl in lines.get((po_e, code), set())))
            attr = "shipment_line/quantity"
        else:
            continue
        values = history(attr, entities)
        want = _norm(s["value"])
        on_entity = [tx for v, tx in values if _norm(v) == want]
        tally[field]["truth"] += 1
        tally[field]["on_entity"] += bool(on_entity)
        tally[field]["with_evidence"] += any(tx in txs for tx in on_entity)
        if not any(tx in txs for tx in on_entity) and len(misses[field]) < 5:
            misses[field].append({**s, "found": [v for v, _ in values]})
    total = sum(t["truth"] for t in tally.values())
    return {"fields": {k: dict(v) for k, v in tally.items()},
            "truth": total,
            "on_entity": sum(t["on_entity"] for t in tally.values()),
            "with_evidence": sum(t["with_evidence"] for t in tally.values()),
            "recall": round(sum(t["with_evidence"] for t in tally.values()) / total, 3) if total else None,
            "misses": dict(misses)}


def message_statements(conn, export_dir: Path) -> dict:
    """Each statement the truth says a chat message or an email makes, checked like pdf_statements.
    A message's document is found by its url (wechat/<file>#<n>, or mid:<Message-ID>). ETDs and ETAs
    in emails are dates, written as instants: one counts if its date matches in China, New York or
    UTC time. Fields the package has no attribute for are counted, not checked."""
    doc_by_url = {v: e for e, v in rows(conn, 'select e, v from current."document/url"')}
    by_doc = defaultdict(set)
    for tx, doc in rows(conn, 'select e, v from current."core/evidence"'):
        by_doc[doc].add(tx)
    po = dict(rows(conn, 'select v, e from current."po/number"'))
    shipment = dict(rows(conn, 'select v, e from current."shipment/booking_no"'))
    entry = dict(rows(conn, 'select v, e from current."customs/entry_no"')) if has_attr(conn, "customs/entry_no") else {}

    def history(attr, e, cast="v::text"):
        if e is None or not has_attr(conn, attr):
            return []
        return rows(conn, f"""select {cast}, tx from history."{attr}" where op = 'assert' and e = %s""", e)

    def dates(attr, e):
        return history(attr, e, "to_char(v at time zone 'Asia/Shanghai', 'YYYY-MM-DD') || ' ' || "
                                "to_char(v at time zone 'America/New_York', 'YYYY-MM-DD') || ' ' || "
                                "to_char(v at time zone 'UTC', 'YYYY-MM-DD')")

    tally, misses, unscored = defaultdict(Counter), defaultdict(list), Counter()
    for line in open(export_dir / "truth" / "statements.jsonl"):
        s = json.loads(line)
        if s["source"] == "pdf":
            continue
        field = s["field"].split(":")[0]
        url = s["ref"] if s["source"] == "wechat" else "mid:" + s["ref"].split("<", 1)[1].rstrip(">")
        txs = by_doc.get(doc_by_url.get(url), set())
        key = f'{s["source"]} {field}'
        if s["source"] == "wechat" and field == "etd":
            found = history("po/etd", po.get(s["subject"]))
            ok = [tx for v, tx in found if v == s["value"]]
        elif s["source"] == "email" and field in ("etd", "eta"):
            found = dates(f"shipment/{field}", shipment.get(s["subject"]))
            ok = [tx for v, tx in found if s["value"] in v.split()]
        elif field == "container_no":
            found = history("shipment/container_no", shipment.get(s["subject"]))
            ok = [tx for v, tx in found if v == s["value"]]
        elif field == "duty_total":  # duty and fees, which may come in two transactions
            e = entry.get(s["subject"])
            duty, fees = history("customs/duty", e), history("customs/fees", e)
            found = [(str(Decimal(d) + Decimal(f)), (dt, ft)) for d, dt in duty for f, ft in fees]
            ok = [pair for v, pair in found if Decimal(v) == Decimal(s["value"])]
        else:
            unscored[key] += 1
            continue
        tally[key]["truth"] += 1
        tally[key]["on_entity"] += bool(ok)
        tally[key]["with_evidence"] += any(set(t if isinstance(t, tuple) else (t,)) <= txs for t in ok)
        if not any(set(t if isinstance(t, tuple) else (t,)) <= txs for t in ok) and len(misses[key]) < 5:
            misses[key].append({**s, "found": [v for v, _ in found]})
    total = sum(t["truth"] for t in tally.values())
    return {"fields": {k: dict(v) for k, v in sorted(tally.items())},
            "truth": total,
            "on_entity": sum(t["on_entity"] for t in tally.values()),
            "with_evidence": sum(t["with_evidence"] for t in tally.values()),
            "recall": round(sum(t["with_evidence"] for t in tally.values()) / total, 3) if total else None,
            "no_attribute_in_package": dict(unscored),
            "misses": dict(misses)}


# Questions whose data the supplier documents, chats and emails carry. 3 reads as of a loader
# mark, 8 needs the sales side, 9 names the loader, and 10 needs stock counts.
DOCUMENT_QUESTIONS = [1, 2, 4, 5, 6, 7]


def questions(conn, reference, ids=DOCUMENT_QUESTIONS) -> dict:
    """The ten questions' reference SQL on this store and on `reference`, the same world written
    by the direct loader. Instants are compared by their date in New York: documents give dates,
    and a date without a time is written as midnight at the port."""
    from factstore_fixture.questions import REFERENCE_SQL
    out = {}
    for q in ids:
        sql = REFERENCE_SQL[q][0]
        got, want = (Counter(tuple(_cell(v) for v in r) for r in c.execute(sql).fetchall()) for c in (conn, reference))
        out[q] = {"agree": got == want, "rows": sum(want.values()),
                  "missing": [list(r) for r in (want - got)][:5], "extra": [list(r) for r in (got - want)][:5]}
    return {"agree": sum(v["agree"] for v in out.values()), "asked": len(ids), "questions": out}


def _cell(v):
    if hasattr(v, "astimezone"):
        from zoneinfo import ZoneInfo
        return v.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    return _norm(v) if isinstance(v, (str, Decimal)) else str(v)


def _norm(v: str) -> str:
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return str(Decimal(s).normalize())
    return s


# --- ontology --------------------------------------------------------------------------------


def shapes(conn, truth: Path) -> dict:
    """Recorded shapes against the fixture's. Each true shape is named by the identity attribute its
    "always" list starts with; its signature is what every entity holding that attribute carries in
    this store (the data, which is what the skill reads), and shapes.json's "always" list is a second
    reference written before the data. Each true shape is matched to the recorded shape whose
    signature is closest (Jaccard); 1.0 means the same attributes."""
    want = json.loads((truth / "shapes.json").read_text())
    got = defaultdict(set)
    names = {}
    if has_attr(conn, "shape/name"):
        names = dict(rows(conn, 'select e, v from current."shape/name"'))
        for e, a in rows(conn, """select s.e, i.v from current."shape/signature" s join current."fs/ident" i on i.e = s.v"""):
            got[e].add(a)

    def closest(always):
        return max(((len(always & sig) / len(always | sig), e) for e, sig in got.items()), default=(0, None))

    out = {}
    for name, spec in want.items():
        data = data_signature(conn, spec["always"][0])
        jaccard, e = closest(data)
        out[name] = {"recorded_as": names.get(e), "jaccard": round(jaccard, 2),
                     "missing": sorted(data - got.get(e, set())), "extra": sorted(got.get(e, set()) - data),
                     "jaccard_to_shapes_json": round(closest(set(spec["always"]))[0], 2)}
    matched = {v["recorded_as"] for v in out.values() if v["jaccard"] == 1}
    return {"truth": len(want), "recorded": len(names),
            "exact": sum(v["jaccard"] == 1 for v in out.values()),
            "close": sum(v["jaccard"] >= 0.8 for v in out.values()),
            "exact_to_shapes_json": sum(v["jaccard_to_shapes_json"] == 1 for v in out.values()),
            "unmatched_recorded": sorted(n for e, n in names.items() if n not in matched),
            "shapes": out}


def data_signature(conn, ident: str) -> set[str]:
    """The attributes every entity holding `ident` carries, outside fs/."""
    n, attrs = 0, []
    if has_attr(conn, ident):
        n = rows(conn, f'select count(*) from current."{ident}"')[0][0]
        attrs = rows(conn, """
            select a.ident, count(distinct c.e) from cur c join attr a on a.id = c.a
            where c.e in (select c2.e from cur c2 join attr k on k.id = c2.a where k.ident = %s)
            and a.ident not like 'fs/%%' group by 1""", ident)
    return {a for a, k in attrs if k == n}
