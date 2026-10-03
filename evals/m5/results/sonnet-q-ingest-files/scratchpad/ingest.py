import sys, re, json, collections, datetime as dt
import factstore
from load import *

DRY = "--write" not in sys.argv
RANK = {"draft": 0, "sent": 1, "confirmed": 2, "in_production": 3, "ready": 4, "shipped": 5, "received": 6}
SRANK = {"booked": 0, "departed": 1, "arrived": 2, "delivered": 3}

docs = load_all()
by_kind = collections.defaultdict(list)
for d in docs:
    by_kind[d["kind"]].append(d)

# ---- store state
sku_by_code = {r[0]: r[1] for r in factstore.query('select v, e from "factory/item_code"').rows}
sku_hs = {r[0]: r[1] for r in factstore.query('select e, v from "sku/hs_code"').rows}
backed = {r[0] for r in factstore.query(
    """select h.v from facts f join "core/evidence" ev on ev.e = f.tx join "document/hash" h on h.e = ev.v
       where f.a ~ '^(po|po_line|shipment|shipment_line|qc|customs)/' group by 1""").rows}

# PI number -> PO, PO -> supplier code (from the PIs themselves; used to resolve chat references)
pi_po = {d["pi_no"]: d["po"] for d in by_kind["pi"]}
po_sup = {d["po"]: d["code"] for d in by_kind["pi"]}
pi_by_po = {d["po"]: d for d in by_kind["pi"]}

po_status = {}
po_lines = collections.defaultdict(dict)   # po -> {sku item code "SUP:item": (line key, qty)}
po_etd = {}
known_pos = set(po_sup)

report = collections.defaultdict(list)
counts = collections.Counter()
low_conf = []
done_docs = set()


class Ship:
    def __init__(self):
        self.so = self.hbl = self.container = self.vessel = self.origin = self.dest = None
        self.pos = set(); self.status = None; self.lines = {}; self.sailed_pos = set()
        self.hbl_in_store = False; self.mode = None; self.depart = None; self.delivered = False

    def e(self):
        if self.hbl and self.hbl_in_store:
            return ["shipment/hbl", self.hbl]
        return ["shipment/booking_no", self.so]


ships = []


def ship_by_hbl(h):
    for s in ships:
        if s.hbl == h:
            return s


def ship_by_so(so):
    for s in ships:
        if s.so == so:
            return s


def ship_by_container(c, when, want=None):
    cands = [s for s in ships if s.container == c and s.depart and s.depart <= when]
    if want:
        c2 = [s for s in cands if want(s)]
        cands = c2 or cands
    return max(cands, key=lambda s: s.depart) if cands else None


def find_booking(vessel, pos, origin=None):
    c = [s for s in ships if s.hbl is None and s.vessel == vessel and (s.pos & set(pos))]
    if origin:
        c2 = [s for s in c if s.origin == origin]
        c = c2 or c
    return c


def tx(d, conf, facts):
    """One transaction: facts + evidence + confidence (+ document facts the first time)."""
    if not facts:
        return
    allf = []
    if d["hash"] not in done_docs:
        done_docs.add(d["hash"])
        allf += [{"e": ["document/hash", d["hash"]], "a": "document/url", "v": d["url"]},
                 {"e": ["document/hash", d["hash"]], "a": "document/issued_at", "v": d["issued"].isoformat()}]
    allf += [{"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", d["hash"]]},
             {"e": "tmp:tx", "a": "core/confidence", "v": str(conf)}]
    allf += [{"e": e, "a": a, "v": v} for e, a, v in facts]
    if d["hash"] in backed and "--force" not in sys.argv:
        counts["skipped_already_read"] += 1
        return
    try:
        r = factstore.transact(allf, dry_run=DRY)
    except Exception as ex:
        print("FAILED", d["url"], str(ex)[:400]); raise SystemExit(1)
    counts[f"tx:{d['kind']}"] += 1
    if str(conf) != "1":
        low_conf.append((d["url"], conf, [(a, v) for e, a, v in facts]))


def PO(p):
    return ["po/number", p]


