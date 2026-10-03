"""Turn all documents into an ordered list of transactions (no writes here)."""
import re, collections, json, sys
from datetime import datetime, date, timedelta
from decimal import Decimal as D
import factstore
from load import *
from deps import deposits_and_acks

RANK = {s: i for i, s in enumerate(['draft', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received'])}
SRANK = {s: i for i, s in enumerate(['booked', 'departed', 'arrived', 'delivered'])}
LOW = 'Low'
R = collections.defaultdict(list)   # report notes

# ---- store reference data -------------------------------------------------
ITEMS = {r[0]: r[1] for r in factstore.query('select f.v, h.v from "factory/item_code" f join "sku/hs_code" h using(e)').rows}
SUPS = {r[0] for r in factstore.query('select v from "supplier/code"').rows}

pdfs = pdf_docs()
chats = chat_docs()
mails = email_docs()
pis = [d for d in pdfs if d['kind'] == 'pi']
PI_BY_NO = {p['pi_no']: p for p in pis}
PO_SUP = {p['po']: p['sup_code'] for p in pis}
dep_list, ack_list, dep_issues = deposits_and_acks(pis, chats)
for i in dep_issues:
    R['deposit/ack unresolved'].append(i)
ACK_BY_URL = {a['m']['url']: a for a in ack_list}


def iso(dt):
    return dt.isoformat()


def isod(d):
    return d.isoformat()


def po_ref(po): return ['po/number', po]
def sup_ref(c): return ['supplier/code', c]
def item_ref(sup, item): return ['factory/item_code', f'{sup}:{item}']
def shp_ref(s): return ['shipment/hbl', s['hbl']] if s['hbl'] else ['shipment/booking_no', s['booking']]


class World:
    def __init__(self):
        self.po = {}      # po -> dict(status, sup, lines{item: (n, qty)}, etd)
        self.ship = []    # shipment dicts
        self.txs = []

    def P(self, po):
        return self.po.setdefault(po, dict(status=None, sup=PO_SUP.get(po), lines={}, line_qty={}, etd=None, placed=None))

    def tx(self, doc, conf, facts, label):
        if not facts:
            return
        pre = [
            {'e': ['document/hash', doc['hash']], 'a': 'document/url', 'v': doc['url']},
            {'e': ['document/hash', doc['hash']], 'a': 'document/issued_at', 'v': iso(doc['issued'])},
            {'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', doc['hash']]},
            {'e': 'tmp:tx', 'a': 'core/confidence', 'v': conf},
        ]
        self.txs.append(dict(doc=doc, conf=conf, label=label, facts=pre + facts))

    def set_status(self, po, st):
        """returns facts if st is further along than the PO's status"""
        p = self.P(po)
        if p['status'] is None or RANK[st] > RANK[p['status']]:
            p['status'] = st
            return [{'e': po_ref(po), 'a': 'po/status', 'v': st}]
        return []


W = World()


def F(e, a, v):
    return {'e': e, 'a': a, 'v': v}


# ---- shipment helpers --------------------------------------------------------
def norm_pos(s):
    out = []
    for tok in re.split(r',\s*', s.strip()):
        m = re.match(r'(?i)^po\s*#?\s*-?\s*(?:(\d{4})\s*-\s*)?(\d+)$', tok.strip().replace('##', '#'))
        m2 = re.match(r'(?i)^po[#\s-]*(\d{4})-(\d{4})$', tok.strip())
        if m2:
            out.append(f'PO-{m2.group(1)}-{m2.group(2)}')
        elif m:
            y, n = m.group(1), int(m.group(2))
            if y is None:
                y = '2025' if n >= 143 else '2026'
            out.append(f'PO-{y}-{n:04d}')
        else:
            R['unparsed PO token'].append(tok)
    return out


def find_ship(hbl=None, booking=None, container=None, vessel=None, pos=(), before=None):
    if hbl:
        for s in W.ship:
            if s['hbl'] == hbl: return s
    if booking:
        for s in W.ship:
            if s['booking'] == booking: return s
    if container:
        c = [s for s in W.ship if s['container'] == container]
        if c: return c
    if pos:
        c = [s for s in W.ship if not s['hbl'] and (set(pos) & s['pos'])]
        cv = [s for s in c if vessel and s['vessel'] == vessel]
        if len(cv) == 1: return cv[0]
        if len(cv) > 1:
            R['ambiguous shipment match'].append((hbl, vessel, sorted(pos), [s['booking'] for s in cv]))
            return cv[0]
        if len(c) == 1:
            R['shipment matched by PO only (vessel differs)'].append((hbl, vessel, sorted(pos), c[0]['booking'], c[0]['vessel']))
            return c[0]
    return None


def new_ship(**kw):
    s = dict(hbl=None, booking=None, container=None, vessel=None, pos=set(), origin=None, dest=None, status=None,
             lines={}, mode=None, docs=[])
    s.update(kw)
    W.ship.append(s)
    return s


def ship_status(s, st):
    if s['status'] is None or SRANK[st] > SRANK[s['status']]:
        s['status'] = st
        return True
    return False


def po_line_key(po, item):
    p = W.P(po)
    n = p['lines'].get(item)
    return f'{po}/{n}' if n else None


def pos_of_ship(s):
    return set(s['pos']) | {k.split('/')[0] + '' for k in []} | {pl[0] for pl in s['lines'].values()}


def po_shipped(po):
    """every booking carrying the PO has a pre-alert or CI, or lines add up to every line's quantity"""
    carriers = [s for s in W.ship if po in s['pos'] or any(v[0] == po for v in s['lines'].values())]
    cond1 = bool(carriers) and all(s['hbl'] for s in carriers)
    p = W.P(po)
    tot = collections.defaultdict(D)
    for s in carriers:
        for k, (pp, line, q) in s['lines'].items():
            if pp == po: tot[line] += q
    cond2 = bool(p['line_qty']) and all(tot[l] >= q for l, q in p['line_qty'].items())
    return cond1 or cond2


def po_received(po):
    carriers = [s for s in W.ship if po in s['pos'] or any(v[0] == po for v in s['lines'].values())]
    return bool(carriers) and all(s['status'] == 'delivered' for s in carriers)


# ---- document emitters ---------------------------------------------------------
def do_pi(d):
    po = d['po']; p = W.P(po)
    sup = d['sup_code']
    p['sup'] = sup
    facts = [
        F(po_ref(po), 'po/pi_number', d['pi_no']),
        F(po_ref(po), 'po/supplier', sup_ref(sup)),
        F(po_ref(po), 'po/etd', isod(d['etd'])),
        F(po_ref(po), 'core/currency', d['cur']),
    ]
    p['etd'] = d['etd']
    facts += W.set_status(po, 'confirmed')
    for i, r in enumerate(d['rows'], 1):
        code = f"{sup}:{r['item']}"
        if code not in ITEMS:
            R['PI item code with no SKU'].append((d['name'], code)); continue
        key = f'{po}/{i}'
        p['lines'][r['item']] = i
        p['line_qty'][key] = D(r['qty'])
        lr = ['po_line/key', key]
        facts += [F(lr, 'core/part_of', po_ref(po)), F(lr, 'po_line/sku', item_ref(sup, r['item'])),
                  F(lr, 'po_line/quantity', r['qty']), F(lr, 'po_line/unit_price', r['price'])]
    s = sup_ref(sup)
    facts += [F(s, 'supplier/name_cn', d['sup_cn']), F(s, 'supplier/name', d['bene']),
              F(s, 'supplier/address', d['address']), F(s, 'supplier/incoterm', d['term']),
              F(s, 'supplier/payment_terms', d['payment']), F(s, 'supplier/currency', d['cur']),
              F(s, 'supplier/port', d['port'])]
    W.tx(d, '1', facts, f"PI {d['pi_no']}")


def do_qc(d):
    po = d['po']
    facts = [F(['qc/report_no', d['report_no']], 'qc/po', po_ref(po)),
             F(['qc/report_no', d['report_no']], 'qc/inspected_on', d['date']),
             F(['qc/report_no', d['report_no']], 'qc/result', d['result']),
             F(['qc/report_no', d['report_no']], 'qc/inspector', d['agency'].title()),
             F(['qc/report_no', d['report_no']], 'qc/sample_size', d['sample'])]
    if d['result'] == 'PASS':
        facts += W.set_status(po, 'ready')
    W.tx(d, '1', facts, f"QC {d['report_no']}")


def line_facts(s_ref, hbl, po, rows, source):
    """rows: list of (item, pcs, ctns)"""
    out = []
    sup = W.P(po)['sup']
    for item, pcs, ctns in rows:
        key = po_line_key(po, item)
        if not key:
            R['shipment row with no PO line'].append((source, po, item)); continue
        lk = f'{hbl}/{key}'
        lr = ['shipment_line/key', lk]
        out += [F(lr, 'core/part_of', s_ref), F(lr, 'shipment_line/po_line', ['po_line/key', key]),
                F(lr, 'shipment_line/quantity', str(pcs))]
        if ctns is not None:
            out.append(F(lr, 'shipment_line/cartons', str(ctns)))
    return out


def record_lines(s, po, rows):
    for item, pcs, ctns in rows:
        key = po_line_key(po, item)
        if key:
            s['lines'][f"{s['hbl']}/{key}"] = (po, key, D(str(pcs)))


def after_ship_status(doc, label, pos_touched, extra_facts, conf='1'):
    pass


def po_status_facts_after_sail(pos, atd_date=None):
    facts = []
    for po in sorted(pos):
        if po_shipped(po):
            f = W.set_status(po, 'shipped')
            facts += f
            if atd_date is not None and W.P(po)['status'] in ('shipped', 'received'):
                facts.append(F(po_ref(po), 'po/etd', isod(atd_date)))
                W.P(po)['etd'] = atd_date
    return facts


def do_ci(d):
    po = d['orders'][0]
    sup = W.P(po)['sup']
    lcl = d['container'] == 'LCL'
    s = find_ship(hbl=d['hbl'], vessel=d['vessel'], pos=[po])
    if s is None:
        s = new_ship(hbl=d['hbl'], vessel=d['vessel'], pos={po})
        R['shipment created from CI (no booking found)'].append((d['name'], d['hbl']))
        facts = []
    else:
        facts = []
        if not s['hbl']:
            s['hbl'] = d['hbl']
            facts.append(F(['shipment/booking_no', s['booking']], 'shipment/hbl', d['hbl']))
    s['pos'].add(po)
    sr = ['shipment/hbl', d['hbl']]
    if facts and s['booking']:      # hbl is being attached in this very transaction: address by booking
        sr = ['shipment/booking_no', s['booking']]
    if not lcl:
        if s['container'] and s['container'] != d['container']:
            R['container conflict'].append((d['name'], s['container'], d['container']))
        s['container'] = d['container']
        facts.append(F(sr, 'shipment/container_no', d['container']))
    s['vessel'] = d['vessel']
    facts += [F(sr, 'shipment/vessel', d['vessel']), F(sr, 'shipment/origin', d['origin']),
              F(sr, 'shipment/destination', d['dest'])]
    s['origin'], s['dest'] = d['origin'], d['dest']
    rows = []
    for r in d['rows']:
        pl = d['pl'].get(r['item'])
        code = f"{sup}:{r['item']}"
        if code not in ITEMS:
            R['CI item code with no SKU'].append((d['name'], code)); continue
        if ITEMS[code] != r['hs']:
            R['HS code differs from SKU'].append((d['name'], code, r['hs'], ITEMS[code]))
        if pl is None or pl['pcs'] != r['qty']:
            R['CI/PL pieces differ'].append((d['name'], r['item'], r['qty'], pl))
        rows.append((r['item'], int(r['qty']), int(pl['ctns']) if pl else None))
    facts += line_facts(sr, d['hbl'], po, rows, d['name'])
    record_lines(s, po, rows)
    facts += po_status_facts_after_sail([po])
    W.tx(d, '1', facts, f"CI {d['name']}")


# ---- emails --------------------------------------------------------------------
def pdate(s):
    return datetime.strptime(s, '%d %b %Y').date()


def do_email(d):
    sj = d['subject']; b = d['body']
    if sj.startswith('Booking Confirmation'):
        g = lambda k: re.search(rf'^{k}: (.*)$', b, re.M).group(1).strip()
        so = g('SO')
        eq = g('Equipment')
        mode = 'LCL' if eq.startswith('LCL') else re.search(r'x(\w+)$', eq).group(1)
        m = re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)', b)
        o, de = m.groups()
        pos = norm_pos(g('POs'))
        etd = local_midnight(pdate(g('ETD')), o); eta = local_midnight(pdate(g('ETA')), de)
        s = find_ship(booking=so)
        if s is None:
            s = new_ship(booking=so)
        s.update(vessel=g('Vessel/Voyage'), pos=set(pos), origin=o, dest=de, mode=mode)
        ship_status(s, 'booked')
        sr = ['shipment/booking_no', so]
        facts = [F(sr, 'shipment/mode', mode), F(sr, 'shipment/vessel', s['vessel']), F(sr, 'shipment/origin', o),
                 F(sr, 'shipment/destination', de), F(sr, 'shipment/etd', iso(etd)), F(sr, 'shipment/eta', iso(eta)),
                 F(sr, 'shipment/status', 'booked')]
        W.tx(d, '1', facts, f'booking {so}')
    elif sj.startswith('RE: Booking Confirmation'):
        so = re.search(r'SO (\S+)', sj).group(1)
        m = re.search(r'New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})', b)
        s = find_ship(booking=so)
        if s is None:
            R['roll for unknown booking'].append(so); return
        etd = local_midnight(pdate(m.group(1)), s['origin']); eta = local_midnight(pdate(m.group(2)), s['dest'])
        sr = shp_ref(s)
        W.tx(d, '1', [F(sr, 'shipment/etd', iso(etd)), F(sr, 'shipment/eta', iso(eta))], f'roll {so}')
    elif sj.startswith('Shipping Advice'):
        g = lambda k: re.search(rf'^{k}: (.*)$', b, re.M).group(1).strip()
        hbl = g('HBL')
        cs = g('Container/Seal').split(' / ')[0]
        vessel = g('Vessel/Voyage')
        m = re.search(r'^ATD (.+?): (\d+ \w+ \d{4})$', b, re.M)
        m2 = re.search(r'^ETA (.+?): (\d+ \w+ \d{4})$', b, re.M)
        o = PORTS[m.group(1)]; de = PORTS[m2.group(1)]
        rows = re.findall(r'^\s+(PO-\d+-\d+)\s+(\S+)\s+(\d+) ctns\s+([\d,]+) pcs$', b, re.M)
        pos = sorted({r[0] for r in rows})
        s = find_ship(hbl=hbl, vessel=vessel, pos=pos)
        facts = []
        if s is None:
            s = new_ship(hbl=hbl, vessel=vessel, pos=set(pos)); R['shipment created from pre-alert (no booking found)'].append(hbl)
        elif not s['hbl']:
            s['hbl'] = hbl
            facts.append(F(['shipment/booking_no', s['booking']], 'shipment/hbl', hbl))
        s['pos'] |= set(pos)
        sr = ['shipment/hbl', hbl]
        if facts and s['booking']:
            sr = ['shipment/booking_no', s['booking']]
        atd = local_midnight(pdate(m.group(2)), o); eta = local_midnight(pdate(m2.group(2)), de)
        if cs != 'LCL':
            if s['container'] and s['container'] != cs:
                R['container conflict'].append((hbl, s['container'], cs))
            s['container'] = cs
            facts.append(F(sr, 'shipment/container_no', cs))
        s['vessel'] = vessel; s['origin'] = o; s['dest'] = de
        facts += [F(sr, 'shipment/vessel', vessel), F(sr, 'shipment/origin', o), F(sr, 'shipment/destination', de),
                  F(sr, 'shipment/etd', iso(atd)), F(sr, 'shipment/eta', iso(eta))]
        if ship_status(s, 'departed'):
            facts.append(F(sr, 'shipment/status', 'departed'))
        for po in pos:
            rr = [(it, int(q.replace(',', '')), int(c)) for p_, it, c, q in rows if p_ == po]
            facts += line_facts(sr, hbl, po, rr, hbl)
            record_lines(s, po, rr)
        facts += po_status_facts_after_sail(pos, atd_date=atd.date())
        W.tx(d, '1', facts, f'prealert {hbl}')
    elif sj.startswith('ETA update'):
        hbl = re.search(r'HBL (\w+)', sj).group(1)
        m = re.search(r'revised ETA (\d+ \w+ \d{4})', b)
        s = find_ship(hbl=hbl)
        if s is None:
            R['ETA update for unknown HBL'].append(hbl); return
        eta = local_midnight(pdate(m.group(1)), s['dest'])
        W.tx(d, '1', [F(['shipment/hbl', hbl], 'shipment/eta', iso(eta))], f'eta {hbl}')
    elif sj.startswith('Arrival Notice'):
        hbl = re.search(r'HBL (\w+)', sj).group(1)
        m = re.search(r'arriving (.+?) on (\d+ \w+ \d{4})', b)
        s = find_ship(hbl=hbl)
        if s is None:
            R['arrival for unknown HBL'].append(hbl); return
        eta = local_midnight(pdate(m.group(2)), PORTS[m.group(1)])
        sr = ['shipment/hbl', hbl]
        facts = []
        if ship_status(s, 'arrived'):
            facts.append(F(sr, 'shipment/status', 'arrived'))
        facts.append(F(sr, 'shipment/eta', iso(eta)))
        W.tx(d, '1', facts, f'arrival {hbl}')
    elif sj.startswith('Receipt complete'):
        key = sj.rsplit(' - ', 1)[1].strip()
        if key.startswith('PBLHB'):
            s = find_ship(hbl=key)
        else:
            c = [s for s in W.ship if s['container'] == key and s['status'] != 'delivered']
            c.sort(key=lambda s: 0)
            if len(c) > 1:
                R['receipt container matches several undelivered shipments'].append((key, [x['hbl'] for x in c]))
            s = c[0] if c else None
        if s is None:
            R['receipt for unknown shipment'].append(key); return
        sr = shp_ref(s)
        facts = []
        if ship_status(s, 'delivered'):
            facts.append(F(sr, 'shipment/status', 'delivered'))
        facts.append(F(sr, 'shipment/delivered_at', iso(d['issued'])))
        for po in sorted(pos_of_ship(s)):
            if po_received(po):
                facts += W.set_status(po, 'received')
        W.tx(d, '1', facts, f'receipt {key}')
        for m in re.finditer(r'(\S+) \((.*?)\): expected (\d+), received (\d+), damaged (\d+)', b):
            if m.group(3) != m.group(4) or m.group(5) != '0':
                R['warehouse discrepancies'].append((key, m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)))
    elif sj.startswith('Entry Summary'):
        mm = re.match(r'Entry Summary (\S+) - (\S+)', sj)
        entry, key = mm.groups()
        if key.startswith('PBLHB'):
            s = find_ship(hbl=key)
        else:
            c = [s for s in W.ship if s['container'] == key]
            s = c[-1] if c else None
            if len(c) > 1: R['entry container matches several shipments'].append((entry, key, [x['hbl'] for x in c]))
        if s is None:
            R['entry for unknown shipment'].append((entry, key)); return
        g = lambda k: D(num(re.search(rf'^{k}: USD ([\d,.]+)$', b, re.M).group(1)))
        val = g('Entered value'); duty = g('Duty \\(HTS\\)') + g('Section 301') + g('Additional duties')
        fees = g('MPF') + g('HMF')
        tot = g('Total duties and fees')
        if duty + fees != tot:
            R['entry total mismatch'].append((entry, duty + fees, tot))
        er = ['customs/entry_no', entry]
        filed = d['issued'].date()
        facts = [F(er, 'customs/shipment', shp_ref(s)), F(er, 'customs/filed_on', isod(filed)),
                 F(er, 'customs/entered_value', str(val)), F(er, 'customs/duty', str(duty)),
                 F(er, 'customs/fees', str(fees)), F(er, 'core/currency', 'USD')]
        W.tx(d, '1', facts, f'entry {entry}')
    else:
        R['unhandled email'].append(sj)


