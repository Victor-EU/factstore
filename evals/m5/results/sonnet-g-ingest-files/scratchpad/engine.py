import re, collections, datetime as dt, json, sys
from parse import *
import factstore

RANK = {s: i for i, s in enumerate('draft sent confirmed in_production ready shipped received'.split())}
SRANK = {s: i for i, s in enumerate('booked departed arrived delivered'.split())}

TX = []          # list of dict(doc, conf, facts)
LOG = collections.defaultdict(list)   # report notes by topic
CNT = collections.Counter()

st_codes = {r[0]: r[1] for r in factstore.query('select c.v, h.v from "factory/item_code" c join "sku/hs_code" h using(e)').rows}
po_status = {}        # po -> status
po_lines = {}         # po -> {code: (lineno, qty)}
po_info = {}          # po -> dict(supplier, total..)
po_etd = {}
shipments = []
chat_ctx = collections.defaultdict(dict)   # per chat file: last PI po, pending deposit...


def D(doc):
    return [{'e': ['document/hash', doc['hash']], 'a': 'document/url', 'v': doc['url']},
            {'e': ['document/hash', doc['hash']], 'a': 'document/issued_at', 'v': doc['issued'].isoformat()}]


def emit(doc, conf, facts, topic=None):
    if not facts:
        return
    TX.append(dict(doc=doc, conf=str(conf), facts=facts, topic=topic))


def A(e, a, v):
    return {'e': e, 'a': a, 'v': v}


def PO(n):
    return ['po/number', n]


def bump_po(doc, po, status, conf=1, extra=None):
    cur = po_status.get(po)
    if cur is None or RANK[status] > RANK[cur]:
        po_status[po] = status
        return [A(PO(po), 'po/status', status)]
    return []


def ref(sh):
    return ['shipment/booking_no', sh['booking']] if sh['booking'] else ['shipment/hbl', sh['hbl']]


def new_ship(**kw):
    sh = dict(booking=None, hbl=None, container=None, vessel=None, origin=None, dest=None, pos=set(),
              exact_pos=set(), lines={}, status=None, atd=None, eta=None, prealert=False, ci=False,
              delivered=False, entry=None, born=None)
    sh.update(kw)
    shipments.append(sh)
    return sh


def find_ship(hbl=None, so=None, vessel=None, pos=(), want='hbl'):
    """return (shipment, loose) ; want: which identifier is missing on the target"""
    for sh in shipments:
        if hbl and sh['hbl'] == hbl:
            return sh, False
        if so and sh['booking'] == so:
            return sh, False
    if vessel:
        cands = [sh for sh in shipments if sh['vessel'] == vessel and set(pos) <= sh['pos'] and
                 ((want == 'hbl' and not sh['hbl']) or (want == 'booking' and not sh['booking']))]
        if len(cands) > 1:
            LOG['ambiguous shipment match'].append((vessel, sorted(pos), [c['booking'] for c in cands]))
        if cands:
            sh = cands[0]
            loose = any(p not in sh['exact_pos'] for p in pos)
            return sh, loose
    return None, False


def sku_ref(sup, code):
    k = f'{sup}:{code}'
    if k not in st_codes:
        LOG['item code without SKU'].append(k)
        return None
    return ['factory/item_code', k]


def line_key(po, sup, code):
    ln = po_lines.get(po, {}).get(code)
    if not ln:
        LOG['line not found'].append((po, code))
        return None
    return f'{po}/{ln[0]}'


SUP_OF_PO = {}


# ------------------------------------------------------------------ PI
def do_pi(d):
    po, sup = d['po'], d['supplier']
    if po in po_lines:
        LOG['second PI for PO'].append((po, d['pi_no']))
    f = D(d)
    S = ['supplier/code', sup]
    f += [A(PO(po), 'po/pi_number', d['pi_no']), A(PO(po), 'po/supplier', S),
          A(PO(po), 'po/etd', d['etd'].isoformat()), A(PO(po), 'core/currency', d['currency'])]
    f += [A(S, 'supplier/name', d['beneficiary']), A(S, 'supplier/name_cn', d['name_cn']),
          A(S, 'supplier/address', d['address']), A(S, 'supplier/incoterm', d['incoterm']),
          A(S, 'supplier/payment_terms', re.sub(r'^T/T', 'T/T', d['payment'])),
          A(S, 'supplier/currency', d['currency']), A(S, 'supplier/port', d['port'])]
    po_etd[po] = d['etd']
    po_lines[po] = {}
    SUP_OF_PO[po] = sup
    tot = 0
    for i, it in enumerate(d['items'], 1):
        key = f'{po}/{i}'
        po_lines[po][it['code']] = (i, float(it['qty']))
        s = sku_ref(sup, it['code'])
        L = ['po_line/key', key]
        f += [A(L, 'core/part_of', PO(po)), A(L, 'po_line/quantity', it['qty']),
              A(L, 'po_line/unit_price', it['price'])]
        if s:
            f.append(A(L, 'po_line/sku', s))
        tot += float(it['qty']) * float(it['price'])
    po_info[po] = dict(total=tot, cur=d['currency'], payment=d['payment'], sup=sup, pi=d['pi_no'])
    f += bump_po(d, po, 'confirmed')
    emit(d, 1, f, 'pi')
    CNT['pi'] += 1


