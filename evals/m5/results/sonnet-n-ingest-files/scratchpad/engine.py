import sys, json, re, collections
from decimal import Decimal
from parse import *

DRY = "--run" not in sys.argv
REPORT = collections.defaultdict(list)   # section -> list of strings
STATS = collections.Counter()

STATUS_PO = ["draft", "sent", "confirmed", "in_production", "ready", "shipped", "received"]
STATUS_SH = ["booked", "departed", "arrived", "delivered"]

# ------------------------------------------------------------------ reference data from the store
import factstore
ITEMS = {}   # factory/item_code -> (sku code, hs)
for r in factstore.query('select c.v, h.v from "factory/item_code" c join "sku/hs_code" h using(e)').rows:
    ITEMS[r[0]] = r[1]
SUPPLIERS = {r[0] for r in factstore.query('select v from "supplier/code"').rows}

PDFS = pdf_docs()
CHATS = chat_docs()
EMAILS = email_docs()
PI_BY_NO = {d["pi_no"]: d for d in PDFS if d["kind"] == "pi"}

KIND_RANK = {"pi": 0, "qc": 1, "cipl": 2, "chat": 3, "email": 4}
ALL = sorted(PDFS + CHATS + EMAILS, key=lambda d: (d["issued"].astimezone(ZoneInfo("UTC")), KIND_RANK[d["kind"]], d.get("n", 0), d.get("name", "")))

# ------------------------------------------------------------------ state
cur = {}          # (entkey, attr) -> value string
cur_t = {}        # (entkey, attr) -> issued of the document behind it
PO = {}           # po number -> dict(supplier, pi_no, lines{n:{item,qty,key,sku}}, status, etd, placed)
SHIPS = []        # list of shipment dicts
TXS = []          # planned transactions

def po_state(p):
    return PO.setdefault(p, {"supplier": None, "pi": None, "lines": [], "status": None, "placed": None, "shipped_etd": None})

def rank(lst, s):
    return lst.index(s) if s in lst else -1

class Tx:
    """facts for one document at one confidence"""
    def __init__(self, doc, conf):
        self.doc, self.conf, self.facts, self.n_data = doc, conf, [], 0

    def a(self, ekey, elook, attr, val, vkey=None):
        """assert unless already current; drop when the document is older than what is held"""
        k = (ekey, attr)
        sval = json.dumps(val) if vkey is None else vkey
        if cur.get(k) == sval:
            return False
        if k in cur_t and cur_t[k] > self.doc["issued"]:
            REPORT["stale"].append(f"{self.doc['url']}: {ekey} {attr} older than held value; not written")
            return False
        cur[k] = sval
        cur_t[k] = self.doc["issued"]
        self.facts.append({"e": elook, "a": attr, "v": val})
        self.n_data += 1
        return True

def flush(tx):
    if not tx.n_data:
        return
    d = tx.doc
    h = d["hash"]
    pre = [
        {"e": ["document/hash", h], "a": "document/url", "v": d["url"]},
        {"e": ["document/hash", h], "a": "document/issued_at", "v": iso(d["issued"])},
        {"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", h]},
        {"e": "tmp:tx", "a": "core/confidence", "v": str(tx.conf)},
    ]
    TXS.append({"doc": d["url"], "conf": str(tx.conf), "facts": pre + tx.facts})
    STATS["tx"] += 1
    STATS["tx_conf_" + str(tx.conf)] += 1

class DocTx:
    def __init__(self, doc):
        self.doc = doc
        self.by = {}
    def at(self, conf):
        if conf not in self.by:
            self.by[conf] = Tx(self.doc, conf)
        return self.by[conf]
    def done(self):
        for c in sorted(self.by, reverse=True):
            flush(self.by[c])

def pol(po): return {"e": ["po/number", po]}
def Po(po): return ["po/number", po]
def Sup(code): return ["supplier/code", code]

def set_po_status(t, po, new):
    p = po_state(po)
    if rank(STATUS_PO, new) > rank(STATUS_PO, p["status"]):
        if t.a("po:" + po, Po(po), "po/status", new):
            p["status"] = new
            return True
    return False

# ------------------------------------------------------------------ shipments
def ship_by_hbl(h): return next((s for s in SHIPS if s["hbl"] == h), None)
def ship_by_so(so): return next((s for s in SHIPS if s["so"] == so), None)
def ship_by_cont(c): return [s for s in SHIPS if s["container"] == c]