def advance_po(d, po, new, facts):
    cur = po_status.get(po)
    if cur is None or RANK[new] > RANK[cur]:
        po_status[po] = new
        facts.append((PO(po), "po/status", new))
        return True
    return False


def po_shipped(po):
    lines = po_lines.get(po)
    if lines:
        tot = collections.Counter()
        for s in ships:
            for plk, q in s.lines.items():
                if plk.startswith(po + "/"):
                    tot[plk] += q
        if all(tot[k] >= q for k, q in lines.values()):
            return True
    sh = [s for s in ships if po in s.pos or any(k.startswith(po + "/") for k in s.lines)]
    return bool(sh) and all(po in s.sailed_pos for s in sh)


def po_received(po):
    sh = [s for s in ships if any(k.startswith(po + "/") for k in s.lines)]
    return bool(sh) and all(s.delivered for s in sh)


def next_md(m, dd, after: dt.date):
    for y in (after.year, after.year + 1):
        try:
            c = dt.date(y, m, dd)
        except ValueError:
            continue
        if c >= after:
            return c


# ------------------------------------------------------------------ handlers
def do_pi(d):
    po, code = d["po"], d["code"]
    f = [(PO(po), "po/pi_number", d["pi_no"]), (PO(po), "po/supplier", ["supplier/code", code]),
         (PO(po), "po/etd", d["etd"].isoformat()), (PO(po), "core/currency", d["cur"])]
    sup = ["supplier/code", code]
    f += [(sup, "supplier/name", d["name"]), (sup, "supplier/name_cn", d["cn"]), (sup, "supplier/address", d["addr"]),
          (sup, "supplier/incoterm", d["incoterm"]), (sup, "supplier/payment_terms", d["pay"]),
          (sup, "supplier/currency", d["cur"]), (sup, "supplier/port", d["port"]),
          (sup, "supplier/contact_name", d["contact"])]
    for i, it in enumerate(d["items"], 1):
        key = f"{po}/{i}"
        ic = f"{code}:{it['item']}"
        if ic not in sku_by_code:
            report["unresolved item code"].append((d["url"], ic))
            continue
        lk = ["po_line/key", key]
        f += [(lk, "core/part_of", PO(po)), (lk, "po_line/sku", ["factory/item_code", ic]),
              (lk, "po_line/quantity", it["qty"]), (lk, "po_line/unit_price", it["price"])]
        po_lines[po][ic] = (key, int(it["qty"]))
    advance_po(d, po, "confirmed", f)
    po_etd[po] = d["etd"]
    tx(d, 1, f)


def do_qc(d):
    f = [(["qc/report_no", d["report"]], "qc/po", PO(d["po"])),
         (["qc/report_no", d["report"]], "qc/inspected_on", d["date"].isoformat()),
         (["qc/report_no", d["report"]], "qc/result", d["result"]),
         (["qc/report_no", d["report"]], "qc/inspector", d["inspector"]),
         (["qc/report_no", d["report"]], "qc/sample_size", d["sample"])]
    if d["result"] == "PASS":
        advance_po(d, d["po"], "ready", f)
    tx(d, 1, f)


def mk_lines(d, ship, rows, po):
    """rows: dicts with item, qty, ctns. Returns facts."""
    f = []
    code = po_sup.get(po)
    for r in rows:
        ic = f"{code}:{r['item']}"
        pl = po_lines.get(po, {}).get(ic)
        if not pl:
            report["shipment row without PO line"].append((d["url"], po, ic))
            continue
        plk, ordered = pl
        key = f"{ship.hbl}/{plk}"
        lk = ["shipment_line/key", key]
        q = int(r["qty"])
        if plk in ship.lines and ship.lines[plk] != q:
            report["shipment line quantity conflict"].append((d["url"], key, ship.lines[plk], q))
        ship.lines[plk] = q
        f += [(lk, "core/part_of", ship.e() if ship.hbl_in_store else ["shipment/hbl", ship.hbl]),
              (lk, "shipment_line/po_line", ["po_line/key", plk]), (lk, "shipment_line/quantity", str(q)),
              (lk, "shipment_line/cartons", r["ctns"])]
        if q != ordered:
            report["shipped qty differs from ordered"].append((d["url"], plk, ordered, q))
    return f


