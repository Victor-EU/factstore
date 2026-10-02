import re, sys, json, glob, os, hashlib, collections, mailbox, datetime as dt
from zoneinfo import ZoneInfo
import factstore

ROOT = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-e-o67pidv7/ingest/work/exports'
S = os.path.dirname(os.path.abspath(__file__))
DRY = '--write' not in sys.argv
NY = ZoneInfo('America/New_York'); LA = ZoneInfo('America/Los_Angeles'); CN = ZoneInfo('Asia/Shanghai')
MON = {m: i + 1 for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}
PORT = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Xiamen': 'CNXMN', 'Nansha': 'CNNSA'}
PFX = {'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'MT': 'NBBW', 'QS': 'NBQS', 'RF': 'DGRF', 'TY': 'HZTY', 'YD': 'XMYD'}
RANK = {s: i for i, s in enumerate('draft sent confirmed in_production ready shipped received'.split())}
TZ_DEST = {'USNYC': NY, 'USLAX': LA}
DEST_NAME = {'New York/Newark': 'USNYC', 'Los Angeles': 'USLAX'}

def sha(b): return hashlib.sha256(b).hexdigest()
def iso(d): return d.isoformat()
def num(s): return s.replace(',', '')

# ---------------------------------------------------------------- documents
docs = []   # dicts: kind, url, hash, at, data

def add(kind, url, h, at, **data):
    docs.append(dict(kind=kind, url=url, hash=h, at=at, **data))

# PDFs
for f in sorted(glob.glob(ROOT + '/supplier_docs/*.pdf')):
    name = os.path.basename(f)
    t = open(f'{S}/txt/{name}.txt').read()
    h = sha(open(f, 'rb').read())
    url = 'supplier_docs/' + name
    if name.startswith('LCI-'):
        d = re.search(r'Inspection date: (\S+)', t).group(1)
        add('qc', url, h, dt.datetime.fromisoformat(d).replace(tzinfo=CN), t=t, file=name)
    elif name.startswith('CI-PL_'):
        d = re.search(r'Invoice No\.: \S+\s+Date: (\S+)', t).group(1)
        add('ci', url, h, dt.datetime.fromisoformat(d).replace(tzinfo=CN), t=t, file=name)
    else:
        d = re.search(r'Date: (\d{4}-\d\d-\d\d)', t).group(1)
        add('pi', url, h, dt.datetime.fromisoformat(d).replace(tzinfo=CN), t=t, file=name)

# emails
raw = open(ROOT + '/email/ops_inbox.mbox', 'rb').read()
parts = re.split(rb'\n\n(?=From \S+ \w{3} \w{3} \d\d \d\d:\d\d:\d\d \d{4}\n)', raw)
import email as emaillib
from email import policy
for p in parts:
    p = p.rstrip(b'\n') + b'\n'
    assert p.startswith(b'From ')
    msg = emaillib.message_from_bytes(p.split(b'\n', 1)[1], policy=policy.default)
    mid = msg['Message-ID'].strip('<>')
    at = emaillib.utils.parsedate_to_datetime(msg['Date'])
    body = msg.get_content()
    add('email', 'mid:' + mid, sha(p), at, subject=msg['Subject'], body=body, sender=msg['From'])

# chats
CHAT_SUP = {}
for f in sorted(glob.glob(ROOT + '/wechat/*.txt')):
    name = os.path.basename(f)
    code = name.split('_')[0]
    lines = open(f, encoding='utf-8').read().split('\n')
    msgs = []; cur = None
    for ln in lines:
        m = re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$', ln)
        if m and (cur is None or cur['closed']):
            cur = dict(ts=m.group(1), sender=m.group(2), lines=[ln], closed=False); msgs.append(cur)
        elif ln.strip() == '':
            if cur: cur['closed'] = True
        elif cur and not cur['closed']:
            cur['lines'].append(ln)
    for i, m in enumerate(msgs, 1):
        text = '\n'.join(m['lines'][1:])
        raw_m = '\n'.join(m['lines']).encode('utf-8')
        at = dt.datetime.strptime(m['ts'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
        add('chat', f'wechat/{name}#{i}', sha(raw_m), at, text=text, sender=m['sender'], code=code, n=i)

docs.sort(key=lambda d: (d['at'].astimezone(dt.timezone.utc), {'pi': 0, 'qc': 1, 'ci': 2}.get(d['kind'], 3)))

# ---------------------------------------------------------------- store state
def q(sql): return factstore.query(sql).rows
ITEM = {c: (sku, hs) for c, sku, hs in q('select c.v, s.v, h.v from "factory/item_code" c join "sku/code" s using(e) join "sku/hs_code" h using(e)')}
KNOWN_PO = {r[0] for r in q('select v from "po/number"')}
# documents already read: backing facts of the kinds this skill writes
READ = {r[0] for r in q("""select distinct h.v from facts f join "core/evidence" ev on ev.e = f.tx join "document/hash" h on h.e = ev.v
  where f.a in ('po/pi_number','shipment_line/quantity','qc/result','customs/entered_value','shipment/status','po/placed_on','po/etd')""")}

# ---------------------------------------------------------------- PI parsing
PIS = {}       # pi file -> parsed
PO_LINES = collections.defaultdict(dict)   # po -> {item code (with sup prefix): line no}
PO_QTY = collections.defaultdict(dict)     # po -> {line key: qty}
PO_SUP = {}
PI_PO = {}     # pi number -> po
PO_ETD = {}

def parse_pi(d):
    t = d['t']; L = t.split('\n')
    pi_no = re.search(r'PI No\.: (\S+)', t).group(1)
    po = re.search(r'Your PO: (PO-\d{4}-\d{4})', t).group(1)
    sup = PFX[d['file'].split('-')[0].split('_')[0][:2]] if not d['file'].startswith('RF-') else 'DGRF'
    name_en = re.search(r'Beneficiary: (.+)', t).group(1).strip()
    rows = []
    for i, ln in enumerate(L):
        m = re.match(r'^([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$', ln)
        if m:
            code = L[i - 2].split(' ')[0]
            rows.append((code, int(num(m.group(1))), m.group(3), num(m.group(4))))
    term = re.search(r'Price term: (.+)', t).group(1).strip()
    pay = re.search(r'Payment: (.+)', t).group(1).strip()
    etd = re.search(r'Delivery: about (\w{3}) (\d+), (\d{4})', t)
    etd = dt.date(int(etd.group(3)), MON[etd.group(1)], int(etd.group(2)))
    cur = {'USD': 'USD', 'RMB': 'CNY'}[rows[0][2]]
    return dict(pi=pi_no, po=po, sup=sup, name_en=name_en, name_cn=L[0].strip(), addr=L[2].strip(), rows=rows, term=term,
                pay=pay, etd=etd, cur=cur, port=PORT[term.split()[-1]])

# ---------------------------------------------------------------- state & output
TX = []   # (doc, conf, facts, note)
REPORT = collections.defaultdict(list)
CNT = collections.Counter()
PO_STATUS = {}
SHIPS = []   # in-memory shipments
POS_ALL = set(KNOWN_PO)
for d in docs:
    for m in re.findall(r'PO-\d{4}-\d{4}', d.get('t', '') + d.get('text', '') + d.get('body', '')):
        POS_ALL.add(m)
SUFFIX = {}
for p in POS_ALL: SUFFIX.setdefault(int(p[-4:]), set()).add(p)

def emit(d, conf, facts, note=''):
    h = d['hash']
    pre = [{'e': ['document/hash', h], 'a': 'document/url', 'v': d['url']},
           {'e': ['document/hash', h], 'a': 'document/issued_at', 'v': iso(d['at'])},
           {'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', h]},
           {'e': 'tmp:tx', 'a': 'core/confidence', 'v': str(conf)}]
    TX.append((d, conf, pre + facts, note))

def A(e, a, v): return {'e': e, 'a': a, 'v': v}
def PO(n): return ['po/number', n]

def set_status(d, po, st, conf=1, note=''):
    if RANK[st] > RANK.get(PO_STATUS.get(po, 'draft'), -1) or po not in PO_STATUS:
        if po in PO_STATUS and RANK[st] <= RANK[PO_STATUS[po]]: return
        PO_STATUS[po] = st
        emit(d, conf, [A(PO(po), 'po/status', st)], note or f'status {st}')

def handle_pi(d):
    p = parse_pi(d); PIS[d['file']] = p; po = p['po']
    PI_PO[p['pi']] = po; PO_SUP[po] = p['sup']; PO_ETD[po] = p['etd']
    sup = ['supplier/code', p['sup']]
    f = [A(sup, 'supplier/name', p['name_en']), A(sup, 'supplier/name_cn', p['name_cn']), A(sup, 'supplier/address', p['addr']),
         A(sup, 'supplier/incoterm', p['term']), A(sup, 'supplier/payment_terms', p['pay']), A(sup, 'supplier/currency', p['cur']),
         A(sup, 'supplier/port', p['port']),
         A(PO(po), 'po/pi_number', p['pi']), A(PO(po), 'po/supplier', sup), A(PO(po), 'po/etd', p['etd'].isoformat()),
         A(PO(po), 'core/currency', p['cur'])]
    for code, qty, cur, price in p['rows']:
        key = f"{p['sup']}:{code}"
        if key not in ITEM:
            REPORT['unresolved'].append(f"{d['url']}: item code {key} has no SKU"); continue
        n = PO_LINES[po].get(key)
        if n is None:
            n = len(PO_LINES[po]) + 1; PO_LINES[po][key] = n
        lk = f'{po}/{n}'; PO_QTY[po][lk] = qty
        f += [A(['po_line/key', lk], 'core/part_of', PO(po)), A(['po_line/key', lk], 'po_line/sku', ['factory/item_code', key]),
              A(['po_line/key', lk], 'po_line/quantity', str(qty)), A(['po_line/key', lk], 'po_line/unit_price', price)]
    f.append(A(PO(po), 'po/status', 'confirmed'))
    # status: only forward
    if RANK['confirmed'] <= RANK.get(PO_STATUS.get(po, 'draft'), 0) and po in PO_STATUS and PO_STATUS[po] != 'sent':
        f.pop()
    else:
        PO_STATUS[po] = 'confirmed'
    emit(d, 1, f, 'PI')
    CNT['po touched'] += 0

# ---------------------------------------------------------------- shipments
class Ship:
    def __init__(s, **k):
        s.booking = None; s.hbl = None; s.container = None; s.vessel = None; s.pos = set(); s.dest = None
        s.lines = {}; s.status = None; s.delivered = False; s.sailed = False; s.atd = None
        s.__dict__.update(k)
    @property
    def key(s):
        return ['shipment/booking_no', s.booking] if s.booking else ['shipment/hbl', s.hbl]

def find_hbl(h):
    for s in SHIPS:
        if s.hbl == h: return s

def canon_po(txt):
    out = []
    for m in re.finditer(r'(?i)\bPO[#\s-]*(?:(\d{4})-)?(\d+)', txt):
        yr, n = m.group(1), int(m.group(2))
        canonical = bool(re.fullmatch(r'PO-\d{4}-\d{4}', m.group(0)))
        cands = SUFFIX.get(n, set())
        if yr: cands = {c for c in cands if c.startswith(f'PO-{yr}-')}
        if len(cands) == 1: out.append((next(iter(cands)), canonical))
        else: REPORT['unresolved'].append(f'PO reference {m.group(0)!r} matches {sorted(cands)}')
    return out

def find_for_hbl(h, vessel, pos):
    s = find_hbl(h)
    if s: return s, 1
    for s in SHIPS:
        if s.hbl is None and s.vessel == vessel and s.pos & set(pos):
            return s, 0.9
    return None, 1

def local_midnight(date, tz): return dt.datetime.combine(date, dt.time(0), tzinfo=tz)
def pdate(s):
    m = re.match(r'(\d+) (\w{3}) (\d{4})', s); return dt.date(int(m.group(3)), MON[m.group(2)], int(m.group(1)))

def sum_shipped(po):
    tot = collections.Counter()
    for s in SHIPS:
        for lk, qty in s.lines.items():
            if lk.rsplit('/', 1)[0].endswith(po) or lk.startswith(po + '/') or ('/' + po + '/') in '/' + lk:
                pass
    return tot

def line_qty(po):
    tot = collections.Counter()
    for s in SHIPS:
        for lk, qty in s.lines.items():
            m = re.match(r'(PO-\d{4}-\d{4})/(\d+)$', lk)
            if m and m.group(1) == po: tot[lk] += qty
    return tot

def update_po_shipped(d, atd_date=None):
    pos = set()
    for s in SHIPS:
        for lk in s.lines: pos.add(lk.split('/')[0])
    for po in sorted(pos):
        if PO_STATUS.get(po) in ('shipped', 'received'):
            # new departure on a PO already shipped -> actual date is the latest departure
            continue
        if po not in PO_QTY: continue
        carrying = [s for s in SHIPS if po in s.pos or any(lk.startswith(po + '/') for lk in s.lines)]
        ok1 = bool(carrying) and all(s.hbl for s in carrying)
        tot = line_qty(po)
        ok2 = all(tot[lk] >= qty for lk, qty in PO_QTY[po].items())
        if (ok1 or ok2) and (ok2 or ok1):
            if ok1 and not ok2 and not all(tot[lk] >= qty for lk, qty in PO_QTY[po].items()):
                # sailed bookings but short quantity: only trust bookings if each sailed shipment has lines
                if not all(s.lines for s in carrying): continue
            f = []
            if atd_date: f.append(A(PO(po), 'po/etd', atd_date.isoformat()))
            else:
                # CI before pre-alert: departure date unknown yet
                pass
            f.append(A(PO(po), 'po/status', 'shipped'))
            PO_STATUS[po] = 'shipped'
            emit(d, 1, f, 'PO shipped')

def ship_lines(d, s, rows, conf=1):
    """rows: (po, item code or None, cartons, qty)"""
    f = []
    for po, code, ctns, qty in rows:
        key = f'{PO_SUP.get(po)}:{code}'
        n = PO_LINES.get(po, {}).get(key)
        if n is None:
            REPORT['unresolved'].append(f"{d['url']}: no PO line for {po} item {code}"); continue
        lk = f'{po}/{n}'; sl = ['shipment_line/key', f'{s.hbl}/{lk}']
        s.lines[lk] = s.lines.get(lk, 0) + 0 if False else qty
        s.pos.add(po)
        f += [A(sl, 'core/part_of', s.key), A(sl, 'shipment_line/po_line', ['po_line/key', lk]),
              A(sl, 'shipment_line/quantity', str(qty))]
        if ctns is not None: f.append(A(sl, 'shipment_line/cartons', str(ctns)))
    return f

def handle_ci(d):
    t = d['t']
    po = re.search(r'Order: (PO-\d{4}-\d{4})', t).group(1)
    m = re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)', t)
    org, dst, vessel, cont, hbl = m.groups()
    L = t.split('\n')
    inv = {}
    for i, ln in enumerate(L):
        r = re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ', ln)
        if r: inv[L[i - 2].split(' ')[0]] = (r.group(1), int(num(r.group(2))))
    cart = {}
    for ln in L:
        r = re.match(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) ', ln)
        if r and r.group(1) in inv: cart[r.group(1)] = int(r.group(2))
    s, conf = find_for_hbl(hbl, vessel, [po])
    if s is None:
        s = Ship(hbl=hbl); SHIPS.append(s)
    elif s.hbl is None:
        s.hbl = hbl
    fl = []
    s.vessel = s.vessel or vessel; s.dest = s.dest or dst
    s.pos.add(po)
    head = [A(s.key, 'shipment/vessel', vessel), A(s.key, 'shipment/origin', org), A(s.key, 'shipment/destination', dst)]
    if cont != 'LCL':
        head.append(A(s.key, 'shipment/container_no', cont)); s.container = cont
    rows = [(po, c, cart.get(c), q) for c, (hs, q) in inv.items()]
    lines = ship_lines(d, s, rows)
    if conf < 1:   # found by vessel + PO, not by an identifier: record the link on its own
        emit(d, conf, [A(s.key, 'shipment/hbl', hbl)], 'HBL linked to booking by vessel/voyage + PO')
    emit(d, 1, head + lines, 'CI/PL')
    # HS codes
    for c, (hs, q) in inv.items():
        key = f'{PO_SUP[po]}:{c}'
        if key in ITEM and ITEM[key][1] != hs:
            REPORT['hs'].append(f"{d['url']}: {key} HS {hs} on invoice vs {ITEM[key][1]} on SKU {ITEM[key][0]} (not overwritten)")
    s.sailed = True
    update_po_shipped(d)

# ---------------------------------------------------------------- QC
INSPECTOR = {'LINKCHECK INSPECTION SERVICES': 'LinkCheck Inspection Services'}
def handle_qc(d):
    t = d['t']
    g = lambda p: re.search(p, t).group(1)
    rep = g(r'Report No\.: (\S+)'); po = g(r'PO No\.: (PO-\d{4}-\d{4})')
    res = g(r'Overall result: (PASS|FAIL)'); size = g(r'sample size (\d+)')
    ins = INSPECTOR[t.split('\n')[0].strip()]
    r = ['qc/report_no', rep]
    emit(d, 1, [A(r, 'qc/po', PO(po)), A(r, 'qc/inspected_on', g(r'Inspection date: (\S+)')), A(r, 'qc/result', res),
                A(r, 'qc/inspector', ins), A(r, 'qc/sample_size', size)], 'inspection')
    if res == 'PASS': set_status(d, po, 'ready')

# ---------------------------------------------------------------- emails
def handle_email(d):
    s_, b = d['subject'], d['body']; at = d['at']
    if s_.startswith('Booking Confirmation') or s_.startswith('RE: Booking Confirmation'):
        if 'ROLLED' in s_:
            so = re.search(r'SO (\w+)', s_).group(1)
            m = re.search(r'New ETD (.+?) ETA (.+?)\.', b)
            sh = next(x for x in SHIPS if x.booking == so)
            etd = local_midnight(pdate(m.group(1)), CN); eta = local_midnight(pdate(m.group(2)), TZ_DEST[sh.dest])
            emit(d, 1, [A(sh.key, 'shipment/etd', iso(etd)), A(sh.key, 'shipment/eta', iso(eta))], 'rolled')
            return
        g = lambda p: re.search(p, b).group(1)
        so = g(r'SO: (\w+)'); eq = g(r'Equipment: (.+)')
        mode = 'LCL' if eq.startswith('LCL') else re.search(r'\dx(\w+)', eq).group(1)
        pol, pod = re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)', b).groups()
        vessel = g(r'Vessel/Voyage: (.+)')
        etd = local_midnight(pdate(g(r'ETD: (.+)')), CN); eta = local_midnight(pdate(g(r'ETA: (.+)')), TZ_DEST[pod])
        pos = canon_po(g(r'POs: (.+)'))
        sh = Ship(booking=so, vessel=vessel, dest=pod, status='booked'); SHIPS.append(sh)
        sh.pos = {p for p, c in pos}
        k = sh.key
        emit(d, 1, [A(k, 'shipment/mode', mode), A(k, 'shipment/vessel', vessel), A(k, 'shipment/origin', pol),
                    A(k, 'shipment/destination', pod), A(k, 'shipment/etd', iso(etd)), A(k, 'shipment/eta', iso(eta)),
                    A(k, 'shipment/status', 'booked')], 'booking')
        if any(not c for p, c in pos):
            REPORT['loose'].append(f"{d['url']}: PO written loosely in booking ({g(r'POs: (.+)')}), used only to match the shipment")
    elif s_.startswith('Shipping Advice'):
        g = lambda p: re.search(p, b).group(1)
        hbl = g(r'HBL: (\w+)'); cs = g(r'Container/Seal: (\S+)'); vessel = g(r'Vessel/Voyage: (.+)')
        m = re.search(r'ATD (\w+): (.+)', b); atd = pdate(m.group(2))
        em = re.search(r'ETA (.+?): (\d+ \w{3} \d{4})', b)
        dest = DEST_NAME[em.group(1)]
        rows = []
        for ln in b.split('\n'):
            r = re.match(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs', ln)
            if r: rows.append((r.group(1), r.group(2), int(r.group(3)), int(r.group(4))))
        pos = [r[0] for r in rows]
        sh, conf = find_for_hbl(hbl, vessel, pos)
        if sh is None:
            sh = Ship(hbl=hbl, vessel=vessel, dest=dest); SHIPS.append(sh)
        elif sh.hbl is None:
            sh.hbl = hbl
        sh.dest = sh.dest or dest; sh.vessel = sh.vessel or vessel
        if conf < 1: emit(d, conf, [A(sh.key, 'shipment/hbl', hbl)], 'HBL linked to booking by vessel/voyage + POs')
        k = sh.key
        etd = local_midnight(atd, CN); eta = local_midnight(pdate(em.group(2)), TZ_DEST[dest])
        f = [A(k, 'shipment/etd', iso(etd)), A(k, 'shipment/eta', iso(eta)), A(k, 'shipment/status', 'departed')]
        if cs != 'LCL':
            f.append(A(k, 'shipment/container_no', cs)); sh.container = cs
        f += ship_lines(d, sh, rows)
        sh.atd = atd; sh.sailed = True; sh.status = 'departed'
        emit(d, 1, f, 'pre-alert')
        update_po_shipped(d, atd)
        # PO already shipped (CI first): record the actual departure
        for po in set(pos):
            if PO_STATUS.get(po) in ('shipped', 'received') and not any(po in tx[2][i:=4]['v'] if False else False for tx in []):
                pass
        for po in sorted(set(pos)):
            if PO_STATUS.get(po) == 'shipped' and PO_ETD.get(po) != atd:
                PO_ETD[po] = atd
                emit(d, 1, [A(PO(po), 'po/etd', atd.isoformat())], 'actual departure')
    elif s_.startswith('ETA update'):
        hbl = re.search(r'HBL (\w+)', s_).group(1)
        sh = find_hbl(hbl)
        if not sh: REPORT['unresolved'].append(f"{d['url']}: ETA update for unknown HBL {hbl}"); return
        eta = local_midnight(pdate(re.search(r'revised ETA (\d+ \w{3} \d{4})', b).group(1)), TZ_DEST[sh.dest])
        emit(d, 1, [A(sh.key, 'shipment/eta', iso(eta))], 'ETA update')
    elif s_.startswith('Arrival Notice'):
        hbl = re.search(r'HBL (\w+)', s_).group(1); sh = find_hbl(hbl)
        m = re.search(r'arriving (.+?) on (\d+ \w{3} \d{4})', b)
        if not sh: REPORT['unresolved'].append(f"{d['url']}: arrival for unknown HBL {hbl}"); return
        eta = local_midnight(pdate(m.group(2)), TZ_DEST[DEST_NAME[m.group(1)]])
        emit(d, 1, [A(sh.key, 'shipment/status', 'arrived'), A(sh.key, 'shipment/eta', iso(eta))], 'arrival')
    elif s_.startswith('Receipt complete'):
        m = re.search(r'Receiving complete for (\S+) under (\S+)', b); ident = m.group(1)
        cands = [x for x in SHIPS if (x.container == ident or x.hbl == ident) and not x.delivered]
        if not cands: REPORT['unresolved'].append(f"{d['url']}: receipt for {ident} matches no open shipment"); return
        sh = cands[0] if len(cands) == 1 else min(cands, key=lambda x: x.atd or dt.date.max)
        if len(cands) > 1: REPORT['loose'].append(f"{d['url']}: {ident} matched {len(cands)} open shipments, took earliest departure")
        sh.delivered = True
        emit(d, 1, [A(sh.key, 'shipment/status', 'delivered'), A(sh.key, 'shipment/delivered_at', iso(at))], 'delivered')
        disc = [ln.strip() for ln in b.split('\n') if 'expected' in ln and re.search(r'damaged [1-9]|received (\d+) damaged', ln)]
        bad = []
        for ln in b.split('\n'):
            r = re.search(r'expected (\d+),? received (\d+),? damaged (\d+)', ln)
            if r and (r.group(1) != r.group(2) or r.group(3) != '0'): bad.append(ln.strip())
        if bad: REPORT['warehouse'].append(f"{ident} ({d['url']}): " + '; '.join(bad))
        # PO received
        for po in sorted({lk.split('/')[0] for lk in sh.lines}):
            carrying = [x for x in SHIPS if any(lk.startswith(po + '/') for lk in x.lines)]
            if all(x.delivered for x in carrying) and PO_STATUS.get(po) == 'shipped':
                PO_STATUS[po] = 'received'; emit(d, 1, [A(PO(po), 'po/status', 'received')], 'PO received')
    elif s_.startswith('Entry Summary'):
        g = lambda p: float(num(re.search(p, b).group(1)))
        no = re.search(r'Entry (\S+) filed for (\S+)\.', b); entry, ident = no.groups()
        sh = find_hbl(ident) or next((x for x in reversed(SHIPS) if x.container == ident and x.hbl), None)
        if not sh: REPORT['unresolved'].append(f"{d['url']}: entry {entry} for {ident} matches no shipment"); return
        val = num(re.search(r'Entered value: USD ([\d,.]+)', b).group(1))
        duty = sum(float(num(re.search(p + r': USD ([\d,.]+)', b).group(1))) for p in ['Duty \\(HTS\\)', 'Section 301', 'Additional duties'])
        fees = sum(float(num(re.search(p + r': USD ([\d,.]+)', b).group(1))) for p in ['MPF', 'HMF'])
        e = ['customs/entry_no', entry]
        emit(d, 1, [A(e, 'customs/shipment', sh.key), A(e, 'customs/filed_on', at.date().isoformat()),
                    A(e, 'customs/entered_value', val), A(e, 'customs/duty', f'{duty:.2f}'), A(e, 'customs/fees', f'{fees:.2f}'),
                    A(e, 'core/currency', 'USD')], 'customs')
    else:
        REPORT['unresolved'].append(f"{d['url']}: unrecognised email {s_}")

# ---------------------------------------------------------------- chats
CH = collections.defaultdict(lambda: dict(cur=None, pay=None))
def next_md(m_, d_, after):
    for y in (after.year, after.year + 1):
        try: c = dt.date(y, m_, d_)
        except ValueError: continue
        if c > after.date(): return c

def handle_chat(d):
    st = CH[d['code']]; t = d['text'].strip(); at = d['at']; sup = ['supplier/code', d['code']]
    PX = r'(PO-\d{4}-\d{4})'
    m = re.search(r'new PO ' + PX + ' attached', t) or re.search(r'\bPO ' + PX + r' for \d+ items', t) or re.search(r"here's " + PX, t)
    if m:
        po = m.group(1); st['cur'] = po
        PO_STATUS_before = PO_STATUS.get(po)
        facts = [A(PO(po), 'po/placed_on', at.date().isoformat()), A(PO(po), 'po/supplier', sup)]
        if po not in PO_STATUS: facts.append(A(PO(po), 'po/status', 'sent')); PO_STATUS[po] = 'sent'
        emit(d, 1, facts, 'PO placed'); return
    m = re.search(r'\[文件\] (\S+)\.pdf', t)
    if m:
        f = m.group(1) + '.pdf'
        if f in PIS: st['cur'] = PIS[f]['po']
        return
    # ETD changes with the PO named by number
    m = re.search(r'ETD for ' + PX + r' will be (\d+)/(\d+)', t) or re.search(PX + r'交期要推迟到(\d+)月(\d+)号', t)
    po = None; conf = 0.9
    if m: po, mo, da = m.group(1), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r'(\S+-PI-\S+|[A-Z]{2}-?\d{6}\S*|\bHT-PI-\d{4}-\d{3}).*预计(\d+)/(\d+)出货', t)
        if m and m.group(1) in PI_PO:
            po, mo, da, conf = PI_PO[m.group(1)], int(m.group(2)), int(m.group(3)), 0.8
    if po:
        date = next_md(mo, da, at)
        emit(d, conf, [A(PO(po), 'po/etd', date.isoformat())], 'ETD change'); PO_ETD[po] = date
        REPORT['lowconf'].append(f"{d['url']}: ETD for {po} -> {date} (year inferred{'; PO from PI number' if conf == 0.8 else ''}), {conf}")
        return
    m = re.fullmatch(r'ETD (?:around )?(\d+)/(\d+)|交期(\d+)月(\d+)号左右(?:，ETD around \d+/\d+)?|ETD (\d+)/(\d+)|交期(\d+)月(\d+)号', t) or re.search(r'ETD (?:around )?(\d+)/(\d+)', t)
    if m:
        g = [x for x in m.groups() if x]; mo, da = int(g[0]), int(g[1]); po = st['cur']
        date = next_md(mo, da, at)
        if PO_ETD.get(po) != date:
            emit(d, 0.8, [A(PO(po), 'po/etd', date.isoformat())], 'ETD after PI differs'); PO_ETD[po] = date
            REPORT['lowconf'].append(f"{d['url']}: ETD for {po} (from context) -> {date}, differs from PI, 0.8")
        else: CNT['bare ETD equal to PI (skipped)'] += 1
        return
    # payments
    m = re.search(r'deposit for ' + PX, t)
    if m: st['pay'] = ['deposit', m.group(1), True, False]; return
    if t.startswith('Deposit paid today'): st['pay'] = ['deposit', st['cur'], False, False]; return
    m = re.search(r'Balance (?:paid )?for ' + PX, t)
    if m: st['pay'] = ['balance', m.group(1), True, False]; return
    if t.startswith('B/L copy') or t.startswith('Goods ready'): return
    # acknowledgements
    ack = t in ('定金收到了，马上安排生产',) or t in ('Received, thank you', '收到，谢谢')
    prod = t == '大货生产中'
    if ack or prod:
        p = st['pay']
        if not p or p[0] != 'deposit' or (ack and p[3]): return
        po = p[1]
        if ack: p[3] = True
        conf = 0.9 if p[2] else 0.8
        if t in ('Received, thank you', '收到，谢谢'): conf = min(conf, 0.8)
        if po and RANK['in_production'] > RANK.get(PO_STATUS.get(po, 'draft'), -1):
            PO_STATUS[po] = 'in_production'
            emit(d, conf, [A(PO(po), 'po/status', 'in_production')], 'production')
            REPORT['lowconf'].append(f"{d['url']}: {po} in_production from deposit acknowledgement / production message, {conf}")
        return
    m = re.search(r'[Cc]ontainer(?: loaded:)? ([A-Z]{4}\d{7})', t)
    if m: CH[d['code']].setdefault('containers', []).append((m.group(1), d['url'], at, st['cur'])); return
    for key, label in (('价', 'price'), ('放假', 'holiday'), ('DHL', 'sample courier'), ('quote', 'quote')):
        if key in t: REPORT['gap_' + label].append(f"{d['url']}: {t[:90]}"); return

