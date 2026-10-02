import re, json, hashlib, glob, os, sys
from datetime import datetime, date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
import parse_pdf, parse_mail
import factstore

SH = ZoneInfo('Asia/Shanghai'); NY = ZoneInfo('America/New_York'); LA = ZoneInfo('America/Los_Angeles')
PORT_TZ = {'CNYTN': SH, 'CNNGB': SH, 'CNNSA': SH, 'CNXMN': SH, 'USNYC': NY, 'USLAX': LA}
PORT_NAME = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Nansha': 'CNNSA', 'Xiamen': 'CNXMN',
             'New York/Newark': 'USNYC', 'Los Angeles': 'USLAX'}
PREFIX = {'MT': 'NBBW', 'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'QS': 'NBQS', 'RF': 'DGRF', 'TY': 'HZTY', 'YD': 'XMYD'}
CHATSUP = {'DGRF_Jason': 'DGRF', 'FSMJ_Grace': 'FSMJ', 'HZTY_Coco': 'HZTY', 'NBBW_Lily': 'NBBW',
           'NBQS_Sunny': 'NBQS', 'SZHT_Kevin': 'SZHT', 'XMYD_Eric': 'XMYD', 'YWLX_Amy': 'YWLX'}
CUR = {'RMB': 'CNY', 'USD': 'USD', 'CNY': 'CNY'}
PO_RANK = {k: i for i, k in enumerate(['draft', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received'])}
SH_RANK = {k: i for i, k in enumerate(['booked', 'departed', 'arrived', 'delivered'], 1)}
MON = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}

anomalies = []
def anom(msg): anomalies.append(msg)

def local_midnight(d, port):
    return datetime(d.year, d.month, d.day, tzinfo=PORT_TZ[port]).isoformat()
def pdate(s):  # '26 Nov 2025'
    d, m, y = s.split(); return date(int(y), MON[m], int(d))
def pidate(s):  # 'Dec 05, 2025'
    m, d, y = re.match(r'(\w+) (\d+), (\d+)', s).groups(); return date(int(y), MON[m], int(d))
def norm_po(tok):
    t = tok.strip()
    m = re.search(r'(\d{4})-(\d{4})', t)
    if m: return 'PO-%s-%s' % m.groups()
    n = int(re.search(r'(\d+)', t).group(1))
    return 'PO-2025-%04d' % n if n >= 100 else 'PO-2026-%04d' % n

# ---------------------------------------------------------------- store snapshot
store_sku = {}
for r in factstore.query('select c.v code, h.v hs from "factory/item_code" c left join "sku/hs_code" h using(e)').rows:
    store_sku[r[0]] = r[1]
store_sup = {r[0] for r in factstore.query('select v from "supplier/code"').rows}

# ---------------------------------------------------------------- model state
S = dict(
    po_status={}, po_sup={}, po_lines={}, po_qty={}, po_etd={}, po_pi={}, po_total={}, po_cur={}, pi_by_no={},
    sh_by_key={},          # internal key -> shipment dict
    placed={},
)
def rank_up(cur, new, table): return table[new] > table.get(cur, -1)

events = []  # dicts: t (iso instant), order, label, doc, groups [(conf, facts)]

def doc_head(h, url, issued):
    return [{"e": ["document/hash", h], "a": "document/url", "v": url},
            {"e": ["document/hash", h], "a": "document/issued_at", "v": issued}]
def group(h, url, issued, conf, facts):
    f = doc_head(h, url, issued)
    f += [{"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", h]},
          {"e": "tmp:tx", "a": "core/confidence", "v": str(conf)}]
    return f + facts
def A(e, a, v): return {"e": e, "a": a, "v": v}
def POe(po): return ["po/number", po]

def set_po_status(po, new, facts):
    cur = S['po_status'].get(po)
    if cur is None or PO_RANK[new] > PO_RANK[cur]:
        S['po_status'][po] = new
        facts.append(A(POe(po), 'po/status', new))
        return True
    return False

# ---------------------------------------------------------------- load documents
PDFS = parse_pdf.load()
MAILS = parse_mail.load()
for m in MAILS: m['t'] = m['issued']
pdf_by_file = {p['file']: p for p in PDFS}

# static shipment knowledge: HBL -> info from CI + prealert, bookings
def parse_prealert(m):
    b = m['body']
    d = dict(hbl=re.search(r'HBL: (\S+)', b).group(1))
    cs = re.search(r'Container/Seal: (\S+) / (\S+)', b)
    d['cont'] = None if cs.group(1) == 'LCL' else cs.group(1)
    d['vessel'] = re.search(r'Vessel/Voyage: (.+)', b).group(1).strip()
    a = re.search(r'ATD (.+?): (\d+ \w+ \d{4})', b)
    d['origin'] = PORT_NAME[a.group(1)]; d['atd'] = pdate(a.group(2))
    e = re.search(r'ETA (.+?): (\d+ \w+ \d{4})', b)
    d['dest'] = PORT_NAME[e.group(1)]; d['eta'] = pdate(e.group(2))
    d['lines'] = [(po, item, int(c), int(q)) for po, item, c, q in
                  re.findall(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs', b)]
    return d
def parse_booking(m):
    b = m['body']
    d = dict(so=re.search(r'SO: (\S+)', b).group(1))
    eq = re.search(r'Equipment: (.+)', b).group(1)
    d['mode'] = 'LCL' if eq.startswith('LCL') else re.search(r'1x(\w+)', eq).group(1)
    d['vessel'] = re.search(r'Vessel/Voyage: (.+)', b).group(1).strip()
    pp = re.search(r'POL: .*\((\w+)\)\s+POD: .*\((\w+)\)', b)
    d['origin'], d['dest'] = pp.groups()
    d['etd'] = pdate(re.search(r'ETD: (.+)', b).group(1)); d['eta'] = pdate(re.search(r'ETA: (.+)', b).group(1))
    d['pos'] = {norm_po(x) for x in re.search(r'POs: (.+)', b).group(1).split(',')}
    return d
for m in MAILS:
    if m['kind'] == 'prealert': m['d'] = parse_prealert(m)
    if m['kind'] == 'booking': m['d'] = parse_booking(m)

hbl_info = {}
for m in MAILS:
    if m['kind'] == 'prealert':
        hbl_info[m['d']['hbl']] = dict(vessel=m['d']['vessel'], pos={l[0] for l in m['d']['lines']}, cont=m['d']['cont'])
for p in PDFS:
    if p['kind'] == 'ci':
        i = hbl_info.setdefault(p['bl'], dict(vessel=p['vessel'], pos=set(), cont=None if p['cont'] == 'LCL' else p['cont']))
        i['pos'].add(p['inv'][2])
        if i['vessel'] != p['vessel']: anom(f"vessel differs between CI {p['file']} and pre-alert: {p['vessel']} vs {i['vessel']}")
bookings = {m['d']['so']: m['d'] for m in MAILS if m['kind'] == 'booking'}
hbl2so, so2hbl = {}, {}
for hbl, i in hbl_info.items():
    c = [so for so, b in bookings.items() if b['vessel'] == i['vessel'] and b['pos'] & i['pos']]
    if len(c) == 1: hbl2so[hbl] = c[0]; so2hbl[c[0]] = hbl
    elif len(c) > 1: anom(f'HBL {hbl} matches several bookings {c}')
    else: anom(f'HBL {hbl} matches no booking (vessel {i["vessel"]}, POs {sorted(i["pos"])})')
for so in bookings:
    if so not in so2hbl: anom(f'booking {so} matches no HBL (no pre-alert/CI)')
cont2hbl = {}
for hbl, i in hbl_info.items():
    if i['cont']:
        if i['cont'] in cont2hbl: anom(f'container {i["cont"]} on two HBLs')
        cont2hbl[i['cont']] = hbl

