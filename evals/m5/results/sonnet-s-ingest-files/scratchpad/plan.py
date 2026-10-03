import re, json, collections, datetime as dt
import factstore
from parse import *

docs = load_docs(); chats = load_chats(); mail = load_mail()
events = docs + chats + mail
for i, e in enumerate(events):
    e['i'] = i
events.sort(key=lambda e: (e['t'], e['i']))

REPORT = collections.defaultdict(list)
def rep(k, msg):
    REPORT[k].append(msg)

# ---------- store reference data
hs_store = {}
for c, hs in factstore.query('select f.v, h.v from "factory/item_code" f join "sku/hs_code" h using(e)').rows:
    hs_store[c] = hs
items_in_store = set(hs_store)

RANK = ['draft', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received']
SRANK = ['booked', 'departed', 'arrived', 'delivered']

# ---------- pre-pass: PO universe, shipment <-> booking mapping
all_pos = set()
for e in docs:
    all_pos.add(e['d']['po'])
for e in chats:
    all_pos.update(re.findall(r'PO-\d{4}-\d{4}', e['text']))

def resolve_po(raw):
    out = []
    for tok in re.findall(r'PO#?[ -]?(?:\d{4}-)?\d+|po \d+', raw, re.I):
        m = re.search(r'(?:(\d{4})-)?(\d+)$', tok)
        yr, n = m.group(1), int(m.group(2))
        cands = [p for p in all_pos if int(p[-4:]) == n and (yr is None or p[3:7] == yr)]
        if len(cands) == 1:
            out.append(cands[0])
        else:
            rep('unresolved', f'loose PO {tok!r} in {raw!r}: {cands}')
    return out

bookings = {}
for e in mail:
    if e['kind'] == 'booking':
        e['d']['pos'] = resolve_po(e['d']['pos_raw'])
        bookings[e['d']['so']] = e

hbl_info = collections.defaultdict(lambda: dict(vessels=set(), pos=set(), container=None, origin=None, dest=None))
for e in docs:
    if e['kind'] == 'ci':
        d = e['d']; h = hbl_info[d['hbl']]
        h['vessels'].add(d['vessel']); h['pos'].add(d['po'])
        if d['container'] != 'LCL': h['container'] = d['container']
        h['origin'], h['dest'] = d['origin'], d['dest']
for e in mail:
    if e['kind'] == 'prealert':
        d = e['d']; h = hbl_info[d['hbl']]
        h['vessels'].add(d['vessel']); h['pos'].update(l['po'] for l in d['lines'])
        if d['container'] != 'LCL': h['container'] = d['container']

hbl2so = {}
for hbl, h in hbl_info.items():
    cands = [so for so, b in bookings.items() if b['d']['vessel'] in h['vessels'] and set(b['d']['pos']) & h['pos']]
    if len(cands) == 1:
        hbl2so[hbl] = cands[0]
    else:
        rep('unresolved', f'HBL {hbl} vessel {h["vessels"]} POs {h["pos"]} -> bookings {cands}')
so_used = collections.Counter(hbl2so.values())
for so, n in so_used.items():
    if n > 1: rep('unresolved', f'booking {so} matches {n} HBLs')
for so in bookings:
    if so not in so_used: rep('info', f'booking {so} (POs {bookings[so]["d"]["pos"]}) has no pre-alert/CI')
cont2hbl = {}
for hbl, h in hbl_info.items():
    if h['container']:
        if h['container'] in cont2hbl and cont2hbl[h['container']] != hbl:
            rep('unresolved', f'container {h["container"]} on two HBLs')
        cont2hbl[h['container']] = hbl

def SHIP(hbl=None, so=None):
    if so is None and hbl in hbl2so:
        so = hbl2so[hbl]
    if so:
        return ['shipment/booking_no', so]
    return ['shipment/hbl', hbl]

# ---------- state
PO = collections.defaultdict(lambda: dict(status=None, sup=None, pi=None, lines={}, item2n={}, total=None, dep_pct=0,
                                            ccy=None, placed=None, shipped={}, hbls={}, deposit=False, etd=None))
SH = collections.defaultdict(lambda: dict(status=None, hbl=None, container=None, pos=set(), delivered=False, atd=None,
                                          origin=None, dest=None, lines={}))
SUPSTATE = collections.defaultdict(dict)
pi2po = {}
TX = []

def doc_of(e):
    return [{'e': ['document/hash', e['hash']], 'a': 'document/url', 'v': e['url']},
            {'e': ['document/hash', e['hash']], 'a': 'document/issued_at', 'v': iso(e['t'])}]

def emit(e, conf, facts):
    facts = [f for f in facts if f is not None]
    if facts:
        TX.append(dict(hash=e['hash'], url=e['url'], issued=iso(e['t']), conf=str(conf), facts=facts))

def F(ent, a, v):
    return {'e': ent, 'a': a, 'v': v}

def POe(n): return ['po/number', n]
def POLe(n, i): return ['po_line/key', f'{n}/{i}']

def set_status(po, new, facts):
    cur = PO[po]['status']
    if cur is None or RANK.index(new) > RANK.index(cur):
        PO[po]['status'] = new
        facts.append(F(POe(po), 'po/status', new))
        return True
    return False

def set_sstatus(key, new, facts):
    cur = SH[key]['status']
    if cur is None or SRANK.index(new) > SRANK.index(cur):
        SH[key]['status'] = new
        facts.append(F(SHIPKEY[key], 'shipment/status', new))
        return True
    return False

SHIPKEY = {}
def shipent(hbl=None, so=None):
    ent = SHIP(hbl, so)
    key = ent[1]
    SHIPKEY[key] = ent
    return key, ent

def dtz(code):
    return TZ_OF['CN'] if code.startswith('CN') else TZ_OF[code]

def at_port(d, code):
    return dt.datetime(d.year, d.month, d.day, tzinfo=dtz(code))

def check_shipped(po, facts, atd=None):
    p = PO[po]
    if RANK.index(p['status'] or 'draft') >= RANK.index('shipped'):
        return
    ok = False
    if p['lines']:
        ok = all(sum(p['shipped'].get(n, 0) for _ in [0]) >= float(l['qty']) for n, l in p['lines'].items())
    if not ok:
        bk = [b for b in bookings.values() if po in b['d']['pos']]
        if bk and all(hbl2so_rev.get(b['d']['so']) and any(h in SEEN_HBL for h in hbl2so_rev[b['d']['so']]) for b in bk):
            ok = True
    if ok:
        set_status(po, 'shipped', facts)

hbl2so_rev = collections.defaultdict(list)
for h, s in hbl2so.items(): hbl2so_rev[s].append(h)
SEEN_HBL = set()

def ship_lines(e, hbl, rows, facts, src):
    """rows: (po, item, qty, ctns). Adds shipment lines; returns list of POs touched."""
    touched = []
    for po, item, qty, ctns in rows:
        p = PO[po]
        n = p['item2n'].get(item)
        if n is None:
            rep('unresolved', f'{src}: {po} item {item} not on PO lines')
            continue
        key = f'{hbl}/{po}/{n}'
        prev = SH_LINES.get(key)
        if prev and (prev[0] != qty or prev[1] != ctns):
            rep('conflict', f'{src}: shipment line {key} qty/ctns {prev} vs {(qty, ctns)}')
        SH_LINES[key] = (qty, ctns)
        facts += [F(['shipment_line/key', key], 'core/part_of', SHIPENT_FOR[hbl]),
                  F(['shipment_line/key', key], 'shipment_line/po_line', POLe(po, n)),
                  F(['shipment_line/key', key], 'shipment_line/quantity', qty),
                  F(['shipment_line/key', key], 'shipment_line/cartons', ctns)]
        if not prev:
            p['shipped'][n] = p['shipped'].get(n, 0) + float(qty)
        else:
            p['shipped'][n] = p['shipped'].get(n, 0) - float(prev[0]) + float(qty)
        p['hbls'][hbl] = True
        if po not in touched: touched.append(po)
    return touched

SH_LINES = {}
SHIPENT_FOR = {}

def slip_date(msg_t, m, d):
    cn = msg_t.astimezone(CN).date()
    y = cn.year
    c = dt.date(y, m, d)
    if c < cn: c = dt.date(y + 1, m, d)
    return c

pending = collections.defaultdict(list)
last_other_me = {}

for e in events:
    k = e['kind']
    # ---------------- PI
    if k == 'pi':
        d = e['d']; po = d['po']; p = PO[po]
        p.update(sup=d['sup'], pi=d['pi'], total=float(d['total']), dep_pct=d['dep_pct'], ccy=d['ccy'], etd=d['etd'])
        pi2po[(d['sup'], d['pi'])] = po
        facts = doc_of(e)
        facts += [F(POe(po), 'po/pi_number', d['pi']), F(POe(po), 'po/supplier', ['supplier/code', d['sup']]),
                  F(POe(po), 'po/etd', d['etd'].isoformat()), F(POe(po), 'core/currency', d['ccy'])]
        set_status(po, 'confirmed', facts)
        for i, r in enumerate(d['rows'], 1):
            code = f"{d['sup']}:{r['item']}"
            if code not in items_in_store: rep('unresolved', f'{e["url"]}: item code {code} has no SKU')
            p['lines'][i] = dict(item=r['item'], qty=r['qty']); p['item2n'][r['item']] = i
            facts += [F(POLe(po, i), 'core/part_of', POe(po)), F(POLe(po, i), 'po_line/sku', ['factory/item_code', code]),
                      F(POLe(po, i), 'po_line/quantity', r['qty']), F(POLe(po, i), 'po_line/unit_price', r['price'])]
        s = ['supplier/code', d['sup']]
        sv = dict(name_cn=d['name_cn'], name=d['bene'], address=d['address'], incoterm=d['incoterm'],
                  payment_terms=d['payment'], currency=d['ccy'], port=d['port'])
        for a, v in sv.items():
            if SUPSTATE[d['sup']].get(a) != v:
                if a in SUPSTATE[d['sup']]: rep('info', f'supplier {d["sup"]} {a} changed {SUPSTATE[d["sup"]][a]!r} -> {v!r} at {e["url"]}')
                SUPSTATE[d['sup']][a] = v
                facts.append(F(s, 'supplier/' + a, v))
        emit(e, 1, facts)
    # ---------------- CI
    elif k == 'ci':
        d = e['d']; hbl = d['hbl']; po = d['po']
        key, ent = shipent(hbl)
        SHIPENT_FOR[hbl] = ent
        sh = SH[key]
        facts = doc_of(e)
        facts.append(F(ent, 'shipment/hbl', hbl))
        if d['container'] != 'LCL': facts.append(F(ent, 'shipment/container_no', d['container']))
        facts += [F(ent, 'shipment/vessel', d['vessel']), F(ent, 'shipment/origin', d['origin']), F(ent, 'shipment/destination', d['dest'])]
        sh.update(origin=d['origin'], dest=d['dest'], hbl=hbl)
        rows = []
        for r in d['rows']:
            rows.append((po, r['item'], r['qty'], d['ctns'][r['item']]))
            c = f"{PO[po]['sup']}:{r['item']}"
            if c in hs_store and hs_store[c] != r['hs']:
                rep('hs', f'{e["url"]}: {c} invoice HS {r["hs"]} vs SKU HS {hs_store[c]}')
        touched = ship_lines(e, hbl, rows, facts, e['url'])
        SEEN_HBL.add(hbl)
        for tp in touched:
            check_shipped(tp, facts)
        emit(e, 1, facts)
    # ---------------- inspection
    elif k == 'lci':
        d = e['d']; po = d['po']
        facts = doc_of(e)
        q = ['qc/report_no', d['report']]
        facts += [F(q, 'qc/po', POe(po)), F(q, 'qc/inspected_on', d['date'].isoformat()), F(q, 'qc/result', d['result']),
                  F(q, 'qc/inspector', d['agency']), F(q, 'qc/sample_size', d['sample'])]
        if d['result'] == 'PASS':
            set_status(po, 'ready', facts)
        emit(e, 1, facts)
    # ---------------- chat
    elif k == 'chat':
        sup = e['sup']; tx = e['text']; ny_date = e['t'].date()
        if e['me']:
            m = re.search(r'(PO-\d{4}-\d{4})', tx)
            if tx.startswith('['):
                continue
            if m and re.search(r'for \d+ items|new PO|here\'s PO', tx):
                po = m.group(1)
                PO[po]['sup'] = PO[po]['sup'] or sup
                facts = doc_of(e) + [F(POe(po), 'po/placed_on', ny_date.isoformat()), F(POe(po), 'po/supplier', ['supplier/code', sup])]
                if PO[po]['placed']: rep('conflict', f'{po} placed twice')
                PO[po]['placed'] = ny_date
                emit(e, 1, facts)
            elif re.search(r'deposit for (PO-\d{4}-\d{4}) \((\w+) ([\d,]+\.\d\d)\)', tx):
                m = re.search(r'deposit for (PO-\d{4}-\d{4}) \((\w+) ([\d,]+\.\d\d)\)', tx)
                po = m.group(1)
                exp = round(PO[po]['total'] * PO[po]['dep_pct'] / 100, 2) if PO[po]['total'] else None
                if exp is None or abs(exp - float(num(m.group(3)))) > 0.011:
                    rep('conflict', f'{e["url"]}: deposit {m.group(3)} vs expected {exp} for {po}')
                pending[sup].append(dict(po=po, t=e['t'], conf=0.9, how='named', other=False, url=e['url']))
            elif re.search(r'Deposit paid today, (\w+) ([\d,]+\.\d\d)', tx):
                m = re.search(r'Deposit paid today, (\w+) ([\d,]+\.\d\d)', tx)
                amt = float(num(m.group(2)))
                cands = [po for po, p in PO.items() if p['sup'] == sup and p['total'] and p['dep_pct'] and p['pi']
                         and abs(round(p['total'] * p['dep_pct'] / 100, 2) - amt) < 0.011 and not p['deposit']]
                if len(cands) == 1:
                    PO[cands[0]]['deposit'] = True
                    pending[sup].append(dict(po=cands[0], t=e['t'], conf=0.9, how='amount', other=False, url=e['url']))
                else:
                    rep('unresolved', f'{e["url"]}: deposit {amt} candidates {cands}')
                    pending[sup].append(dict(po=None, t=e['t'], conf=0.9, how='unresolved', other=False, url=e['url']))
            elif re.search(r'Balance|QC passed|QC failed|Inspection passed|Understood|Again\?\?|Ok noted|Sorry can you type', tx):
                pass
            else:
                for pd in pending[sup]: pd['other'] = True
            if m and 'deposit for' in tx:
                PO[m.group(1)]['deposit'] = True
        else:
            # supplier message
            if re.search(r'定金收到了|Received, thank you|收到，谢谢', tx):
                if not pending[sup]:
                    rep('info', f'{e["url"]}: acknowledgement with no pending deposit: {tx!r}')
                    continue
                pd = pending[sup].pop(0)
                if pd['po'] is None:
                    continue
                gap = (e['t'] - pd['t']).days
                conf = pd['conf'] if not pd['other'] else 0.8
                if gap > 4: rep('info', f'{e["url"]}: ack {gap} days after deposit {pd["url"]}')
                facts = doc_of(e); n0 = len(facts)
                set_status(pd['po'], 'in_production', facts)
                if len(facts) > n0:
                    emit(e, conf, facts)
                else:
                    rep('info', f'{e["url"]}: ack of {pd["po"]} deposit, PO already {PO[pd["po"]]["status"]}')
            elif '大货生产中' in tx:
                cands = [po for po, p in PO.items() if p['sup'] == sup and p['pi'] and p['deposit'] and RANK.index(p['status']) < RANK.index('ready')]
                cands.sort()
                if len(cands) == 1:
                    facts = doc_of(e); n0 = len(facts)
                    set_status(cands[0], 'in_production', facts)
                    if len(facts) > n0: emit(e, 0.8, facts)
                    else: rep('info', f'{e["url"]}: production started for {cands[0]} - already {PO[cands[0]]["status"]}')
                else:
                    rep('unresolved', f'{e["url"]}: production started, candidates {cands}')
            elif re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', tx) or re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', tx) \
                    or re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货', tx):
                m = re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', tx) or re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', tx)
                if m:
                    po = m.group(1)
                else:
                    m = re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货', tx)
                    po = pi2po.get((sup, m.group(1)))
                    if not po:
                        rep('unresolved', f'{e["url"]}: PI {m.group(1)} not found'); continue
                newd = slip_date(e['t'], int(m.group(2)), int(m.group(3)))
                if RANK.index(PO[po]['status'] or 'draft') >= RANK.index('shipped'):
                    rep('info', f'{e["url"]}: ETD change for already shipped {po} ignored'); continue
                if PO[po]['etd'] and newd <= PO[po]['etd']:
                    rep('info', f'{e["url"]}: ETD change to {newd} not later than {PO[po]["etd"]} for {po}')
                PO[po]['etd'] = newd
                emit(e, 0.85, doc_of(e) + [F(POe(po), 'po/etd', newd.isoformat())])
            elif re.search(r'已装柜 container loaded: (\w+)|Container (\w+) loaded today', tx):
                m = re.search(r'已装柜 container loaded: (\w+)|Container (\w+) loaded today', tx)
                cont = m.group(1) or m.group(2)
                hbl = cont2hbl.get(cont)
                if not hbl:
                    rep('unresolved', f'{e["url"]}: container {cont} matches no CI/pre-alert'); continue
                pos = hbl_info[hbl]['pos']
                if not any(PO[p_]['sup'] == sup for p_ in pos):
                    rep('conflict', f'{e["url"]}: container {cont} not for this supplier')
                key, ent = shipent(hbl)
                emit(e, 0.9, doc_of(e) + [F(ent, 'shipment/container_no', cont)])
            elif re.search(r'ETD around|交期|^ETD \d', tx):
                m = re.search(r'(\d+)月(\d+)号|ETD (?:around )?(\d+)/(\d+)', tx)
                mo, da = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(3)), int(m.group(4)))
                # compare with the latest PI of this supplier before this message
                last = [x for x in docs if x['kind'] == 'pi' and x['d']['sup'] == sup and x['t'] <= e['t']]
                if last:
                    pe = last[-1]['d']['etd']
                    if (pe.month, pe.day) != (mo, da):
                        rep('conflict', f'{e["url"]}: chat ETD {mo}/{da} differs from PI {last[-1]["d"]["pi"]} ETD {pe}')
    # ---------------- email
    elif k == 'booking':
        d = e['d']; so = d['so']
        key, ent = shipent(None, so)
        sh = SH[key]
        sh.update(origin=d['pol'], dest=d['pod'])
        facts = doc_of(e) + [F(ent, 'shipment/mode', d['mode']), F(ent, 'shipment/vessel', d['vessel']),
                             F(ent, 'shipment/origin', d['pol']), F(ent, 'shipment/destination', d['pod']),
                             F(ent, 'shipment/etd', iso(at_port(d['etd'], d['pol']))),
                             F(ent, 'shipment/eta', iso(at_port(d['eta'], d['pod'])))]
        set_sstatus(key, 'booked', facts)
        sh['pos'].update(d['pos'])
        emit(e, 1, facts)
    elif k == 'roll':
        d = e['d']; key, ent = shipent(None, d['so'])
        sh = SH[key]
        if sh['status'] and SRANK.index(sh['status']) >= 1:
            rep('info', f'{e["url"]}: roll after departure ignored'); continue
        emit(e, 1, doc_of(e) + [F(ent, 'shipment/etd', iso(at_port(d['etd'], sh['origin']))),
                                 F(ent, 'shipment/eta', iso(at_port(d['eta'], sh['dest'])))])
    elif k == 'prealert':
        d = e['d']; hbl = d['hbl']
        key, ent = shipent(hbl)
        SHIPENT_FOR[hbl] = ent
        sh = SH[key]
        origin = sh['origin'] or hbl_info[hbl]['origin']; dest = sh['dest'] or hbl_info[hbl]['dest']
        sh['origin'], sh['dest'] = origin, dest
        facts = doc_of(e) + [F(ent, 'shipment/hbl', hbl)]
        if d['container'] != 'LCL': facts.append(F(ent, 'shipment/container_no', d['container']))
        facts += [F(ent, 'shipment/vessel', d['vessel']),
                  F(ent, 'shipment/etd', iso(at_port(d['atd'], origin))),
                  F(ent, 'shipment/eta', iso(at_port(d['eta'], dest)))]
        sh['atd'] = d['atd']
        set_sstatus(key, 'departed', facts)
        rows = [(l['po'], l['item'], l['qty'], l['ctns']) for l in d['lines']]
        touched = ship_lines(e, hbl, rows, facts, e['url'])
        SEEN_HBL.add(hbl)
        for tp in touched:
            sh['pos'].add(tp)
            check_shipped(tp, facts)
            if RANK.index(PO[tp]['status']) >= RANK.index('shipped'):
                atds = [SH[kk]['atd'] for kk in SH if tp in SH[kk]['pos'] and SH[kk]['atd']]
                latest = max(atds)
                facts.append(F(POe(tp), 'po/etd', latest.isoformat())); PO[tp]['etd'] = latest
        emit(e, 1, facts)
    elif k in ('eta', 'arrival'):
        d = e['d']; hbl = d['hbl']
        key, ent = shipent(hbl)
        sh = SH[key]
        if k == 'eta':
            if sh['status'] in ('arrived', 'delivered'):
                rep('info', f'{e["url"]}: ETA update after arrival ignored'); continue
            emit(e, 1, doc_of(e) + [F(ent, 'shipment/eta', iso(at_port(d['eta'], sh['dest'])))])
        else:
            dest = 'USNYC' if d['port'].startswith('New York') else 'USLAX'
            if sh['dest'] and sh['dest'] != dest: rep('conflict', f'{e["url"]}: arrival port {dest} vs shipment {sh["dest"]}')
            facts = doc_of(e) + [F(ent, 'shipment/eta', iso(at_port(d['date'], dest)))]
            set_sstatus(key, 'arrived', facts)
            emit(e, 1, facts)
    elif k == 'receipt':
        d = e['d']; ref = d['ref']
        hbl = ref if ref.startswith('PBLHB') else cont2hbl.get(ref)
        if not hbl: rep('unresolved', f'{e["url"]}: receipt for {ref} matches no shipment'); continue
        key, ent = shipent(hbl)
        sh = SH[key]
        facts = doc_of(e) + [F(ent, 'shipment/delivered_at', iso(e['t']))]
        set_sstatus(key, 'delivered', facts)
        sh['delivered'] = True
        for po, p in PO.items():
            if hbl in p['hbls']:
                shs = [h for h in p['hbls']]
                if all(SH[shipent(h)[0]]['delivered'] for h in shs):
                    set_status(po, 'received', facts)
        if d['disc']:
            rep('warehouse', f'{d["rcv"]} ({ref}): ' + '; '.join(f'{a} exp {b} rec {c} dmg {x}' for a, b, c, x in d['disc']))
        emit(e, 1, facts)
    elif k == 'entry':
        d = e['d']; ref = d['ref']
        hbl = ref if ref.startswith('PBLHB') else cont2hbl.get(ref)
        if not hbl: rep('unresolved', f'{e["url"]}: entry for {ref} matches no shipment'); continue
        key, ent = shipent(hbl)
        duty = round(float(d['hts']) + float(d['s301']) + float(d['add']), 2)
        fees = round(float(d['mpf']) + float(d['hmf']), 2)
        if abs(duty + fees - float(d['total'])) > 0.011: rep('conflict', f'{e["url"]}: duty+fees {duty+fees} vs total {d["total"]}')
        c = ['customs/entry_no', d['entry']]
        emit(e, 1, doc_of(e) + [F(c, 'customs/shipment', ent), F(c, 'customs/filed_on', e['t'].date().isoformat()),
                                F(c, 'customs/entered_value', d['value']), F(c, 'customs/duty', f'{duty:.2f}'),
                                F(c, 'customs/fees', f'{fees:.2f}'), F(c, 'core/currency', 'USD')])

# leftover pending deposits
for sup, l in pending.items():
    for pd in l:
        rep('info', f'deposit without acknowledgement: {pd["url"]} {pd["po"]}')

json.dump(dict(tx=TX, report=REPORT), open('plan.json', 'w'), default=str)
print(len(TX), 'transactions;', sum(len(t['facts']) for t in TX), 'facts')
print(collections.Counter(t['conf'] for t in TX))
for k, v in REPORT.items():
    print('##', k, len(v))
    for x in v: print('  ', x)
print('final PO status:', collections.Counter(p['status'] for p in PO.values()))
print('final ship status:', collections.Counter(s['status'] for s in SH.values()))
