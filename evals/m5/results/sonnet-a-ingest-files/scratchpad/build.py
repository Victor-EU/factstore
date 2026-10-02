from plan import *
TX = []      # list of dict(doc, conf, facts, ts, kind)
STATUS = {}  # po -> status
POETD = {}   # po -> date asserted
LINES = {}   # po -> {sku code -> (line key, qty)}
POLINES = {} # po -> [line keys]
SHIP_STATE = {}   # shipment id (so or hbl) -> dict(status, departed, eta_loc, linked hbl)
LINKED = set()    # hbl linked to booking entity
SHLINES = {}      # po line key -> {shipment id: qty}
DEPARTED = set()  # shipment ids invoiced or pre-alerted
ATD = {}          # shipment id -> actual departure date
DELIVERED = set()
SHIP_POS = {}     # shipment id -> set of POs (from lines)
DEST = {}         # shipment id -> pod

def sid(hbl): return HBL2SO.get(hbl, hbl)         # shipment id: booking where one exists
def sref(hbl_or_so, via_hbl=False):
    return ['shipment/hbl', hbl_or_so] if via_hbl else ['shipment/booking_no', hbl_or_so]

def tx(ev, facts, conf='1'):
    TX.append(dict(ts=ev['ts'].isoformat(), kind=ev['kind'], doc=ev['doc'], conf=conf, facts=facts))

def po_status(ev, po, new, conf='1'):
    cur = STATUS.get(po)
    if cur is None or RANK[new] > RANK[cur]:
        STATUS[po] = new
        return [dict(e=['po/number', po], a='po/status', v=new)]
    return []

def ensure_link(ev, hbl):
    """booking entity gets the HBL, once. Returns shipment ref to use afterwards."""
    so = HBL2SO.get(hbl)
    if so and hbl not in LINKED:
        LINKED.add(hbl)
        tx(ev, [dict(e=sref(so), a='shipment/hbl', v=hbl)], '0.9' if BOOK_LOOSE.get(hbl) else '1')
    return ['shipment/hbl', hbl]

def po_lines_for(po, items):
    pass

def check_shipped(ev, po, conf='1'):
    carrying = {s for s, p in SHIP_POS.items() if po in p} | {b['so'] for b in BOOK.values() if po in [p for p, _ in b['pos']]}
    out = []
    qty_ok = all(sum(SHLINES.get(k, {}).values()) >= q for k, q in [(LINES[po][c][0], LINES[po][c][1]) for c in LINES[po]]) if po in LINES else False
    if qty_ok or (carrying and carrying <= DEPARTED):
        out += po_status(ev, po, 'shipped')
        return True, out
    return False, out