HANDLERS = dict(pi=handle_pi, ci=handle_ci, qc=handle_qc, email=handle_email, chat=handle_chat)
SKIPPED = []
for d in docs:
    if d['kind'] in ('pi', 'ci', 'qc', 'email') and d['hash'] in READ:
        SKIPPED.append(d['url']);
    CNT['doc ' + d['kind']] += 0
    HANDLERS[d['kind']](d)

# ---------------------------------------------------------------- write
def run():
    done = collections.Counter(); touched = collections.defaultdict(set)
    for d, conf, facts, note in TX:
        if d['hash'] in READ and d['kind'] != 'chat': continue
        r = factstore.transact(facts, dry_run=DRY)
        done[note] += 1
    return done

if __name__ == '__main__':
    out = run()
    print('DRY' if DRY else 'WRITTEN', dict(out))
    print('transactions', len(TX), 'documents with facts', len({t[0]['hash'] for t in TX}))
    json.dump({k: v for k, v in REPORT.items()}, open(S + '/report.json', 'w'), indent=1, ensure_ascii=False)
    print({k: len(v) for k, v in REPORT.items()}, dict(CNT))
    # chat containers vs shipments
    allc = {s.container for s in SHIPS if s.container}
    for code, st in CH.items():
        for c, url, at, po in st.get('containers', []):
            if c not in allc: REPORT['unresolved'].append(f'{url}: container {c} in chat matches no shipment')
    print([x for x in REPORT['unresolved']][:40])