# ------------------------------------------------------------------ QC
def do_qc(d):
    po = d['po']
    Q = ['qc/report_no', d['report']]
    f = D(d) + [A(Q, 'qc/po', PO(po)), A(Q, 'qc/inspected_on', d['date'].isoformat()),
                A(Q, 'qc/result', d['result']), A(Q, 'qc/inspector', d['agency']),
                A(Q, 'qc/sample_size', d['sample'])]
    if d['result'] == 'PASS':
        f += bump_po(d, po, 'ready')
    elif d['result'] == 'FAIL':
        LOG['failed inspections'].append((d['report'], po))
    emit(d, 1, f, 'qc')
    CNT['qc'] += 1


# ------------------------------------------------------------------ shipped / received
def carrying(po):
    return [sh for sh in shipments if po in sh['pos'] or any(k.startswith(po + '/') for k in sh['lines'])]


def check_shipped(d, po, atd_date=None):
    """called after pre-alert / CI. returns facts"""
    if po not in po_lines:
        return []
    shs = carrying(po)
    booked = [sh for sh in shs if sh['booking'] and po in sh['pos']]
    c1 = bool(booked) and all(sh['prealert'] or sh['ci'] for sh in booked)
    tot = collections.Counter()
    for sh in shs:
        for k, q in sh['lines'].items():
            if k.startswith(po + '/'):
                tot[k] += q
    c2 = all(tot[f'{po}/{ln}'] >= q for ln, q in po_lines[po].values())
    if c1 != c2:
        LOG['shipped criteria disagree'].append((po, 'bookings' if c1 else 'no-bookings', 'qty-complete' if c2 else 'qty-short', d.get('hbl') or d.get('url')))
    f = []
    if c1 or c2:
        f += bump_po(d, po, 'shipped')
    return f


def po_atd_fact(po, sh):
    """po/etd := actual departure once PO is shipped"""
    if po_status.get(po) and RANK[po_status[po]] >= RANK['shipped'] and sh['atd']:
        shs = [s for s in carrying(po) if s['atd'] and s['prealert']]
        latest = max(s['atd'] for s in shs)
        if po_etd.get(po) != latest:
            po_etd[po] = latest
            return [A(PO(po), 'po/etd', latest.isoformat())]
    return []


def check_received(d, po):
    shs = carrying(po)
    if po_status.get(po) and RANK[po_status[po]] >= RANK['shipped'] and shs and all(s['delivered'] for s in shs):
        return bump_po(d, po, 'received')
    return []


# ------------------------------------------------------------------ CI
def do_ci(d):
    po, sup, hbl = d['po'], d['supplier'], d['hbl']
    pos = {po}
    sh, loose = find_ship(hbl=hbl, vessel=d['vessel'], pos=pos)
    pre = []
    if sh is None:
        sh = new_ship(hbl=hbl, vessel=d['vessel'])
        LOG['shipment created from CI (no booking found)'].append((hbl, po))
        CNT['shipment created'] += 1
    elif not sh['hbl']:
        sh['hbl'] = hbl
        pre = D(d) + [A(ref(sh), 'shipment/hbl', hbl)]
        emit(d, 0.9 if loose else 1, pre, 'ci-link')
        CNT['shipment hbl added'] += 1
    sh['ci'] = True
    sh['pos'].add(po); sh['exact_pos'].add(po)
    sh['container'] = None if d['container'] == 'LCL' else d['container']
    sh['vessel'] = d['vessel']; sh['origin'] = d['origin']; sh['dest'] = d['dest']
    H = ['shipment/hbl', hbl]
    f = D(d)
    if d['container'] != 'LCL':
        f.append(A(H, 'shipment/container_no', d['container']))
    f += [A(H, 'shipment/vessel', d['vessel']), A(H, 'shipment/origin', d['origin']),
          A(H, 'shipment/destination', d['dest'])]
    for it in d['items']:
        lk = line_key(po, sup, it['code'])
        if not lk:
            continue
        key = f'{hbl}/{lk}'
        sh['lines'][lk] = float(it['qty'])
        SL = ['shipment_line/key', key]
        f += [A(SL, 'core/part_of', H), A(SL, 'shipment_line/po_line', ['po_line/key', lk]),
              A(SL, 'shipment_line/quantity', it['qty']), A(SL, 'shipment_line/cartons', it['ctns'])]
        s = f'{sup}:{it["code"]}'
        if s in st_codes:
            if st_codes[s] != it['hs']:
                LOG['HS code differs from SKU'].append((s, st_codes[s], it['hs'], d['name']))
        else:
            LOG['item code without SKU'].append(s)
    f += check_shipped(d, po)
    emit(d, 1, f, 'ci')
    CNT['ci'] += 1