HAVE = {r[0] for r in factstore.query('select h.v from "core/evidence" ev join "document/hash" h on h.e = ev.v').rows}
SKIPPED = [e for e in EV if e['doc'][0] in HAVE]
for ev in EV:
    k, d = ev['kind'], ev['d']
    if ev['doc'][0] in HAVE: continue
    if k == 'pi':
        po = d['po']; sup = d['sup']
        P = ['po/number', po]
        facts = [dict(e=P, a='po/pi_number', v=d['pi']), dict(e=P, a='po/supplier', v=['supplier/code', sup]),
                 dict(e=P, a='po/etd', v=d['etd_date'].isoformat()), dict(e=P, a='core/currency', v='CNY' if d['cur'] == 'RMB' else d['cur'])]
        facts += po_status(ev, po, 'confirmed')
        if po in LINES: note('PO already has lines when PI read', po)
        LINES[po] = {}; POLINES[po] = []
        for i, it in enumerate(d['items'], 1):
            key = f'{po}/{i}'; L = ['po_line/key', key]
            code = f"{sup}:{it['item']}"
            facts += [dict(e=L, a='core/part_of', v=P), dict(e=L, a='po_line/sku', v=['factory/item_code', code]),
                      dict(e=L, a='po_line/quantity', v=it['qty']), dict(e=L, a='po_line/unit_price', v=it['price'])]
            LINES[po][it['item']] = (key, Decimal(it['qty'])); POLINES[po].append(key)
        S = ['supplier/code', sup]
        txt = open(D + d['file'] + '.txt').read()
        facts += [dict(e=S, a='supplier/name_cn', v=d['name_cn']), dict(e=S, a='supplier/address', v=d['addr']),
                  dict(e=S, a='supplier/incoterm', v=d['incoterm']), dict(e=S, a='supplier/payment_terms', v=d['pay'])]
        tx(ev, facts)
    elif k == 'ci':
        po = d['po']; hbl = d['hbl']
        if po not in LINES: note('CI for PO without PI', d['file'], po); continue
        ref = ensure_link(ev, hbl)
        S = ref
        DEST[sid(hbl)] = d['pod']
        facts = [dict(e=S, a='shipment/vessel', v=d['vessel']), dict(e=S, a='shipment/origin', v=d['pol']), dict(e=S, a='shipment/destination', v=d['pod'])]
        if d['container'] != 'LCL': facts.append(dict(e=S, a='shipment/container_no', v=d['container']))
        SH = sid(hbl)
        for it in d['items']:
            sku = f"{d['sup']}:{it['item']}"
            if ITEM.get(sku) is None: note('CI item not in store', d['file'], sku); continue
            if ITEM[sku] != it['hs']: note('HS CODE DIFFERS from SKU', d['file'], sku, it['hs'], ITEM[sku])
            if it['item'] not in LINES[po]: note('CI item not on PO', d['file'], po, it['item']); continue
            lk, oq = LINES[po][it['item']]
            SL = ['shipment_line/key', f'{hbl}/{lk}']
            if it['item'] not in d['ctns']: note('no packing row', d['file'], it['item'])
            facts += [dict(e=SL, a='core/part_of', v=S), dict(e=SL, a='shipment_line/po_line', v=['po_line/key', lk]),
                      dict(e=SL, a='shipment_line/quantity', v=it['qty'])]
            if it['item'] in d['ctns']: facts.append(dict(e=SL, a='shipment_line/cartons', v=d['ctns'][it['item']]))
            SHLINES.setdefault(lk, {})[SH] = Decimal(it['qty'])
            SHIP_POS.setdefault(SH, set()).add(po)
        tx(ev, facts)
        DEPARTED.add(SH)
        ok, f2 = check_shipped(ev, po)
        if f2: tx(ev, f2)
    elif k == 'qc':
        po = d['po']; Q = ['qc/report_no', d['no']]
        facts = [dict(e=Q, a='qc/po', v=['po/number', po]), dict(e=Q, a='qc/inspected_on', v=d['date']), dict(e=Q, a='qc/result', v=d['res']),
                 dict(e=Q, a='qc/inspector', v=d['agency']), dict(e=Q, a='qc/sample_size', v=d['size'])]
        if po not in PI: note('QC for PO without PI', d['no'], po)
        if d['res'] == 'PASS': facts += po_status(ev, po, 'ready')
        tx(ev, facts)
    elif k == 'booking':
        S = sref(d['so'])
        facts = [dict(e=S, a='shipment/mode', v=d['mode']), dict(e=S, a='shipment/vessel', v=d['vessel']), dict(e=S, a='shipment/origin', v=d['pol']),
                 dict(e=S, a='shipment/destination', v=d['pod']), dict(e=S, a='shipment/etd', v=inst(d['etd'], d['pol'])),
                 dict(e=S, a='shipment/eta', v=inst(d['eta'], d['pod'])), dict(e=S, a='shipment/status', v='booked')]
        DEST[d['so']] = d['pod']
        tx(ev, facts)
    elif k == 'rolled':
        S = sref(d['so']); b = BOOK[d['so']]
        tx(ev, [dict(e=S, a='shipment/etd', v=inst(d['etd'], b['pol'])), dict(e=S, a='shipment/eta', v=inst(d['eta'], b['pod']))])
    elif k == 'prealert':
        hbl = d['hbl']; so = HBL2SO[hbl]; SH = so
        ref = ensure_link(ev, hbl); S = ref
        b = BOOK[so]
        facts = [dict(e=S, a='shipment/etd', v=inst(d['atd'], b['pol'])), dict(e=S, a='shipment/eta', v=inst(d['eta'], b['pod'])), dict(e=S, a='shipment/status', v='departed')]
        if d['container'] != 'LCL': facts.append(dict(e=S, a='shipment/container_no', v=d['container']))
        pos = set()
        for r in d['rows']:
            po = r['po']; pos.add(po)
            sku = f"{PI[po]['sup']}:{r['item']}" if po in PI else None
            if po not in LINES or r['item'] not in LINES[po]: note('pre-alert row has no PO line', hbl, po, r['item']); continue
            lk, oq = LINES[po][r['item']]
            SL = ['shipment_line/key', f'{hbl}/{lk}']
            facts += [dict(e=SL, a='core/part_of', v=S), dict(e=SL, a='shipment_line/po_line', v=['po_line/key', lk]),
                      dict(e=SL, a='shipment_line/quantity', v=r['pcs']), dict(e=SL, a='shipment_line/cartons', v=r['ctns'])]
            SHLINES.setdefault(lk, {})[SH] = Decimal(r['pcs'])
            SHIP_POS.setdefault(SH, set()).add(po)
        tx(ev, facts)
        DEPARTED.add(SH); ATD[SH] = d['atd']
        for po in sorted(pos):
            ok, f2 = check_shipped(ev, po)
            if ok:
                dates = [ATD[s] for s in SHIP_POS if po in SHIP_POS[s] and s in ATD]
                latest = max(dates)
                if POETD.get(po) != latest:
                    POETD[po] = latest; f2.append(dict(e=['po/number', po], a='po/etd', v=latest.isoformat()))
            if f2: tx(ev, f2)
    elif k == 'etaupd':
        hbl = d['hbl']; so = HBL2SO[hbl]
        tx(ev, [dict(e=['shipment/hbl', hbl], a='shipment/eta', v=inst(d['eta'], DEST[so]))])
    elif k == 'arrival':
        hbl = d['hbl']; so = HBL2SO[hbl]
        tx(ev, [dict(e=['shipment/hbl', hbl], a='shipment/status', v='arrived'), dict(e=['shipment/hbl', hbl], a='shipment/eta', v=inst(d['date'], DEST[so]))])
    elif k == 'receipt':
        key = d['key']
        if key.startswith('PBLHB'): hbl = key
        else:
            so = CONT2SO[key]; hbl = SO2HBL[so][0]
        so = HBL2SO[hbl]
        DELIVERED.add(so)
        facts = [dict(e=['shipment/hbl', hbl], a='shipment/status', v='delivered'), dict(e=['shipment/hbl', hbl], a='shipment/delivered_at', v=d['at'])]
        tx(ev, facts)
        for po in sorted(SHIP_POS.get(so, [])):
            carrying = {s for s, p in SHIP_POS.items() if po in p} | {b['so'] for b in BOOK.values() if po in [p for p, _ in b['pos']]}
            if carrying <= DELIVERED:
                f2 = po_status(ev, po, 'received')
                if f2: tx(ev, f2)
    elif k == 'customs':
        key = d['key']
        if key.startswith('PBLHB'): hbl = key
        else: hbl = SO2HBL[CONT2SO[key]][0]
        E = ['customs/entry_no', d['entry']]
        tx(ev, [dict(e=E, a='customs/shipment', v=['shipment/hbl', hbl]), dict(e=E, a='customs/filed_on', v=d['filed']),
                dict(e=E, a='customs/entered_value', v=str(d['value'])), dict(e=E, a='customs/duty', v=str(d['duty'])),
                dict(e=E, a='customs/fees', v=str(d['fees'])), dict(e=E, a='core/currency', v='USD')])
    elif k == 'chat_etd':
        po = d['po']
        if po not in PI: note('chat ETD for PO without PI', po); continue
        POETD[po] = d['etd']
        tx(ev, [dict(e=['po/number', po], a='po/etd', v=d['etd'].isoformat())], d['conf'])
    elif k == 'chat_container':
        cont = d['container']; so = CONT2SO.get(cont)
        if not so: note('chat container without shipment', cont); continue
        sups = {PI[p]['sup'] for p in SHIP_POS.get(so, []) if p in PI} | BOOK[so]['sups']
        if d['sup'] not in sups: note('chat container supplier not on shipment', cont, d['sup'])
        tx(ev, [dict(e=sref(so), a='shipment/container_no', v=cont)], '0.9')
    elif k == 'chat_ack':
        dep = d['dep']; sup = d['sup']
        if dep['po']: po, conf = dep['po'], '0.9'
        else:
            c = [p for p, pi in PI.items() if pi['sup'] == sup and day(pi['date']) <= dep['ts'] and pi['cur'] == ('RMB' if dep['cur'] == 'CNY' else dep['cur'])
                 and abs(sum(Decimal(i['qty']) * Decimal(i['price']) for i in pi['items']) * Decimal(re.search(r'(\d+)% deposit', pi['pay']).group(1)) / 100 - dep['amt']) <= Decimal('0.02')]
            if len(c) != 1: note('DEPOSIT AMOUNT MATCH', sup, dep['amt'], c); continue
            po, conf = c[0], '0.8'
        f = po_status(ev, po, 'in_production')
        if f: tx(ev, f, conf)
    elif k == 'chat_prod':
        sup = d['sup']
        c = [p for p, pi in PI.items() if pi['sup'] == sup and day(pi['date']) <= ev['ts'] and STATUS.get(p) in ('confirmed', 'in_production')]
        if len(c) != 1: note('大货生产中 CANDIDATES', sup, ev['ts'].date(), c); continue
        f = po_status(ev, c[0], 'in_production')
        if f: tx(ev, f, '0.8')

if __name__ == '__main__':
    print(len(TX), 'transactions')
    print('\n'.join(NOTES))