def sref(s, t=None):
    # an identifier asserted in this very transaction is not yet resolvable: keep using the booking number
    if s["hbl"] and not (t is not None and s.get("hbl_tx") is t):
        return ["shipment/hbl", s["hbl"]]
    return ["shipment/booking_no", s["so"]]
def skey(s): return "ship:%d" % s["id"]

def new_ship(**kw):
    s = {"id": len(SHIPS) + 1, "so": None, "hbl": None, "container": None, "vessel": None, "origin": None, "dest": None,
         "pos": set(), "lines": {}, "status": None, "departed_docs": set(), "delivered": False, "mode": None}
    s.update(kw)
    SHIPS.append(s)
    return s

def norm_po(tok):
    """booking emails name POs loosely: PO#2025-0146, po 0147, PO144, PO8 ..."""
    m = re.search(r"(\d{4})\D?(\d{4})$", tok)
    if m:
        return f"PO-{m.group(1)}-{m.group(2)}"
    n = re.search(r"(\d+)$", tok).group(1).zfill(4)
    c = [p for p in ALL_POS if p.endswith("-" + n)]
    if len(c) != 1:
        REPORT["unresolved"].append(f"booking PO reference {tok!r} matches {c}")
        return None
    return c[0]

ALL_POS = sorted({d["po"] for d in PDFS if d["kind"] in ("pi", "cipl", "qc")} |
                 {m for c in CHATS for m in re.findall(r"PO-\d{4}-\d{4}", c["text"])})

def sku_of(po, item):
    code = po_state(po)["supplier"]
    key = f"{code}:{item}"
    return key if key in ITEMS else None

def find_line(po, item):
    key = sku_of(po, item)
    for ln in po_state(po)["lines"]:
        if ln["sku"] == key:
            return ln
    return None

def add_ship_line(t, s, po, item, qty, ctns, pdoc):
    ln = find_line(po, item)
    if ln is None:
        REPORT["unresolved"].append(f"{t.doc['url']}: no PO line for {po} item {item}")
        return None
    key = f"{s['hbl']}/{ln['key']}"
    ek = "sline:" + key
    E = ["shipment_line/key", key]
    t.a(ek, E, "core/part_of", sref(s, t))
    t.a(ek, E, "shipment_line/po_line", ["po_line/key", ln["key"]])
    prev = s["lines"].get(ln["key"])
    if prev and prev["qty"] != qty:
        REPORT["discrepancy"].append(f"{t.doc['url']}: {key} quantity {qty} differs from earlier {prev['qty']} ({prev['src']})")
    if prev and ctns is not None and prev["ctns"] is not None and prev["ctns"] != ctns:
        REPORT["discrepancy"].append(f"{t.doc['url']}: {key} cartons {ctns} differs from earlier {prev['ctns']} ({prev['src']})")
    t.a(ek, E, "shipment_line/quantity", str(qty))
    if ctns is not None:
        t.a(ek, E, "shipment_line/cartons", str(ctns))
    s["lines"][ln["key"]] = {"qty": qty, "ctns": ctns, "src": t.doc["url"], "po": po}
    s["pos"].add(po)
    return ln

def ship_covers(po):
    """PO shipped: every shipment carrying it has lines for it, or line totals reach every ordered quantity"""
    p = po_state(po)
    if not p["lines"]:
        return False
    tot = collections.Counter()
    for s in SHIPS:
        for k, v in s["lines"].items():
            if v["po"] == po:
                tot[k] += v["qty"]
    if all(tot[ln["key"]] >= ln["qty"] for ln in p["lines"]):
        return True
    carriers = [s for s in SHIPS if po in s["pos"]]
    return bool(carriers) and all(any(v["po"] == po for v in s["lines"].values()) for s in carriers)

def find_ship_for_docs(hbl, vessel, pos):
    s = ship_by_hbl(hbl)
    if s:
        return s
    cands = [x for x in SHIPS if x["hbl"] is None and x["vessel"] == vessel and (x["pos"] & set(pos))]
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        REPORT["unresolved"].append(f"HBL {hbl}: several bookings on {vessel} carry {sorted(pos)}: {[c['so'] for c in cands]}")
        return None
    return None