def attach(d, hbl, vessel, pos, origin):
    """Find or create the shipment for an HBL-bearing document. Returns (ship, facts)."""
    f = []
    s = ship_by_hbl(hbl)
    if s is None:
        c = find_booking(vessel, pos, origin)
        if len(c) == 1:
            s = c[0]
            s.hbl = hbl
            f.append((s.e(), "shipment/hbl", hbl))
            # after this transaction the HBL identifies it
        elif len(c) > 1:
            report["ambiguous booking"].append((d["url"], hbl, [x.so for x in c]))
        if s is None:
            s = Ship(); s.hbl = hbl; ships.append(s)
            report["shipment without booking"].append((d["url"], hbl))
            s.hbl_in_store = False
    return s, f


def finish_hbl(s):
    s.hbl_in_store = True


def do_ci(d):
    po = d["po"]
    s, f = attach(d, d["hbl"], d["vessel"], [po], d["origin"])
    first = not s.hbl_in_store
    ent = s.e() if s.hbl_in_store else (["shipment/booking_no", s.so] if s.so else ["shipment/hbl", s.hbl])
    if d["container"] != "LCL":
        f.append((ent, "shipment/container_no", d["container"])); s.container = d["container"]
    f += [(ent, "shipment/vessel", d["vessel"]), (ent, "shipment/origin", d["origin"]),
          (ent, "shipment/destination", d["dest"])]
    s.vessel, s.origin, s.dest = d["vessel"], d["origin"], d["dest"]
    s.pos.add(po)
    if s.depart is None:
        s.depart = d["issued"]
    # lines: part_of via hbl lookup requires hbl to exist -> use the same entity ref
    lf = mk_lines(d, s, d["rows"], po)
    f += [(e, a, ent if a == "core/part_of" else v) for e, a, v in lf]
    # HS code check
    for r in d["rows"]:
        ic = f"{po_sup[po]}:{r['item']}"
        sk = sku_by_code.get(ic)
        if sk is not None and sku_hs.get(sk) and sku_hs[sk] != r["hs"]:
            report["HS code differs from SKU"].append((d["url"], ic, sku_hs[sk], r["hs"]))
    s.sailed_pos.add(po)
    tx(d, 1, f)
    s.hbl_in_store = True
    shipped_check(d, [po], None)


def shipped_check(d, pos, atd):
    f = []
    for po in pos:
        if po_shipped(po):
            advance_po(d, po, "shipped", f)
            if atd is not None and (po_status.get(po) == "shipped"):
                f.append((PO(po), "po/etd", atd.isoformat())); po_etd[po] = atd
    if f:
        tx(d, 1, f)


def do_booking(d):
    s = ship_by_so(d["so"])
    if s is None:
        s = Ship(); s.so = d["so"]; ships.append(s)
    s.vessel, s.origin, s.dest, s.mode = d["vessel"], d["origin"], d["dest"], d["mode"]
    s.pos |= set(d["pos"]); s.status = "booked"
    s.depart = d["issued"]
    for p in d["pos"]:
        if p not in known_pos:
            report["booking PO not in any PI"].append((d["url"], p, d["pos_raw"]))
    e = ["shipment/booking_no", d["so"]]
    f = [(e, "shipment/mode", d["mode"]), (e, "shipment/vessel", d["vessel"]), (e, "shipment/origin", d["origin"]),
         (e, "shipment/destination", d["dest"]), (e, "shipment/etd", local_midnight(d["etd_d"], d["origin"])),
         (e, "shipment/eta", local_midnight(d["eta_d"], d["dest"])), (e, "shipment/status", "booked")]
    tx(d, 1, f)
    # loosely written PO references were interpreted: record nothing about them in the store


def do_rolled(d):
    s = ship_by_so(d["so"])
    if not s:
        report["rolled booking unknown"].append((d["url"], d["so"])); return
    e = s.e()
    tx(d, 1, [(e, "shipment/etd", local_midnight(d["etd_d"], s.origin)),
              (e, "shipment/eta", local_midnight(d["eta_d"], s.dest))])