# ---- chats ---------------------------------------------------------------------
def next_md(m, dd, after_cn):
    for y in (after_cn.year, after_cn.year + 1):
        try:
            c = date(y, m, dd)
        except ValueError:
            continue
        if c >= after_cn: return c


def do_chat(d):
    t = d['text'].strip(); sup = d['sup']
    ts_cn = d['issued'].astimezone(CN).date()
    if d['ours']:
        m = re.search(r'(?:PO (PO-\d{4}-\d{4}) for \d+ items|new PO (PO-\d{4}-\d{4}) attached|here\'s (PO-\d{4}-\d{4})\.)', t)
        if m:
            po = next(x for x in m.groups() if x)
            W.P(po)['sup'] = W.P(po)['sup'] or sup
            if PO_SUP.get(po) not in (None, sup):
                R['PO placed with different supplier than its PI'].append((po, sup, PO_SUP.get(po)))
            placed = d['issued'].date()
            W.tx(d, '1', [F(po_ref(po), 'po/placed_on', isod(placed)), F(po_ref(po), 'po/supplier', sup_ref(sup))],
                 f'PO placed {po}')
            W.P(po)['placed'] = placed
        return
    # supplier messages
    if d['url'] in ACK_BY_URL and not t.startswith('大货'):
        a = ACK_BY_URL[d['url']]
        po = a['dep']['po']
        f = W.set_status(po, 'in_production')
        if f: W.tx(d, '0.9', f, f'deposit ack {po}')
        return
    m = re.match(r'^Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货$', t)
    if m:
        pi = PI_BY_NO[m.group(1)]; po = pi['po']
        etd = next_md(int(m.group(2)), int(m.group(3)), ts_cn)
        return etd_update(d, po, etd)
    m = re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)$', t)
    if m:
        return etd_update(d, m.group(1), next_md(int(m.group(2)), int(m.group(3)), ts_cn))
    m = re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', t)
    if m:
        return etd_update(d, m.group(1), next_md(int(m.group(2)), int(m.group(3)), ts_cn))
    m = re.search(r'container loaded: ([A-Z]{4}\d{7}) seal|^Container ([A-Z]{4}\d{7}) loaded today', t)
    if m:
        cn = m.group(1) or m.group(2)
        # the supplier's PO that is ready and not yet sailed (earliest)
        c = [po for po, p in W.po.items() if p['sup'] == sup and p['status'] in ('ready',) and not po_shipped(po)]
        c.sort()
        ships = []
        for po in c:
            ships += [s for s in W.ship if po in s['pos'] and not s['container'] and not s['hbl']]
        if len(c) >= 1 and ships:
            s = ships[0]
            if len(c) > 1:
                R['container message with several ready POs'].append((d['url'], cn, c))
            s['container'] = cn
            W.tx(d, '0.9', [F(shp_ref(s), 'shipment/container_no', cn)], f'chat container {cn} for {c[0]}')
        else:
            R['chat container not resolved to a shipment'].append((d['url'], cn, c))
        return
    # PI-time ETD messages: the PI itself carries the date
    m = re.match(r'^(?:交期(\d+)月(\d+)号左右|ETD (?:around )?(\d+)/(\d+)|交期(\d+)月(\d+)号左右，ETD around (\d+)/(\d+))$', t)
    if m:
        return