# ------------------------------------------------------------------ emails
def do_email(d):
    t = d['etype']
    f = D(d)
    if t == 'booking':
        so = d['so']
        pos = {p for p, _ in d['pos']}
        sh, loose = find_ship(so=so, vessel=d['vessel'], pos=pos, want='booking')
        if sh is None:
            sh = new_ship(booking=so)
            CNT['shipment created'] += 1
        elif not sh['booking']:
            sh['booking'] = so
            f.append(A(['shipment/hbl', sh['hbl']], 'shipment/booking_no', so))
            LOG['booking matched to existing shipment'].append((so, sh['hbl']))
        sh['pos'] |= pos
        sh['exact_pos'] |= {p for p, ex in d['pos'] if ex}
        sh['vessel'] = d['vessel']; sh['origin'] = d['origin']; sh['dest'] = d['dest']
        sh['status'] = 'booked'; sh['born'] = d['issued']
        sh['mode'] = d['mode']
        B = ['shipment/booking_no', so]
        etd = local_instant(d['etd'], d['origin']); eta = local_instant(d['eta'], d['dest'])
        sh['etd_book'] = etd
        f += [A(B, 'shipment/mode', d['mode']), A(B, 'shipment/vessel', d['vessel']),
              A(B, 'shipment/origin', d['origin']), A(B, 'shipment/destination', d['dest']),
              A(B, 'shipment/etd', etd), A(B, 'shipment/eta', eta), A(B, 'shipment/status', 'booked')]
        emit(d, 1, f, 'booking')
    elif t == 'roll':
        sh, _ = find_ship(so=d['so'])
        if not sh:
            LOG['unresolved'].append(('roll without booking', d['so']))
            return
        f += [A(ref(sh), 'shipment/etd', local_instant(d['etd'], sh['origin'])),
              A(ref(sh), 'shipment/eta', local_instant(d['eta'], sh['dest']))]
        emit(d, 1, f, 'roll')
    elif t == 'prealert':
        hbl = d['hbl']
        cargo = {r['po'] for r in d['rows']}
        sh, loose = find_ship(hbl=hbl, vessel=d['vessel'], pos=cargo)
        if sh is None:
            sh = new_ship(hbl=hbl, vessel=d['vessel'])
            LOG['shipment created from pre-alert (no booking found)'].append((hbl, sorted(cargo)))
            CNT['shipment created'] += 1
        elif not sh['hbl']:
            sh['hbl'] = hbl
            emit(d, 0.9 if loose else 1, D(d) + [A(ref(sh), 'shipment/hbl', hbl)], 'prealert-link')
            CNT['shipment hbl added'] += 1
        sh['prealert'] = True
        sh['pos'] |= cargo; sh['exact_pos'] |= cargo
        H = ['shipment/hbl', hbl]
        etd = local_instant(d['atd'], d['atd_port']); eta = local_instant(d['eta'], d['eta_port'])
        sh['atd'] = d['atd']; sh['status'] = 'departed'
        if d['container']:
            sh['container'] = d['container']
            f.append(A(H, 'shipment/container_no', d['container']))
        sh['vessel'] = d['vessel']
        f += [A(H, 'shipment/etd', etd), A(H, 'shipment/eta', eta), A(H, 'shipment/status', 'departed')]
        for r in d['rows']:
            sup = SUP_OF_PO.get(r['po'])
            lk = line_key(r['po'], sup, r['code'])
            if not lk:
                continue
            old = sh['lines'].get(lk)
            if old is not None and old != float(r['qty']):
                LOG['CI vs pre-alert quantity'].append((hbl, lk, old, r['qty']))
            sh['lines'][lk] = float(r['qty'])
            SL = ['shipment_line/key', f'{hbl}/{lk}']
            f += [A(SL, 'core/part_of', H), A(SL, 'shipment_line/po_line', ['po_line/key', lk]),
                  A(SL, 'shipment_line/quantity', r['qty']), A(SL, 'shipment_line/cartons', r['ctns'])]
        for po in sorted(cargo):
            f += check_shipped(d, po)
            f += po_atd_fact(po, sh)
        emit(d, 1, f, 'prealert')
    elif t == 'eta':
        sh, _ = find_ship(hbl=d['hbl'])
        if not sh:
            LOG['unresolved'].append(('ETA update for unknown HBL', d['hbl'])); return
        if sh['status'] in ('arrived', 'delivered'):
            LOG['stale ETA update skipped'].append((d['hbl'], d['issued'].isoformat())); return
        f.append(A(ref(sh), 'shipment/eta', local_instant(d['eta'], sh['dest'])))
        emit(d, 1, f, 'eta')
    elif t == 'arrival':
        sh, _ = find_ship(hbl=d['hbl'])
        if not sh:
            LOG['unresolved'].append(('arrival for unknown HBL', d['hbl'])); return
        if sh['dest'] and sh['dest'] != d['arr_port']:
            LOG['arrival port differs from destination'].append((d['hbl'], sh['dest'], d['arr_port']))
        if sh['container'] != d['container']:
            LOG['container differs'].append((d['hbl'], sh['container'], d['container']))
        sh['status'] = 'arrived'
        f += [A(ref(sh), 'shipment/status', 'arrived'),
              A(ref(sh), 'shipment/eta', local_instant(d['arr'], d['arr_port']))]
        emit(d, 1, f, 'arrival')
    elif t == 'entry':
        ident = d['ident']
        if ident.startswith('PBLHB'):
            sh, _ = find_ship(hbl=ident)
        else:
            c = [s for s in shipments if s['container'] == ident and s['prealert'] and not s['entry']
                 and s['born'] is not None or (s['container'] == ident and s['prealert'] and not s['entry'])]
            sh = c[-1] if c else None
            if len(c) > 1:
                LOG['container reused: entry matched to latest unentered shipment'].append((ident, d['entry'], [x['hbl'] for x in c]))
        if not sh:
            LOG['unresolved'].append(('entry for unknown shipment', d['entry'], ident)); return
        sh['entry'] = d['entry']
        E = ['customs/entry_no', d['entry']]
        f += [A(E, 'customs/shipment', ref(sh)),
              A(E, 'customs/filed_on', d['issued'].date().isoformat()),
              A(E, 'customs/entered_value', d['value']), A(E, 'customs/duty', d['duty']),
              A(E, 'customs/fees', d['fees']), A(E, 'core/currency', 'USD')]
        emit(d, 1, f, 'entry')
    elif t == 'receipt':
        ident = d['ident']
        if ident.startswith('PBLHB'):
            sh, _ = find_ship(hbl=ident)
        else:
            c = [s for s in shipments if s['container'] == ident and not s['delivered'] and s['prealert']]
            if len(c) > 1:
                c2 = [s for s in c if s['status'] == 'arrived']
                LOG['container reused: receipt matched'].append((ident, d['rcv'], [x['hbl'] for x in c], [x['hbl'] for x in c2]))
                c = c2 or c
            sh = c[0] if c else None
        if not sh:
            LOG['unresolved'].append(('receipt for unknown shipment', d['rcv'], ident)); return
        sh['delivered'] = True; sh['status'] = 'delivered'
        f += [A(ref(sh), 'shipment/status', 'delivered'),
              A(ref(sh), 'shipment/delivered_at', d['issued'].isoformat())]
        pos = {k.split('/')[0] for k in sh['lines']}
        for po in sorted(pos):
            f += check_received(d, po)
        for sku, exp, rec, dam in d['disc']:
            if exp != rec or int(dam):
                LOG['warehouse discrepancies'].append((d['rcv'], sku, exp, rec, dam))
        emit(d, 1, f, 'receipt')
    CNT[t] += 1