def do_prealert(d):
    pos = sorted({l["po"] for l in d["lines"]})
    s, f = attach(d, d["hbl"], d["vessel"], pos, d["origin"])
    ent = s.e() if s.hbl_in_store else (["shipment/booking_no", s.so] if s.so else ["shipment/hbl", s.hbl])
    s.vessel, s.origin, s.dest = d["vessel"], d["origin"], d["dest"]
    if d["container"] != "LCL":
        f.append((ent, "shipment/container_no", d["container"])); s.container = d["container"]
    f += [(ent, "shipment/vessel", d["vessel"]), (ent, "shipment/origin", d["origin"]),
          (ent, "shipment/destination", d["dest"]),
          (ent, "shipment/etd", local_midnight(d["atd"], d["origin"])),
          (ent, "shipment/eta", local_midnight(d["eta_d"], d["dest"]))]
    if s.status is None or SRANK[s.status] < SRANK["departed"]:
        f.append((ent, "shipment/status", "departed")); s.status = "departed"
    s.depart = dt.datetime(d["atd"].year, d["atd"].month, d["atd"].day, tzinfo=CN)
    byp = collections.defaultdict(list)
    for l in d["lines"]:
        byp[l["po"]].append(l)
    for po, rows in byp.items():
        s.pos.add(po)
        lf = mk_lines(d, s, rows, po)
        f += [(e, a, ent if a == "core/part_of" else v) for e, a, v in lf]
        s.sailed_pos.add(po)
    tx(d, 1, f)
    s.hbl_in_store = True
    shipped_check(d, pos, d["atd"])


def ship_for_hbl_email(d):
    s = ship_by_hbl(d["hbl"])
    if not s:
        report["email for unknown HBL"].append((d["url"], d["hbl"]))
    return s


def do_eta(d):
    s = ship_for_hbl_email(d)
    if s:
        tx(d, 1, [(s.e(), "shipment/eta", local_midnight(d["eta_d"], s.dest))])


def do_arrival(d):
    s = ship_for_hbl_email(d)
    if not s:
        return
    if s.dest and s.dest != d["dest"]:
        report["arrival port differs"].append((d["url"], s.dest, d["dest"]))
    f = [(s.e(), "shipment/eta", local_midnight(d["eta_d"], d["dest"]))]
    if SRANK.get(s.status, -1) < SRANK["arrived"]:
        f.append((s.e(), "shipment/status", "arrived")); s.status = "arrived"
    tx(d, 1, f)


def do_entry(d):
    ref = d["ref"]
    s = ship_by_hbl(ref) if ref.startswith("PBLHB") else ship_by_container(ref, d["issued"])
    if not s:
        report["entry for unknown shipment"].append((d["url"], ref)); return
    duty = (Decimal(d["hts"]) + Decimal(d["s301"]) + Decimal(d["addl"]))
    fees = Decimal(d["mpf"]) + Decimal(d["hmf"])
    if duty + fees != Decimal(d["total"]):
        report["entry total mismatch"].append((d["url"], str(duty + fees), d["total"]))
    e = ["customs/entry_no", d["entry"]]
    tx(d, 1, [(e, "customs/shipment", s.e()), (e, "customs/filed_on", d["issued"].date().isoformat()),
              (e, "customs/entered_value", d["value"]), (e, "customs/duty", str(duty)),
              (e, "customs/fees", str(fees)), (e, "core/currency", "USD")])


def do_receipt(d):
    ref = d["ref"]
    s = ship_by_hbl(ref) if ref.startswith("PBLHB") else ship_by_container(
        ref, d["issued"], want=lambda x: not x.delivered)
    if not s:
        report["receipt for unknown shipment"].append((d["url"], ref)); return
    s.delivered = True; s.status = "delivered"
    f = [(s.e(), "shipment/status", "delivered"), (s.e(), "shipment/delivered_at", d["issued"].isoformat())]
    tx(d, 1, f)
    for exp in d["discrepancies"]:
        if exp[1] != exp[2] or int(exp[3]) > 0:
            report["receiving discrepancies (gap: no attribute)"].append((d["rcv"], ref, exp))
    f2 = []
    for po in sorted({k.split("/")[0] for k in s.lines}):
        if po_status.get(po) == "shipped" and po_received(po):
            advance_po(d, po, "received", f2)
    if f2:
        tx(d, 1, f2)