# ------------------------------------------------------------------ PDF handlers
def do_pi(d):
    dt = DocTx(d)
    t = dt.at(1)
    po = d["po"]
    code = re.search(r"sales@(\w+)\.example", d["text"]).group(1).upper()
    if code not in SUPPLIERS:
        REPORT["unresolved"].append(f"{d['url']}: supplier code {code} not in store"); return
    p = po_state(po)
    p["supplier"] = code
    p["pi"] = d["pi_no"]
    E = Po(po); k = "po:" + po
    t.a(k, E, "po/pi_number", d["pi_no"])
    t.a(k, E, "po/supplier", Sup(code))
    t.a(k, E, "po/etd", d["etd"])
    t.a(k, E, "core/currency", d["currency"])
    # supplier
    sk, SE = "sup:" + code, Sup(code)
    t.a(sk, SE, "supplier/name", d["beneficiary"])
    t.a(sk, SE, "supplier/name_cn", d["name_cn"])
    t.a(sk, SE, "supplier/address", d["address"])
    t.a(sk, SE, "supplier/incoterm", d["incoterm"])
    t.a(sk, SE, "supplier/payment_terms", d["payment"])
    t.a(sk, SE, "supplier/currency", d["currency"])
    portname = d["incoterm"].split()[-1]
    t.a(sk, SE, "supplier/port", PORT_NAME[portname])
    # lines
    for i, r in enumerate(d["rows"], 1):
        key = f"{po}/{i}"
        code_key = f"{code}:{r['item']}"
        if code_key not in ITEMS:
            REPORT["unresolved"].append(f"{d['url']}: item {code_key} has no SKU in the store")
            continue
        ex = next((ln for ln in p["lines"] if ln["sku"] == code_key), None)
        if ex:
            key = ex["key"]
        else:
            p["lines"].append({"key": key, "sku": code_key, "qty": int(r["qty"]), "price": r["price"]})
        lk, LE = "poline:" + key, ["po_line/key", key]
        t.a(lk, LE, "core/part_of", Po(po))
        t.a(lk, LE, "po_line/sku", ["factory/item_code", code_key])
        t.a(lk, LE, "po_line/quantity", r["qty"])
        t.a(lk, LE, "po_line/unit_price", r["price"])
        if ex:
            ex["qty"] = int(r["qty"]); ex["price"] = r["price"]
    set_po_status(t, po, "confirmed")
    dt.done()

def do_qc(d):
    dt = DocTx(d)
    t = dt.at(1)
    po = d["po"]
    E = ["qc/report_no", d["report_no"]]; k = "qc:" + d["report_no"]
    t.a(k, E, "qc/po", Po(po))
    t.a(k, E, "qc/inspected_on", d["inspected_on"])
    t.a(k, E, "qc/result", d["result"])
    t.a(k, E, "qc/inspector", d["agency"])
    t.a(k, E, "qc/sample_size", d["sample"])
    if d["result"] == "PASS":
        set_po_status(t, po, "ready")
    dt.done()

HS_DIFF = set()
def do_cipl(d):
    dt = DocTx(d)
    t = dt.at(1)
    po = d["po"]
    p = po_state(po)
    pos = {po}
    s = find_ship_for_docs(d["hbl"], d["vessel"], pos)
    if s is None:
        s = new_ship(hbl=d["hbl"])
        STATS["shipments_from_docs"] += 1
        REPORT["note"].append(f"{d['url']}: no booking found for HBL {d['hbl']}; shipment created from the invoice")
    elif s["hbl"] is None:
        s["hbl"] = d["hbl"]; s["hbl_tx"] = t
        t.a(skey(s), ["shipment/booking_no", s["so"]], "shipment/hbl", d["hbl"])
    s["pos"].add(po)
    E = sref(s, t); k = skey(s)
    if d["container"] != "LCL":
        if s["container"] and s["container"] != d["container"]:
            REPORT["discrepancy"].append(f"{d['url']}: container {d['container']} vs {s['container']} already recorded")
        t.a(k, E, "shipment/container_no", d["container"])
        s["container"] = d["container"]
    t.a(k, E, "shipment/vessel", d["vessel"]); s["vessel"] = d["vessel"]
    t.a(k, E, "shipment/origin", d["origin"]); s["origin"] = d["origin"]
    t.a(k, E, "shipment/destination", d["dest"]); s["dest"] = d["dest"]
    for r in d["rows"]:
        pk = d["pack"].get(r["item"])
        ln = add_ship_line(t, s, po, r["item"], int(r["qty"]), int(pk["ctns"]) if pk else None, d)
        if ln is None:
            continue
        s["departed_docs"].add(d["url"])
        # HS code
        key = f"{p['supplier']}:{r['item']}"
        if key in ITEMS and ITEMS[key] != r["hs"] and (key, r["hs"]) not in HS_DIFF:
            HS_DIFF.add((key, r["hs"]))
            REPORT["hs"].append(f"{d['url']}: {key} invoice HS {r['hs']} vs SKU {ITEMS[key]}")
    for ln in p["lines"]:
        sold = sum(v["qty"] for ss in SHIPS for kk, v in ss["lines"].items() if v["po"] == po and kk == ln["key"])
        if sold != ln["qty"] and any(r["item"] and find_line(po, r["item"]) is ln for r in d["rows"]):
            REPORT["discrepancy"].append(f"{d['url']}: {ln['key']} invoiced {sold} vs ordered {ln['qty']}")
    if ship_covers(po):
        set_po_status(t, po, "shipped")
    dt.done()