def etd_update(d, po, etd):
    p = W.P(po)
    if p['status'] in ('shipped', 'received'):
        R['ETD slip after goods sailed (not applied)'].append((d['url'], po, etd)); return
    p['etd'] = etd
    W.tx(d, '0.9', [F(po_ref(po), 'po/etd', isod(etd))], f'ETD {po} {etd}')


# ---- run in issue order -----------------------------------------------------------
events = []
for d in pdfs:
    events.append((d['issued'], {'pi': 1, 'ci': 3, 'qc': 2}[d['kind']], d))
for d in chats:
    events.append((d['issued'], 0, d))
for d in mails:
    events.append((d['issued'], 4, d))
events.sort(key=lambda e: (e[0], e[1]))
for _, _, d in events:
    k = d['kind']
    if k == 'pi': do_pi(d)
    elif k == 'qc': do_qc(d)
    elif k == 'ci': do_ci(d)
    elif k == 'chat': do_chat(d)
    elif k == 'email': do_email(d)

if __name__ == '__main__':
    print(len(W.txs), 'transactions')
    print(collections.Counter(t['label'].split()[0] for t in W.txs))
    for k, v in R.items():
        print('##', k, len(v))
        for x in v[:40]: print('   ', x)
    print({po: p['status'] for po, p in sorted(W.po.items())})