from decimal import Decimal

# ------------------------------------------------------------------ chat
chat_ctx = collections.defaultdict(dict)   # file -> {"last_pi_po": po, "dep_po": po}
GAPS = collections.Counter()
SENT_RE = re.compile(r"(new PO|here's|PO PO-)")


def pct_deposit(po):
    m = re.search(r"(\d+)% deposit", pi_by_po[po]["pay"])
    return int(m.group(1)) if m else None


def pi_total(po):
    return sum(Decimal(i["amount"]) for i in pi_by_po[po]["items"])


def do_chat(d):
    t, f, ctx = d["text"], d["file"], chat_ctx[d["file"]]
    sup = d["sup"]
    # chat messages carry the header on the first line, text after it
    ch = d["issued"].astimezone(CN).date()
    if d["ours"]:
        m = re.search(r"PO-\d{4}-\d{4}", t)
        if m and SENT_RE.search(t) and not t.startswith("[文件]"):
            po = m.group(0)
            e = PO(po)
            tx(d, 1, [(e, "po/placed_on", d["issued"].date().isoformat()),
                      (e, "po/supplier", ["supplier/code", sup])])
            ctx.setdefault("sent", []).append(po)
            return
        m = re.match(r"Deposit paid today, (USD|CNY) ([\d,.]+)", t)
        n = re.search(r"deposit for (PO-\d{4}-\d{4}) \((USD|CNY) ([\d,.]+)\)", t)
        if m or n:
            amt = Decimal(num((n or m).group(3 if n else 2)).rstrip("."))
            po, how = None, None
            if n:
                po, how = n.group(1), "named"
            else:
                cands = [p for p in ctx.get("pis", []) if pct_deposit(p)]
                hit = [p for p in cands if abs(pi_total(p) * pct_deposit(p) / 100 - amt) < Decimal("0.05")]
                if len(hit) == 1:
                    po, how = hit[0], "amount"
                elif cands:
                    po, how = cands[-1], "latest PI"
                    report["deposit PO inferred from latest PI only"].append((d["url"], po))
            ctx["dep"] = (po, how, d["n"])
            return
        if re.search(r"QC (passed|failed)|Inspection passed|Balance|balance|quote|catalogue|samples|Sorry can you type|Again|noted|Understood|^OK$|\[", t):
            categorize(d)
            return
        categorize(d); return
    # supplier messages
    m = re.match(r"\[文件\] (.+)\.pdf", t)
    if m:
        name = m.group(1)
        if name in pi_po:
            ctx.setdefault("pis", []).append(pi_po[name]); ctx["last_pi"] = pi_po[name]; ctx["last_pi_n"] = d["n"]
        return
    # production started / deposit acknowledged
    prod = t.startswith("定金收到了") or t.startswith("大货生产中") or (
        re.match(r"(Received, thank you|收到，谢谢)$", t) and ctx.get("dep") and d["n"] - ctx["dep"][2] <= 4)
    if prod:
        dep = ctx.get("dep")
        if dep and dep[0]:
            po, how, _ = dep
            f_ = []
            if advance_po(d, po, "in_production", f_):
                tx(d, "0.8" if how == "latest PI" else "0.9", f_)
        else:
            report["production message without deposit context"].append(d["url"])
        return
    # ETD changes
    m = (re.search(r"ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)", t) or
         re.search(r"(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号", t))
    if m:
        etd_change(d, m.group(1), int(m.group(2)), int(m.group(3)), "0.9"); return
    m = re.search(r"^Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货", t)
    if m:
        po = pi_po.get(m.group(1))
        if po:
            etd_change(d, po, int(m.group(2)), int(m.group(3)), "0.85")
        else:
            report["PI number not found"].append((d["url"], m.group(1)))
        return
    m = (re.match(r"ETD (\d+)/(\d+)$", t) or re.search(r"ETD around (\d+)/(\d+)", t) or
         re.match(r"交期(\d+)月(\d+)号左右$", t))
    if m:
        po = ctx.get("last_pi")
        if po and d["n"] - ctx["last_pi_n"] <= 4:
            etd_change(d, po, int(m.group(1)), int(m.group(2)), "0.8")
        else:
            report["ETD message without PI context"].append(d["url"])
        return
    m = re.search(r"(?:Container (\w{4}\d{7}) loaded today|container loaded: (\w{4}\d{7}))", t)
    if m:
        cont = m.group(1) or m.group(2)
        container_msg(d, cont, ctx)
        return
    categorize(d)