# ------------------------------------------------------------------ email handlers
def dmy(s): return datetime.strptime(s, "%d %b %Y").date()

def do_email(d):
    sub, body = d["subject"], d["body"]
    dt = DocTx(d)
    t = dt.at(1)
    if sub.startswith("Booking Confirmation"):
        so = re.search(r"SO: (\S+)", body).group(1)
        eq = re.search(r"Equipment: (.*)", body).group(1)
        mode = "LCL" if eq.startswith("LCL") else re.search(r"(\d+x)?(\d+(?:GP|HQ))", eq).group(2)
        vessel = re.search(r"Vessel/Voyage: (.*)", body).group(1).strip()
        m = re.search(r"POL: .*?\((\w{5})\)\s+POD: .*?\((\w{5})\)", body)
        o, de = m.groups()
        etd = dmy(re.search(r"ETD: (.*)", body).group(1)); eta = dmy(re.search(r"ETA: (.*)", body).group(1))
        pos = {norm_po(x) for x in re.findall(r"(?:PO|po)[#\s-]*[\d-]+", re.search(r"POs: (.*)", body).group(1))} - {None}
        s = ship_by_so(so)
        if s is None:
            s = new_ship(so=so)
        s.update(vessel=vessel, origin=o, dest=de, mode=mode)
        s["pos"] |= pos
        E = ["shipment/booking_no", so]; k = skey(s)
        t.a(k, E, "shipment/mode", mode)
        t.a(k, E, "shipment/vessel", vessel)
        t.a(k, E, "shipment/origin", o)
        t.a(k, E, "shipment/destination", de)
        t.a(k, E, "shipment/etd", iso(local_midnight(etd, o)))
        t.a(k, E, "shipment/eta", iso(local_midnight(eta, de)))
        if rank(STATUS_SH, s["status"]) < 0:
            t.a(k, E, "shipment/status", "booked"); s["status"] = "booked"
    elif "ROLLED" in sub:
        so = re.search(r"SO (\S+)", sub).group(1)
        s = ship_by_so(so)
        m = re.search(r"New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})", body)
        E = sref(s); k = skey(s)
        t.a(k, E, "shipment/etd", iso(local_midnight(dmy(m.group(1)), s["origin"])))
        t.a(k, E, "shipment/eta", iso(local_midnight(dmy(m.group(2)), s["dest"])))
    elif sub.startswith("Shipping Advice"):
        hbl = re.search(r"HBL: (\S+)", body).group(1)
        cont = re.search(r"Container/Seal: (\S+) /", body).group(1)
        vessel = re.search(r"Vessel/Voyage: (.*)", body).group(1).strip()
        m = re.search(r"ATD (\w[\w ]*?): (\d+ \w+ \d{4})", body)
        opn, atd = PORT_NAME[m.group(1)], dmy(m.group(2))
        m = re.search(r"ETA ([\w /]+?): (\d+ \w+ \d{4})", body)
        dpn, eta = PORT_NAME[m.group(1)], dmy(m.group(2))
        rows = re.findall(r"^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs", body, re.M)
        pos = {r[0] for r in rows}
        s = find_ship_for_docs(hbl, vessel, pos)
        if s is None:
            s = new_ship(hbl=hbl, vessel=vessel, origin=opn, dest=dpn)
            REPORT["note"].append(f"{d['url']}: no booking found for HBL {hbl}; shipment created from the pre-alert")
            t.a(skey(s), sref(s), "shipment/vessel", vessel)
            t.a(skey(s), sref(s), "shipment/origin", opn)
            t.a(skey(s), sref(s), "shipment/destination", dpn)
        elif s["hbl"] is None:
            s["hbl"] = hbl; s["hbl_tx"] = t
            t.a(skey(s), ["shipment/booking_no", s["so"]], "shipment/hbl", hbl)
        E = sref(s, t); k = skey(s)
        if cont != "LCL":
            if s["container"] and s["container"] != cont:
                REPORT["discrepancy"].append(f"{d['url']}: container {cont} vs {s['container']} already recorded")
            t.a(k, E, "shipment/container_no", cont); s["container"] = cont
        t.a(k, E, "shipment/etd", iso(local_midnight(atd, opn)))
        t.a(k, E, "shipment/eta", iso(local_midnight(eta, dpn)))
        if rank(STATUS_SH, "departed") > rank(STATUS_SH, s["status"]):
            t.a(k, E, "shipment/status", "departed"); s["status"] = "departed"
        s["departed_docs"].add(d["url"]); s["atd"] = atd
        for po, item, ctns, pcs in rows:
            add_ship_line(t, s, po, item, int(pcs), int(ctns), d)
        for po in sorted(pos):
            if ship_covers(po):
                set_po_status(t, po, "shipped")
                # actual departure date
                t.a("po:" + po, Po(po), "po/etd", atd.isoformat())
    elif sub.startswith("ETA update"):
        hbl = re.search(r"HBL (\S+)", sub).group(1)
        s = ship_by_hbl(hbl)
        eta = dmy(re.search(r"revised ETA (\d+ \w+ \d{4})", body).group(1))
        t.a(skey(s), sref(s), "shipment/eta", iso(local_midnight(eta, s["dest"])))
    elif sub.startswith("Arrival Notice"):
        hbl = re.search(r"HBL (\S+)", sub).group(1)
        s = ship_by_hbl(hbl)
        m = re.search(r"arriving ([\w /]+?) on (\d+ \w+ \d{4})", body)
        port = PORT_NAME[m.group(1)]
        if port != s["dest"]:
            REPORT["discrepancy"].append(f"{d['url']}: arrival port {port} differs from shipment destination {s['dest']}")
        E = sref(s); k = skey(s)
        t.a(k, E, "shipment/eta", iso(local_midnight(dmy(m.group(2)), port)))
        if rank(STATUS_SH, "arrived") > rank(STATUS_SH, s["status"]):
            t.a(k, E, "shipment/status", "arrived"); s["status"] = "arrived"
    elif sub.startswith("Receipt complete"):
        ident = sub.rsplit(" - ", 1)[1].strip()
        cs = ship_by_cont(ident) or ([ship_by_hbl(ident)] if ship_by_hbl(ident) else [])
        if len(cs) != 1:
            REPORT["unresolved"].append(f"{d['url']}: receipt for {ident} matches {len(cs)} shipments"); return
        s = cs[0]
        E = sref(s); k = skey(s)
        if rank(STATUS_SH, "delivered") > rank(STATUS_SH, s["status"]):
            t.a(k, E, "shipment/status", "delivered"); s["status"] = "delivered"
        t.a(k, E, "shipment/delivered_at", iso(d["issued"]))
        s["delivered"] = True
        for line in re.findall(r"^\s+(ACMH-\d+) \((.*?)\): expected (\d+), received (\d+), damaged (\d+)", body, re.M):
            if line[2] != line[3] or line[4] != "0":
                REPORT["warehouse"].append(f"{d['url']} {ident}: {line[0]} {line[1]} expected {line[2]} received {line[3]} damaged {line[4]}")
        for po in sorted({v["po"] for v in s["lines"].values()}):
            carriers = [x for x in SHIPS if any(v["po"] == po for v in x["lines"].values())]
            if all(x["delivered"] for x in carriers):
                set_po_status(t, po, "received")
    elif sub.startswith("Entry Summary"):
        m = re.match(r"Entry Summary (\S+) - (\S+)", sub)
        entry, ident = m.groups()
        cs = ship_by_cont(ident) or ([ship_by_hbl(ident)] if ship_by_hbl(ident) else [])
        if len(cs) != 1:
            REPORT["unresolved"].append(f"{d['url']}: entry {entry} for {ident} matches {len(cs)} shipments"); return
        s = cs[0]
        g = lambda lab: Decimal(re.search(lab + r": USD ([\d,]+\.\d+)", body).group(1).replace(",", ""))
        value = g("Entered value"); duty = g(r"Duty \(HTS\)") + g("Section 301") + g("Additional duties"); fees = g("MPF") + g("HMF")
        total = g("Total duties and fees")
        if duty + fees != total:
            REPORT["discrepancy"].append(f"{d['url']}: duty {duty} + fees {fees} != stated total {total}")
        E = ["customs/entry_no", entry]; k = "cust:" + entry
        t.a(k, E, "customs/shipment", sref(s))
        t.a(k, E, "customs/filed_on", d["issued"].date().isoformat())
        t.a(k, E, "customs/entered_value", str(value))
        t.a(k, E, "customs/duty", str(duty))
        t.a(k, E, "customs/fees", str(fees))
        t.a(k, E, "core/currency", "USD")
    dt.done()