# ------------------------------------------------------------------ chat
def next_date(m, dday, ref_dt):
    r = ref_dt.astimezone(CN).date()
    for y in (r.year, r.year + 1):
        try:
            c = dt.date(y, m, dday)
        except ValueError:
            continue
        if c >= r:
            return c


def do_chat(d, pi_po_by_name, ci_by_container):
    key = d['file']
    ctx = chat_ctx[key]
    b = d['body'].strip()
    ts = d['issued']
    sup = d['sup']
    f = D(d)
    if d['ours']:
        m = re.search(r'(?:new PO|PO) (PO-\d{4}-\d{4})|here\'s (PO-\d{4}-\d{4})', b)
        if m and not b.startswith('[') and ('attached' in b or 'for ' in b and 'items' in b or "here's" in b):
            po = m[1] or m[2]
            f += [A(PO(po), 'po/placed_on', ts.astimezone(CHAT_TZ).date().isoformat()),
                  A(PO(po), 'po/supplier', ['supplier/code', sup])]
            SUP_OF_PO.setdefault(po, sup)
            ctx['last_po'] = po
            emit(d, 1, f, 'chat-po'); CNT['chat po sent'] += 1
            return
        m = re.search(r'deposit for (PO-\d{4}-\d{4}) \((USD|CNY) ([\d,.]+)\)', b)
        if m:
            ctx['dep'] = (m[1], 0.9); return
        m = re.search(r'Deposit paid today, (USD|CNY) ([\d,]+\.\d\d)', b)
        if m:
            amt = float(num(m[2]))
            c = [p for p, i in po_info.items() if i['sup'] == sup and i['cur'] == m[1] and
                 re.search(r'(\d+)% deposit', i['payment']) and
                 abs(float(re.search(r'(\d+)% deposit', i['payment'])[1]) / 100 * i['total'] - amt) < 0.02]
            if len(c) == 1:
                ctx['dep'] = (c[0], 0.8)
            else:
                LOG['unresolved'].append(('deposit amount matches', d['url'], amt, c))
                ctx['dep'] = None
            return
        return
    # supplier messages
    pi = re.match(r'\[文件\] ((?!CI-PL|PO-|LCI)\S+)\.pdf', b)
    if pi:
        ctx['last_pi'] = pi_po_by_name.get(pi[1]); return
    if re.match(r'(Received, thank you|收到，谢谢|定金收到了，马上安排生产)$', b):
        dep = ctx.pop('dep', None)
        if dep:
            po, conf = dep
            f2 = bump_po(d, po, 'in_production')
            if f2:
                emit(d, conf, f + f2, 'chat-prod'); CNT['chat in_production'] += 1
            ctx.pop('dep', None)
        return
    if b.startswith('大货生产中'):
        # production under way; PO not named: the chat's latest PO still short of in_production
        cands = [p for p in po_info if po_info[p]['sup'] == sup and po_status.get(p) in ('confirmed',)]
        if len(cands) == 1:
            f2 = bump_po(d, cands[0], 'in_production')
            emit(d, 0.7, f + f2, 'chat-prod'); CNT['chat in_production'] += 1
        else:
            LOG['unresolved'].append(('"production under way" without PO', d['url'], cands))
        return
    po = None; conf = 0.9
    m = re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', b)
    if m:
        po, mo, dd = m[1], int(m[2]), int(m[3])
    m2 = re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', b)
    if m2:
        po, mo, dd = m2[1], int(m2[2]), int(m2[3])
    if not po:
        m3 = re.fullmatch(r'ETD (\d+)/(\d+)', b) or re.match(r'交期(\d+)月(\d+)号左右', b)
        if m3:
            po = ctx.get('last_pi'); mo, dd = int(m3[1]), int(m3[2]); conf = 0.8
            if not po:
                LOG['unresolved'].append(('ETD without PI context', d['url'])); return
    if po:
        if po_status.get(po) and RANK[po_status[po]] >= RANK['shipped']:
            LOG['ETD message after shipped: skipped'].append((po, d['url'])); return
        date = next_date(mo, dd, ts)
        if po_etd.get(po) == date:
            LOG['chat ETD equals current'].append((po, d['url'], conf))
            return
        po_etd[po] = date
        emit(d, conf, f + [A(PO(po), 'po/etd', date.isoformat())], 'chat-etd'); CNT['chat etd'] += 1
        return
    m = re.search(r'[Cc]ontainer(?: loaded:)? (\w{4}\d{7})', b)
    if m:
        cont = m[1]
        po = ci_by_container.get((key, cont, ts))
        if not po:
            LOG['unresolved'].append(('container message: no PO', d['url'], cont)); return
        cands = [s for s in shipments if po in s['pos'] and not s['prealert'] and not s['ci']]
        if len(cands) != 1:
            LOG['unresolved'].append(('container message: shipment not found', d['url'], cont, po, len(cands))); return
        sh = cands[0]
        sh['container'] = cont
        emit(d, 0.8, f + [A(ref(sh), 'shipment/container_no', cont)], 'chat-container'); CNT['chat container'] += 1
        return