def categorize(d):
    t = d["text"]
    if re.search(r"单价|price|rebate|降价|涨价|\+\d%|-\d%", t):
        GAPS["price change"] += 1; report["gap: price changes"].append((d["url"], t[:100]))
    elif re.search(r"放假|holiday", t):
        GAPS["holiday closure"] += 1
    elif re.search(r"[Dd]eposit|[Bb]alance|B/L copy|定金|余款", t):
        GAPS["payment"] += 1
    elif re.search(r"DHL|[Ss]amples|样品", t):
        GAPS["sample courier / packaging samples"] += 1
    elif re.search(r"^\[(图片|语音|动画表情)", t):
        GAPS["photos/voice/stickers"] += 1
    else:
        GAPS["other (small talk / QC chatter / quotes)"] += 1


def etd_change(d, po, m, dd, conf):
    cur = po_status.get(po)
    if cur and RANK[cur] >= RANK["shipped"]:
        report["ETD change after PO shipped, ignored"].append((d["url"], po)); return
    ch = d["issued"].astimezone(CN).date()
    new = next_md(m, dd, ch)
    if po_etd.get(po) == new:
        counts["chat ETD equals current, no change"] += 1; return
    po_etd[po] = new
    tx(d, conf, [(PO(po), "po/etd", new.isoformat())])


def container_msg(d, cont, ctx):
    sup = d["sup"]
    # the PO: the supplier's commercial invoice for this container
    cis = [c for c in by_kind["ci"] if c["container"] == cont and po_sup.get(c["po"]) == sup and c["issued"] >= d["issued"] - dt.timedelta(days=2)]
    if not cis:
        report["container message without matching CI"].append((d["url"], cont)); return
    ci = min(cis, key=lambda c: c["issued"])
    po = ci["po"]
    cands = [s for s in ships if po in s.pos and s.vessel == ci["vessel"] and s.container in (None, cont)]
    if len(cands) != 1:
        report["container message: shipment not unique"].append((d["url"], cont, po, len(cands))); return
    s = cands[0]
    s.container = cont
    tx(d, "0.9", [(s.e(), "shipment/container_no", cont)])


HANDLERS = dict(pi=do_pi, qc=do_qc, ci=do_ci, booking=do_booking, rolled=do_rolled, prealert=do_prealert,
                eta=do_eta, arrival=do_arrival, entry=do_entry, receipt=do_receipt, chat=do_chat)

for d in docs:
    HANDLERS[d["kind"]](d)

print("MODE", "DRY RUN" if DRY else "WRITE")
print(dict(counts))
print("chat non-fact categories:", dict(GAPS))
for k, v in report.items():
    print(f"\n## {k} ({len(v)})")
    for x in v[:12]:
        print("  ", x)
print("\nlow confidence txs:", len(low_conf))
json.dump(dict(report={k: [str(x) for x in v] for k, v in report.items()}, low=[str(x) for x in low_conf],
               gaps=dict(GAPS), counts=dict(counts)),
          open("run_report.json", "w"), indent=1, ensure_ascii=False)

if "--summary" in sys.argv:
    print(collections.Counter(po_status.values()))
    for po in sorted(known_pos):
        sh=[(s.so,s.hbl,s.status,s.delivered) for s in ships if po in s.pos or any(k.startswith(po+"/") for k in s.lines)]
        print(po, po_status.get(po), po_etd.get(po), sh)
    print(len(ships), collections.Counter(s.status for s in ships))