# ------------------------------------------------------------------ chat handlers
CH = collections.defaultdict(lambda: {"ctx_pi": None, "ctx_po": None, "dep": None, "paid": [], "seen_sent": set()})

def next_occurrence(m, dday, msg_dt):
    base = msg_dt.astimezone(SH).date()
    for y in (base.year, base.year + 1):
        try:
            c = date(y, m, dday)
        except ValueError:
            continue
        if c >= base:
            return c

def do_chat(d):
    code, txt = d["code"], d["text"].strip()
    st = CH[d["file"]]
    dt = DocTx(d)
    sup_ok = code in SUPPLIERS
    if d["mine"]:
        m = (re.search(r"new PO (PO-\d{4}-\d{4}) attached", txt) or re.search(r"here's (PO-\d{4}-\d{4})\.", txt)
             or re.search(r"PO (PO-\d{4}-\d{4}) for \d+ items", txt))
        if m:
            po = m.group(1)
            st["ctx_po"] = po
            ps = po_state(po)
            if ps["placed"] is None:
                ps["placed"] = d["issued"].astimezone(NY).date().isoformat()
                t = dt.at(1)
                t.a("po:" + po, Po(po), "po/placed_on", ps["placed"])
                t.a("po:" + po, Po(po), "po/supplier", Sup(code))
                if ps["supplier"] and ps["supplier"] != code:
                    REPORT["discrepancy"].append(f"{d['url']}: PO {po} sent to {code} but PI supplier is {ps['supplier']}")
                ps["supplier"] = ps["supplier"] or code
            else:
                REPORT["note"].append(f"{d['url']}: PO {po} mentioned as sent again; placed_on kept at {ps['placed']}")
        m = re.search(r"deposit for (PO-\d{4}-\d{4})", txt)
        if m:
            st["dep"] = (m.group(1), True, d)
        elif txt.startswith("Deposit paid today"):
            st["dep"] = (st["ctx_pi_po"] if st.get("ctx_pi_po") else st["ctx_po"], False, d)
        dt.done()
        return
    # supplier messages
    if re.match(r"\[文件\] (\S+)\.pdf$", txt):
        name = re.match(r"\[文件\] (\S+)\.pdf$", txt).group(1)
        if name in PI_BY_NO:
            st["ctx_pi_po"] = PI_BY_NO[name]["po"]
        dt.done(); return
    ctxpo = st.get("ctx_pi_po") or st["ctx_po"]
    # deposit acknowledged / production started
    if txt in ("Received, thank you", "收到，谢谢", "定金收到了，马上安排生产") and st["dep"]:
        po, named, ddoc = st["dep"]
        st["dep"] = None
        if po:
            conf = Decimal("0.9")  # PO named, or matched by deposit amount to the PI
            set_po_status(dt.at(conf), po, "in_production")
            st["paid"].append(po)
        dt.done(); return
    if txt == "大货生产中":
        po = st["paid"][-1] if st["paid"] else None
        if po and rank(STATUS_PO, po_state(po)["status"]) < rank(STATUS_PO, "in_production"):
            set_po_status(dt.at(Decimal("0.8")), po, "in_production")
        elif po is None:
            REPORT["unresolved"].append(f"{d['url']}: production started, no PO with deposit in this chat")
        dt.done(); return
    # ETD messages
    po = conf = None; mo = dd = None
    m = re.match(r"^ETD (\d+)/(\d+)$", txt)
    if m:
        mo, dd, po, conf = int(m.group(1)), int(m.group(2)), ctxpo, Decimal("0.8")
    m = re.match(r"^交期(\d+)月(\d+)号左右", txt)
    if m:
        mo, dd, po, conf = int(m.group(1)), int(m.group(2)), ctxpo, Decimal("0.8")
    m = re.search(r"ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)", txt)
    if m:
        po, mo, dd, conf = m.group(1), int(m.group(2)), int(m.group(3)), Decimal("0.9")
    m = re.search(r"(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号", txt)
    if m:
        po, mo, dd, conf = m.group(1), int(m.group(2)), int(m.group(3)), Decimal("0.9")
    m = re.search(r"Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货", txt)
    if m:
        pi = PI_BY_NO.get(m.group(1))
        if pi is None:
            REPORT["unresolved"].append(f"{d['url']}: PI {m.group(1)} not found")
        else:
            po, mo, dd, conf = pi["po"], int(m.group(2)), int(m.group(3)), Decimal("0.9")
    if mo is not None:
        if po is None:
            REPORT["unresolved"].append(f"{d['url']}: ETD message with no PO context")
        else:
            etd = next_occurrence(mo, dd, d["issued"])
            ps = po_state(po)
            if ps["status"] in ("shipped", "received"):
                REPORT["note"].append(f"{d['url']}: ETD {etd} for {po} ignored, PO already {ps['status']}")
            else:
                dt.at(conf).a("po:" + po, Po(po), "po/etd", etd.isoformat())
        dt.done(); return
    # container
    m = re.search(r"(?:container loaded: |Container )([A-Z]{4}\d{7})", txt)
    if m and ("loaded" in txt):
        cn = m.group(1)
        mine = {p for p, v in PO.items() if v["supplier"] == code}
        cands = [s for s in SHIPS if (s["pos"] & mine) and s["container"] is None and s["status"] in ("booked", None)]
        if len(cands) == 1:
            s = cands[0]
            s["container"] = cn
            dt.at(Decimal("0.9")).a(skey(s), sref(s), "shipment/container_no", cn)
        else:
            REPORT["unresolved"].append(f"{d['url']}: container {cn} from {code}: {len(cands)} candidate shipments")
        dt.done(); return
    # price changes, holidays, samples, small talk: no facts
    kinds = [("price", r"单价上调|涨|降价|labour costs|volume rebate|prices"), ("holiday", r"放假|holiday"), ("sample", r"Samples sent by DHL")]
    for name, rx in kinds:
        if re.search(rx, txt):
            REPORT["gap_" + name].append(f"{d['url']}: {txt[:140]}")
    if txt.startswith("Deposit paid") or "deposit for" in txt or txt.startswith(("Balance", "Balance paid")):
        pass
    dt.done()

# ------------------------------------------------------------------ run
def main():
    for d in ALL:
        k = d["kind"]
        if k == "pi": do_pi(d)
        elif k == "qc": do_qc(d)
        elif k == "cipl": do_cipl(d)
        elif k == "email": do_email(d)
        elif k == "chat": do_chat(d)
    json.dump(TXS, open(S + "/plan.json", "w"), indent=1)
    json.dump({k: v for k, v in REPORT.items()}, open(S + "/report.json", "w"), indent=1, ensure_ascii=False)
    print("transactions:", len(TXS), dict(STATS))
    for k, v in REPORT.items():
        print(f"--- {k}: {len(v)}")
        for x in v[:40]:
            print("   ", x)

if __name__ == "__main__":
    main()

def summary():
    for s in SHIPS:
        print(s["id"], s["so"], s["hbl"], s["container"], s["vessel"], s["origin"], s["dest"], s["mode"], s["status"], sorted(s["pos"]), len(s["lines"]))
    for p in sorted(PO):
        v = PO[p]
        print(p, v["supplier"], v["pi"], v["status"], v["placed"], v["supplier"])
