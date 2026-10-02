import re, json, os, hashlib, sys, datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime as pdt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pi import parse_pi, pdfs, D
from mbox import msgs
EXP = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-a-jtof532b/ingest/work/exports'
NY = ZoneInfo('America/New_York'); CN = ZoneInfo('Asia/Shanghai'); LA = ZoneInfo('America/Los_Angeles'); UTC = ZoneInfo('UTC')
PORT_TZ = {'USNYC': NY, 'USLAX': LA}
for k in ('CNNGB', 'CNYTN', 'CNXMN', 'CNNSA'): PORT_TZ[k] = CN
PREFIX = {'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'MT': 'NBBW', 'QS': 'NBQS', 'RF': 'DGRF', 'TY': 'HZTY', 'YD': 'XMYD'}
CHATS = {'DGRF_Jason': 'DGRF', 'FSMJ_Grace': 'FSMJ', 'HZTY_Coco': 'HZTY', 'NBBW_Lily': 'NBBW', 'NBQS_Sunny': 'NBQS', 'SZHT_Kevin': 'SZHT', 'XMYD_Eric': 'XMYD', 'YWLX_Amy': 'YWLX'}
RANK = {s: i for i, s in enumerate(['draft', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received'])}
MON = {m: i + 1 for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}
NOTES = []   # diagnostics / report items
def note(*a): NOTES.append(' '.join(str(x) for x in a))

# store facts needed: SKU item codes and HS codes
import factstore
ITEM = {r[0]: r[1] for r in factstore.query('select i.v, h.v from "factory/item_code" i join "sku/hs_code" h using(e)').rows}
STORE_POS = {r[0] for r in factstore.query('select v from "po/number"').rows}

def utc(d): return d.astimezone(UTC)
def day(s): return dt.datetime.strptime(s, '%Y-%m-%d').replace(hour=12, tzinfo=UTC)   # date-only documents sort at midday UTC
def pdate(s):   # '26 Nov 2025'
    d, m, y = s.split(); return dt.date(int(y), MON[m], int(d))
def inst(d, loc):  # date at 00:00 port-local time
    return dt.datetime(d.year, d.month, d.day, tzinfo=PORT_TZ[loc]).isoformat()

EV = []  # events: dict(ts, kind, doc=(hash,url), ...)

# ---------------- PDFs ----------------
PI = {}
for f in sorted(pdfs):
    if re.match(r'(HT-PI|LX|MJ|MT|QS|RF-PI|TY|YD)[^_]*\.pdf$', f):
        d = parse_pi(f); d['sup'] = PREFIX[re.match(r'[A-Z]+', f).group(0)]
        tot = sum(Decimal(i['qty']) * Decimal(i['price']) for i in d['items'])
        txt = open(D + f + '.txt').read()
        printed = Decimal(re.search(r'TOTAL \w{3} ([\d,.]+)', txt).group(1).replace(',', ''))
        nrows = len(re.findall(r'(?m)^\S+ .+\n.*\n[\d,]+ [\d,]+ \w{3} [\d,.]+ \w{3} [\d,.]+$', txt))
        if tot != printed or nrows != len(d['items']): note('PI PARSE MISMATCH', f, tot, printed)
        for i in d['items']:
            if Decimal(i['qty']) * Decimal(i['price']) != Decimal(i['amt']): note('PI row amount mismatch', f, i)
            if f"{d['sup']}:{i['item']}" not in ITEM: note('PI item not in store', f, i['item'])
        d['etd_date'] = dt.datetime.strptime(d['etd'], '%b %d, %Y').date()
        PI[d['po']] = d
        EV.append(dict(ts=day(d['date']), kind='pi', doc=(d['hash'], 'supplier_docs/' + f), d=d))
PI_BY_NO = {d['pi']: d for d in PI.values()}

def parse_ci(f):
    t = open(D + f + '.txt').read()
    r = {}
    m = re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (\S+)', t); r['inv'], r['date'], r['po'] = m.groups()
    m = re.search(r'From (\w+) to (\w+) by sea, (MV .*?)\s+Container: (\S+)\s+B/L: (\S+)', t)
    r['pol'], r['pod'], r['vessel'], r['container'], r['hbl'] = m.groups()
    r['items'] = []
    for m in re.finditer(r'(?m)^(\S+) (.+)\n.*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) \w{3} ([\d,.]+) \w{3} ([\d,.]+)$', t):
        r['items'].append(dict(item=m.group(1), hs=m.group(3), qty=m.group(4).replace(',', ''), price=m.group(5), amt=m.group(6)))
    r['ctns'] = {}
    for m in re.finditer(r'(?m)^(\d+-\d+|\d+) (\S+) (\d+) (\d+) ([\d,]+) [\d,.]+ \S+ [\d.]+$', t):
        r['ctns'][m.group(2)] = m.group(3)
    r['sup'] = PREFIX[re.search(r'CI-PL_([A-Z]+)', f).group(1)]
    tot = re.search(r'TOTAL: (\d+) CTNS', t)
    if sum(int(v) for v in r['ctns'].values()) != int(tot.group(1)): note('PL carton total mismatch', f)
    if len(r['ctns']) != len(r['items']): note('CI/PL row count differs', f, len(r['items']), len(r['ctns']))
    return r
CI = []
for f in sorted(pdfs):
    if f.startswith('CI-PL_'):
        r = parse_ci(f); r['file'] = f; r['hash'] = pdfs[f]
        CI.append(r)
        EV.append(dict(ts=day(r['date']), kind='ci', doc=(r['hash'], 'supplier_docs/' + f), d=r))

QCS = []
for f in sorted(pdfs):
    if f.startswith('LCI-'):
        t = open(D + f + '.txt').read()
        r = dict(no=re.search(r'Report No\.: (\S+)', t).group(1), date=re.search(r'Inspection date: (\S+)', t).group(1),
                 po=re.search(r'PO No\.: (\S+)', t).group(1), res=re.search(r'Overall result: (\w+)', t).group(1),
                 size=re.search(r'sample size (\d+)', t).group(1), agency=t.split('\n')[0].title(), file=f, hash=pdfs[f])
        QCS.append(r)
        EV.append(dict(ts=day(r['date']), kind='qc', doc=(r['hash'], 'supplier_docs/' + f), d=r))

# ---------------- emails ----------------
def po_ref(ref, ctx_ts, sup_codes):
    """resolve a PO reference; returns (po_number, exact)"""
    m = re.fullmatch(r'PO-(\d{4})-(\d{4})', ref)
    if m: return ref, True
    m = re.fullmatch(r'PO#(\d{4})-(\d{4})', ref)
    if m: return f'PO-{m.group(1)}-{m.group(2)}', False
    n = int(re.sub(r'\D', '', ref))
    cands = [p for p in set(PI) | STORE_POS if int(p[-4:]) == n and (p not in PI or PI[p]['sup'] in sup_codes)]
    cands = [p for p in cands if p in PI and day(PI[p]['date']) <= ctx_ts]
    if len(cands) == 1: return cands[0], False
    note('PO REF AMBIGUOUS', ref, cands); return None, False
SUPNAME = {'Dongguan Ruifeng': 'DGRF', 'Foshan Mingjia': 'FSMJ', 'Hangzhou Tianyi': 'HZTY', 'Ningbo Mingtu': 'NBBW', 'Ningbo Qisheng': 'NBQS', 'Shenzhen Hetai': 'SZHT', 'Xiamen Yuanda': 'XMYD', 'Yiwu Lanxin': 'YWLX'}
BOOK = {}; PREALERT = []; OTHER = []
for m in msgs:
    s, b = m['subj'], m['body']; ts = utc(pdt(m['date']))
    doc = (m['hash'], 'mid:' + m['mid']); g = lambda k: re.search(k + r': (.*)', b).group(1)
    local_date = pdt(m['date']).date()
    if s.startswith('Booking Confirmation'):
        so = g('SO'); eq = g('Equipment')
        mode = 'LCL' if eq.startswith('LCL') else re.search(r'1x(\w+)', eq).group(1)
        sups = {c for n, c in SUPNAME.items() if n in g(r'Shipper\(s\)')}
        refs = [r.strip() for r in g('POs').split(',')]
        pos = [po_ref(r, ts, sups) for r in refs]
        d = dict(so=so, mode=mode, vessel=g('Vessel/Voyage'), pol=re.search(r'POL: .*?\((\w+)\)', b).group(1), pod=re.search(r'POD: .*?\((\w+)\)', b).group(1),
                 etd=pdate(g('ETD')), eta=pdate(g('ETA')), pos=pos, refs=refs, sups=sups)
        BOOK[so] = d
        EV.append(dict(ts=ts, kind='booking', doc=doc, d=d))
    elif 'ROLLED' in s:
        so = re.search(r'SO (\w+)', s).group(1)
        mm = re.search(r'New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})', b)
        EV.append(dict(ts=ts, kind='rolled', doc=doc, d=dict(so=so, etd=pdate(mm.group(1)), eta=pdate(mm.group(2)))))
    elif s.startswith('Shipping Advice'):
        hbl = g('HBL'); cs = g(r'Container/Seal').split(' / ')[0]
        rows = [dict(po=a, item=i, ctns=c, pcs=p) for a, i, c, p in re.findall(r'(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs', b)]
        d = dict(hbl=hbl, container=cs, vessel=g('Vessel/Voyage'), atd=pdate(re.search(r'ATD [^:]*: (.*)', b).group(1)),
                 eta=pdate(re.search(r'ETA [^:]*: (.*)', b).group(1)), rows=rows)
        pk = re.search(r'Packages: (\d+) CTNS', b)
        if sum(int(r['ctns']) for r in rows) != int(pk.group(1)): note('pre-alert carton total mismatch', hbl)
        PREALERT.append(d); EV.append(dict(ts=ts, kind='prealert', doc=doc, d=d))
    elif s.startswith('ETA update'):
        EV.append(dict(ts=ts, kind='etaupd', doc=doc, d=dict(hbl=re.search(r'HBL (\w+)', s).group(1), eta=pdate(re.search(r'revised ETA (\d+ \w+ \d{4})', b).group(1)))))
    elif s.startswith('Arrival Notice'):
        mm = re.search(r'HBL (\w+) \((\w+)\) .* arriving .* on (\d+ \w+ \d{4})', b)
        EV.append(dict(ts=ts, kind='arrival', doc=doc, d=dict(hbl=mm.group(1), cont=mm.group(2), date=pdate(mm.group(3)))))
    elif s.startswith('Receipt complete'):
        mm = re.search(r'Receiving complete for (\w+) under (\S+)', b)
        extra = [l for l in b.split('\n') if re.search(r'complet|received on|at \d', l) and 'Receiving complete' not in l and 'expected' not in l]
        if extra: note('RECEIPT EMAIL has time text', m['mid'], extra)
        EV.append(dict(ts=ts, kind='receipt', doc=doc, d=dict(key=mm.group(1), rcv=mm.group(2), at=pdt(m['date']).isoformat())))
    elif s.startswith('Entry Summary'):
        def amt(k): return Decimal(re.search(k + r': USD ([\d,.]+)', b).group(1).replace(',', ''))
        mm = re.search(r'Entry (\S+) filed for (\w+)', b)
        d = dict(entry=mm.group(1), key=mm.group(2), filed=local_date.isoformat(), value=amt('Entered value'),
                 duty=amt(r'Duty \(HTS\)') + amt('Section 301') + amt('Additional duties'), fees=amt('MPF') + amt('HMF'), total=amt('Total duties and fees'))
        if d['duty'] + d['fees'] != d['total']: note('CUSTOMS total != duty+fees', d['entry'], d['duty'] + d['fees'], d['total'])
        EV.append(dict(ts=ts, kind='customs', doc=doc, d=d))
    else:
        note('UNHANDLED EMAIL', s)

# link pre-alerts to bookings (vessel/voyage + PO overlap)
HBL2SO = {}; SO2HBL = {}; BOOK_LOOSE = {}
for pa in PREALERT:
    pos = {r['po'] for r in pa['rows']}
    c = [b for b in BOOK.values() if b['vessel'] == pa['vessel'] and pos & {p for p, _ in b['pos'] if p}]
    if len(c) != 1: note('PRE-ALERT LINK PROBLEM', pa['hbl'], [b['so'] for b in c]); continue
    b = c[0]
    HBL2SO[pa['hbl']] = b['so']; SO2HBL.setdefault(b['so'], []).append(pa['hbl'])
    exact = all(ex for p, ex in b['pos'] if p in pos)
    BOOK_LOOSE[pa['hbl']] = not exact
    if pos != {p for p, _ in b['pos']}: note('booking POs vs pre-alert POs differ', b['so'], pa['hbl'], sorted(p for p, _ in b['pos']), sorted(pos))
    if pa['container'] != 'LCL' and b['mode'] == 'LCL' or pa['container'] == 'LCL' and b['mode'] != 'LCL': note('mode/container mismatch', b['so'], pa['hbl'])
for so, h in SO2HBL.items():
    if len(h) > 1: note('BOOKING WITH SEVERAL HBLs', so, h)
for so in BOOK:
    if so not in SO2HBL: note('booking without pre-alert', so, BOOK[so]['etd'])
CONT2SO = {}
for pa in PREALERT:
    if pa['container'] != 'LCL' and pa['hbl'] in HBL2SO: CONT2SO[pa['container']] = HBL2SO[pa['hbl']]

# ---------------- chats ----------------
def next_date(mo, d, after_cn):
    y = after_cn.year
    for yy in (y, y + 1):
        try: c = dt.date(yy, mo, d)
        except ValueError: continue
        if c >= after_cn: return c
CH_NOTES = []
pending = {}
for name, sup in CHATS.items():
    raw = open(f'{EXP}/wechat/{name}.txt', encoding='utf-8').read()
    blocks = [b for b in raw.split('\n\n')[1:] if b.strip()]
    pending_dep = None
    for n, blk in enumerate(blocks, 1):
        lines = blk.split('\n'); hdr, txt = lines[0], '\n'.join(lines[1:])
        mm = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$', hdr)
        ts = dt.datetime.strptime(mm.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY).astimezone(UTC)
        who = 'M' if 'Maya' in mm.group(2) else 'S'
        h = hashlib.sha256(blk.encode('utf-8')).hexdigest()   # message lines exactly as exported, no trailing blank line
        doc = (h, f'wechat/{name}.txt#{n}')
        cn_date = ts.astimezone(CN).date()
        if txt.startswith('['): continue
        # supplier-side ETD statements
        m1 = re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', txt)
        m2 = re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', txt)
        m3 = re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货', txt)
        m4 = re.fullmatch(r'(?:ETD (\d+)/(\d+)|交期(\d+)月(\d+)号左右(?:，ETD around \d+/\d+)?)', txt)
        if who == 'S' and (m1 or m2 or m3):
            if m3:
                pi = PI_BY_NO.get(m3.group(1)); po = pi['po'] if pi else None; conf = '0.85'; mo, dd = int(m3.group(2)), int(m3.group(3))
                if not po: note('chat PI no unknown', name, n, m3.group(1)); continue
            else:
                mm_ = m1 or m2; po = mm_.group(1); conf = '0.9'; mo, dd = int(mm_.group(2)), int(mm_.group(3))
            d = next_date(mo, dd, cn_date)
            EV.append(dict(ts=ts, kind='chat_etd', doc=doc, d=dict(po=po, etd=d, conf=conf, sup=sup, raw=txt)))
        elif who == 'S' and m4:
            g_ = [int(x) for x in m4.groups() if x]
            d = next_date(g_[0], g_[1], cn_date)
            # compare with the supplier's latest PI at that time
            pis = [p for p in PI.values() if p['sup'] == sup and day(p['date']) <= ts + dt.timedelta(hours=13)]
            pi = max(pis, key=lambda p: p['date'])
            if pi['etd_date'] != d: note('CHAT ETD DIFFERS FROM PI', name, n, d, pi['pi'], pi['etd_date'])
            CH_NOTES.append(('etd-same-as-pi', name, n))
        elif who == 'S' and re.search(r'[A-Z]{4}\d{7}', txt) and re.search(r'[Cc]ontainer', txt):
            cont = re.search(r'([A-Z]{4}\d{7})', txt).group(1)
            EV.append(dict(ts=ts, kind='chat_container', doc=doc, d=dict(container=cont, sup=sup)))
        elif who == 'M' and re.search(r'[Dd]eposit', txt):
            amt = re.search(r'(USD|CNY) ([\d,]+\.\d\d)', txt); po = re.search(r'(PO-\d{4}-\d{4})', txt)
            pending_dep = dict(po=po.group(1) if po else None, amt=Decimal(amt.group(2).replace(',', '')), cur=amt.group(1), ts=ts, n=n)
        elif who == 'S' and txt in ('Received, thank you', '收到，谢谢', '定金收到了，马上安排生产'):
            if pending_dep:
                EV.append(dict(ts=ts, kind='chat_ack', doc=doc, d=dict(sup=sup, dep=pending_dep, raw=txt)))
                pending_dep = None
        elif who == 'S' and txt == '大货生产中':
            EV.append(dict(ts=ts, kind='chat_prod', doc=doc, d=dict(sup=sup)))

EV.sort(key=lambda e: e['ts'])
