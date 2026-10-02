
# ================================================================ chats
WROOT = parse_pdf.ROOT + '/wechat'
HDR = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$')
chat_msgs = []
for f in sorted(glob.glob(WROOT + '/*.txt')):
    base = os.path.basename(f)[:-4]; code = CHATSUP[base]
    lines = open(f, encoding='utf-8').read().split('\n')
    n = 0; i = 0
    while i < len(lines):
        m = HDR.match(lines[i])
        if m:
            blk = [lines[i]]; i += 1
            while i < len(lines) and lines[i].strip() != '': blk.append(lines[i]); i += 1
            n += 1
            ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            chat_msgs.append(dict(code=code, file=os.path.basename(f), n=n, t=ts, sender=m.group(2), text='\n'.join(blk[1:]),
                                  hash=hashlib.sha256(('\n'.join(blk) + '\n').encode('utf-8')).hexdigest(),
                                  url=f'wechat/{os.path.basename(f)}#{n}'))
        else: i += 1
chat_msgs.sort(key=lambda m: m['t'])

pis = [p for p in PDFS if p['kind'] == 'pi']
for p in pis: p['code'] = PREFIX[re.match(r'([A-Z]{2})', p['file']).group(1)]
pi_no2po = {p['pi']: p['po'] for p in pis}
po2pi = {p['po']: p for p in pis}

def next_occurrence(msg_t, mo, d):
    base = msg_t.astimezone(SH).date()
    for y in (base.year, base.year + 1):
        try: c = date(y, mo, d)
        except ValueError: continue
        if c >= base: return c

intents = []   # (t, order, kind, data, msg)
# deposit -> ack linking per chat
by_chat = {}
for m in chat_msgs: by_chat.setdefault(m['file'], []).append(m)
ACK = ('Received, thank you', '收到，谢谢', '定金收到了，马上安排生产')
for fname, ms in by_chat.items():
    code = ms[0]['code']; last_pay = None; last_pi = None; pend = None
    for m in ms:
        tx = m['text']; maya = m['sender'].startswith('Maya')
        mo = re.search(r'\[文件\] (\S+)\.pdf', tx)
        if mo and not maya and mo.group(1) in pi_no2po: last_pi = mo.group(1)
        if maya:
            mm = re.match(r'Hi (?:\w+),? new PO (PO-\d{4}-\d{4}) attached|Hi \w+! PO (PO-\d{4}-\d{4}) for \d+ items|\w+, here\'s (PO-\d{4}-\d{4})\.', tx)
            if mm:
                po = [g for g in mm.groups() if g][0]
                intents.append((m['t'], 'placed', dict(po=po, code=code), m))
            d1 = re.search(r'Deposit paid today, (USD|CNY) ([\d,]+\.\d\d)', tx)
            d2 = re.search(r'deposit for (PO-\d{4}-\d{4}) \((USD|CNY) ([\d,]+\.\d\d)\)', tx)
            if d1 or d2:
                if d2: po = d2.group(1)
                else:
                    amt = Decimal(d1.group(2).replace(',', '')); cands = []
                    for p in pis:
                        if p['code'] != code or CUR[p['items'][0]['cur']] != d1.group(1): continue
                        pct = Decimal(re.search(r'(\d+)% deposit', p['pay']).group(1)) / 100
                        tot = Decimal(p['total'][1].replace(',', ''))
                        if (tot * pct).quantize(Decimal('0.01')) == amt: cands.append(p['po'])
                    if len(cands) == 1: po = cands[0]
                    else: po = None; anom(f'{m["url"]}: deposit {amt} resolves to {cands}')
                last_pay = ('deposit', po, m); pend = po
            elif re.search(r'Balance (paid )?for', tx): last_pay = ('balance', None, m)
        else:
            if tx in ACK and pend and (tx == ACK[2] or (last_pay and last_pay[0] == 'deposit')):
                intents.append((m['t'], 'inprod', dict(po=pend), m)); pend = None; last_pay = None
            # ETD change messages
            e1 = re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', tx)
            e2 = re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', tx)
            e3 = re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货', tx)
            if e1 or e2:
                g = e1 or e2; intents.append((m['t'], 'etd', dict(po=g.group(1), date=next_occurrence(m['t'], int(g.group(2)), int(g.group(3))), via='po'), m))
            elif e3:
                po = pi_no2po[e3.group(1)]
                intents.append((m['t'], 'etd', dict(po=po, date=next_occurrence(m['t'], int(e3.group(2)), int(e3.group(3))), via='pi'), m))
            e4 = re.fullmatch(r'ETD (\d+)/(\d+)|交期(\d+)月(\d+)号左右|交期(\d+)月(\d+)号左右|ETD around (\d+)/(\d+)|交期(\d+)月(\d+)号左右，ETD around (\d+)/(\d+)', tx)
            e5 = re.match(r'(?:ETD (\d+)/(\d+))|(?:交期(\d+)月(\d+)号)', tx)
            if e5 and last_pi:
                g = [x for x in e5.groups() if x]; dd = next_occurrence(m['t'], int(g[0]), int(g[1]))
                pidate_ = pidate(po2pi[pi_no2po[last_pi]]['etd'])
                if dd != pidate_: anom(f'{m["url"]}: chat ETD {dd} differs from {last_pi} printed ETD {pidate_}')
            e6 = re.search(r'container loaded: (\w{4}\d{7}) seal', tx)
            if e6: intents.append((m['t'], 'container', dict(cont=e6.group(1), code=code), m))

# ================================================================ unified timeline
timeline = []
for p in PDFS:
    t = datetime.fromisoformat(p['date']).replace(tzinfo=SH)
    timeline.append((t, {'pi': 0, 'qc': 2, 'ci': 3}[p['kind']], 'pdf', p))
for t, k, d, m in intents: timeline.append((t, 1, 'intent', (k, d, m)))
for m in MAILS: timeline.append((datetime.fromisoformat(m['t']), 4, 'mail', m))
timeline.sort(key=lambda x: (x[0], x[1]))

# ================================================================ state
PO = dict(status={}, sup={}, lines={}, qty={}, etd={}, cur={})
SHIP = {}
def sstate(hbl=None, so=None):
    if hbl and hbl in hbl2so: so = hbl2so[hbl]
    if so and so in so2hbl: hbl = so2hbl[so]
    k = hbl or so
    return SHIP.setdefault(k, dict(hbl=hbl, so=so, hw=False, sw=False, status=None, origin=None, dest=None, sailed=False,
                                   delivered=False, lines={}, pos=set()))
def saddr(st, facts, via):
    """lookup for a shipment; asserts the second identifier the first time it is known; via = identifiers the document gives"""
    if st['sw']:
        e = ["shipment/booking_no", st['so']]
        if st['hbl'] and not st['hw'] and via == 'hbl':
            facts.append(A(e, 'shipment/hbl', st['hbl'])); st['hw'] = True
        return e
    if st['hw']: return ["shipment/hbl", st['hbl']]
    if via == 'hbl' and st['hbl']:
        e = ["shipment/hbl", st['hbl']]; st['hw'] = True
        if st['so']: facts.append(A(e, 'shipment/booking_no', st['so'])); st['sw'] = True
        return e
    if st['so']: st['sw'] = True; return ["shipment/booking_no", st['so']]
    return None
def sadvance(st, facts, e, new):
    if st['status'] is None or SH_RANK[new] > SH_RANK[st['status']]:
        st['status'] = new; facts.append(A(e, 'shipment/status', new))

def out(t, label, h, url, conf_facts_list):
    issued = t.isoformat()
    groups = [(c, group(h, url, issued, c, f)) for c, f in conf_facts_list if f]
    if groups: events.append(dict(t=issued, label=label, groups=groups))

diag = []
def line_key(po, item):
    return PO['lines'].get(po, {}).get(item)

def shipped_check(po, pa_facts, atd):
    """is every ordered unit loaded, or every booking carrying the PO sailed?"""
    qty_ok = all(sum(sh['lines'].get(k, (0, 0))[0] for sh in SHIP.values()) >= q for k, q in PO['qty'][po].items())
    bks = [st for st in SHIP.values() if po in st['pos']]
    book_ok = bool(bks) and all(st['sailed'] for st in bks)
    diag.append((po, qty_ok, book_ok))
    return qty_ok, book_ok

recv_lines = {}
for t, _, kind, obj in timeline:
    if kind == 'pdf' and obj['kind'] == 'pi':
        p = obj; po = p['po']; code = p['code']; cur = CUR[p['items'][0]['cur']]
        f = [A(POe(po), 'po/pi_number', p['pi']), A(POe(po), 'po/supplier', ["supplier/code", code]), A(POe(po), 'core/currency', cur),
             A(POe(po), 'po/etd', pidate(p['etd']).isoformat())]
        PO['sup'][po] = code; PO['cur'][po] = cur; PO['etd'][po] = pidate(p['etd'])
        cur_status = PO['status'].get(po)
        if cur_status is None or PO_RANK['confirmed'] > PO_RANK[cur_status]: PO['status'][po] = 'confirmed'; f.append(A(POe(po), 'po/status', 'confirmed'))
        lines, qty = {}, {}
        for n, it in enumerate(p['items'], 1):
            key = f'{po}/{n}'; ic = f"{code}:{it['item']}"
            if ic not in store_sku: anom(f'{p["file"]}: item {ic} has no SKU in store'); continue
            le = ["po_line/key", key]
            f += [A(le, 'core/part_of', POe(po)), A(le, 'po_line/sku', ["factory/item_code", ic]),
                  A(le, 'po_line/quantity', str(it['qty'])), A(le, 'po_line/unit_price', it['price'].replace(',', ''))]
            lines[it['item']] = key; qty[key] = it['qty']
        PO['lines'][po] = lines; PO['qty'][po] = qty
        sup = ["supplier/code", code]
        tt = open(f"{parse_pdf.TXT}/{p['file']}.txt").read()
        f += [A(sup, 'supplier/name', re.search(r'Beneficiary: (.+)', tt).group(1).strip()), A(sup, 'supplier/name_cn', p['name_cn']),
              A(sup, 'supplier/address', p['address']), A(sup, 'supplier/incoterm', f"{p['term'][0]} {p['term'][1]}"),
              A(sup, 'supplier/payment_terms', p['pay'].replace('T/T ', '', 0)), A(sup, 'supplier/currency', cur),
              A(sup, 'supplier/port', {'Ningbo': 'CNNGB', 'Yantian': 'CNYTN', 'Nansha': 'CNNSA', 'Xiamen': 'CNXMN'}[p['term'][1]])]
        out(t, p['file'], p['hash'], p['url'], [(1, f)])

    elif kind == 'pdf' and obj['kind'] == 'qc':
        p = obj; po = p['po']
        f = [A(["qc/report_no", p['report']], 'qc/po', POe(po)), A(["qc/report_no", p['report']], 'qc/inspected_on', p['date']),
             A(["qc/report_no", p['report']], 'qc/result', p['result']),
             A(["qc/report_no", p['report']], 'qc/inspector', p['agency'].title()),
             A(["qc/report_no", p['report']], 'qc/sample_size', str(p['sample']))]
        if p['result'] == 'PASS':
            cs = PO['status'].get(po)
            if cs is None or PO_RANK['ready'] > PO_RANK[cs]: PO['status'][po] = 'ready'; f.append(A(POe(po), 'po/status', 'ready'))
        out(t, p['file'], p['hash'], p['url'], [(1, f)])

    elif kind == 'pdf' and obj['kind'] == 'ci':
        p = obj; hbl = p['bl']; st = sstate(hbl=hbl); po = p['inv'][2]
        f = []; e = saddr(st, f, 'hbl')
        if p['cont'] != 'LCL': f.append(A(e, 'shipment/container_no', p['cont']))
        f += [A(e, 'shipment/vessel', p['vessel']), A(e, 'shipment/origin', p['from']), A(e, 'shipment/destination', p['to'])]
        st['origin'], st['dest'] = p['from'], p['to']; st['pos'].add(po)
        for it in p['items']:
            key = line_key(po, it['item'])
            if not key: anom(f'{p["file"]}: {po} has no line for {it["item"]}'); continue
            sk = f"{PO['sup'][po]}:{it['item']}"
            if store_sku.get(sk) and store_sku[sk] != it['hs']: anom(f'{p["file"]}: HS code {it["hs"]} differs from SKU {sk} HS {store_sku[sk]}')
            if store_sku.get(sk) is None and sk in store_sku:
                f.append(A(["factory/item_code", sk], 'sku/hs_code', it['hs']))
            le = ["shipment_line/key", f'{hbl}/{key}']
            f += [A(le, 'core/part_of', e), A(le, 'shipment_line/po_line', ["po_line/key", key]), A(le, 'shipment_line/quantity', str(it['qty'])),
                  A(le, 'shipment_line/cartons', str(p['ctns'][it['item']]))]
            st['lines'][key] = (it['qty'], p['ctns'][it['item']])
        st['ci_seen'] = True
        out(t, p['file'], p['hash'], p['url'], [(1, f)])

    elif kind == 'intent':
        k, d, m = obj
        if k == 'placed':
            po = d['po']
            f = [A(POe(po), 'po/placed_on', m['t'].date().isoformat()), A(POe(po), 'po/supplier', ["supplier/code", d['code']])]
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
        elif k == 'etd':
            po = d['po']
            if PO['status'].get(po) in ('shipped', 'received'): anom(f'{m["url"]}: ETD change for already shipped {po}'); continue
            if PO['etd'].get(po) == d['date']: continue
            PO['etd'][po] = d['date']
            out(t, m['url'], m['hash'], m['url'], [(0.9, [A(POe(po), 'po/etd', d['date'].isoformat())])])
        elif k == 'inprod':
            po = d['po']; f = []
            cs = PO['status'].get(po)
            if cs is None or PO_RANK['in_production'] > PO_RANK[cs]:
                PO['status'][po] = 'in_production'; f.append(A(POe(po), 'po/status', 'in_production'))
            out(t, m['url'], m['hash'], m['url'], [(0.9, f)])
        elif k == 'container':
            hbl = cont2hbl.get(d['cont'])
            if not hbl: anom(f'{m["url"]}: container {d["cont"]} not found on any HBL'); continue
            st = sstate(hbl=hbl)
            if not (st['sw'] or st['hw']):
                if st['so']: pass
                else: anom(f'{m["url"]}: no shipment yet for container {d["cont"]}'); continue
            f = []; e = saddr(st, f, 'so') if not st['hw'] else ["shipment/hbl", hbl]
            if e is None: anom(f'{m["url"]}: no shipment yet for container {d["cont"]}'); continue
            f.append(A(e, 'shipment/container_no', d['cont']))
            out(t, m['url'], m['hash'], m['url'], [(0.9, f)])

    elif kind == 'mail':
        m = obj; k = m['kind']; b = m['body']; dd = m.get('d')
        if k == 'booking':
            st = sstate(so=dd['so']); f = []; e = saddr(st, f, 'so')
            if not st['sw']: f.append(A(e, 'shipment/booking_no', st['so'])); st['sw'] = True; anom(f'{m["url"]}: booking arrived after its HBL shipment existed')
            f += [A(e, 'shipment/mode', dd['mode']), A(e, 'shipment/vessel', dd['vessel']), A(e, 'shipment/origin', dd['origin']),
                  A(e, 'shipment/destination', dd['dest']), A(e, 'shipment/etd', local_midnight(dd['etd'], dd['origin'])),
                  A(e, 'shipment/eta', local_midnight(dd['eta'], dd['dest']))]
            st['origin'], st['dest'] = dd['origin'], dd['dest']; st['pos'] |= dd['pos']
            sadvance(st, f, e, 'booked')
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
        elif k == 'roll':
            so = re.search(r'SO (\S+)', b).group(1); st = sstate(so=so)
            ed = pdate(re.search(r'New ETD (\d+ \w+ \d{4})', b).group(1)); ea = pdate(re.search(r'ETA (\d+ \w+ \d{4})', b).group(1))
            f = []; e = saddr(st, f, 'so')
            f += [A(e, 'shipment/etd', local_midnight(ed, st['origin'])), A(e, 'shipment/eta', local_midnight(ea, st['dest']))]
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
        elif k == 'prealert':
            hbl = dd['hbl']; st = sstate(hbl=hbl); f = []; e = saddr(st, f, 'hbl')
            if dd['cont']: f.append(A(e, 'shipment/container_no', dd['cont']))
            if not st['origin']:
                f += [A(e, 'shipment/origin', dd['origin']), A(e, 'shipment/destination', dd['dest'])]; st['origin'], st['dest'] = dd['origin'], dd['dest']
            elif (st['origin'], st['dest']) != (dd['origin'], dd['dest']): anom(f'{m["url"]}: ports differ {st["origin"]}/{st["dest"]} vs {dd["origin"]}/{dd["dest"]}')
            f += [A(e, 'shipment/etd', local_midnight(dd['atd'], dd['origin'])), A(e, 'shipment/eta', local_midnight(dd['eta'], dd['dest']))]
            sadvance(st, f, e, 'departed'); st['sailed'] = True
            pos = set()
            for po, item, c, q in dd['lines']:
                key = line_key(po, item)
                if not key: anom(f'{m["url"]}: {po} has no line for {item}'); continue
                if key in st['lines'] and st['lines'][key] != (q, c): anom(f'{m["url"]}: {key} pre-alert {q} pcs/{c} ctns vs CI {st["lines"][key]}')
                le = ["shipment_line/key", f'{hbl}/{key}']
                f += [A(le, 'core/part_of', e), A(le, 'shipment_line/po_line', ["po_line/key", key]), A(le, 'shipment_line/quantity', str(q)),
                      A(le, 'shipment_line/cartons', str(c))]
                st['lines'][key] = (q, c); pos.add(po)
            st['pos'] |= pos
            for po in sorted(pos):
                qo, bo = shipped_check(po, f, dd['atd'])
                if qo or bo:
                    cs = PO['status'].get(po)
                    if cs is None or PO_RANK['shipped'] > PO_RANK[cs]:
                        PO['status'][po] = 'shipped'; f.append(A(POe(po), 'po/status', 'shipped')); f.append(A(POe(po), 'po/etd', dd['atd'].isoformat()))
                        PO['etd'][po] = dd['atd']
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
        elif k == 'eta':
            mo = re.search(r'ETA (\d+ \w+ \d{4}) for HBL (\S+)', b); hbl = mo.group(2); st = sstate(hbl=hbl)
            f = []; e = saddr(st, f, 'hbl'); f.append(A(e, 'shipment/eta', local_midnight(pdate(mo.group(1)), st['dest'])))
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
        elif k == 'arrival':
            mo = re.search(r'HBL (\S+) \((\S+)\) on (.+?) is arriving (.+?) on (\d+ \w+ \d{4})', b); hbl = mo.group(1); st = sstate(hbl=hbl)
            port = PORT_NAME[mo.group(4)]
            if port != st['dest']: anom(f'{m["url"]}: arrival port {port} differs from destination {st["dest"]}')
            f = []; e = saddr(st, f, 'hbl'); sadvance(st, f, e, 'arrived')
            f.append(A(e, 'shipment/eta', local_midnight(pdate(mo.group(5)), port)))
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
        elif k == 'receipt':
            ident = re.search(r'Receiving complete for (\S+) under', b).group(1)
            hbl = ident if ident.startswith('PBLHB') else cont2hbl.get(ident)
            if not hbl: anom(f'{m["url"]}: {ident} matches no shipment'); continue
            st = sstate(hbl=hbl); f = []; e = saddr(st, f, 'hbl'); sadvance(st, f, e, 'delivered'); st['delivered'] = True
            f.append(A(e, 'shipment/delivered_at', datetime.fromisoformat(m['t']).isoformat()))
            for po in sorted(st['pos']):
                carriers = [s for s in SHIP.values() if po in s['pos'] and s['lines']]
                if carriers and all(s['delivered'] for s in carriers):
                    cs = PO['status'].get(po)
                    if cs is None or PO_RANK['received'] > PO_RANK[cs]: PO['status'][po] = 'received'; f.append(A(POe(po), 'po/status', 'received'))
            out(t, m['url'], m['hash'], m['url'], [(1, f)])
            disc = re.findall(r'(ACMH-\d+ .*)', b)
            if disc: recv_lines[m['url']] = disc
        elif k == 'entry':
            mo = re.search(r'Entry (\S+) filed for (\S+)\.', b); no, ident = mo.groups()
            hbl = ident if ident.startswith('PBLHB') else cont2hbl.get(ident)
            if not hbl: anom(f'{m["url"]}: {ident} matches no shipment'); continue
            st = sstate(hbl=hbl); f = []; e = saddr(st, f, 'hbl')
            v = lambda lab: Decimal(re.search(lab + r': USD ([\d,.]+)', b).group(1).replace(',', ''))
            duty = v(r'Duty \(HTS\)') + v('Section 301') + v('Additional duties'); fees = v('MPF') + v('HMF')
            tot = v('Total duties and fees')
            if duty + fees != tot: anom(f'{m["url"]}: duty+fees {duty+fees} != total {tot}')
            ce = ["customs/entry_no", no]
            f += [A(ce, 'customs/shipment', e), A(ce, 'customs/filed_on', datetime.fromisoformat(m['t']).date().isoformat()),
                  A(ce, 'customs/entered_value', str(v('Entered value'))), A(ce, 'customs/duty', str(duty)), A(ce, 'customs/fees', str(fees)),
                  A(ce, 'core/currency', 'USD')]
            out(t, m['url'], m['hash'], m['url'], [(1, f)])

json.dump(events, open(os.path.dirname(__file__) + '/events.json', 'w'), ensure_ascii=False)
if __name__ == '__main__':
    print(len(events), 'events,', sum(len(e['groups']) for e in events), 'transactions')
    print('--- anomalies'); [print(a) for a in anomalies]
    print('--- shipped diag (po, qty_ok, bookings_ok)'); [print(d) for d in diag if d[1] != d[2]]
    from collections import Counter
    print(Counter((d[1], d[2]) for d in diag))
    print('final PO status', Counter(PO['status'].values()))
if __name__ == '__main__' and len(sys.argv) > 1:
    for po in sorted(PO['status']): print(po, PO['status'][po], PO['etd'].get(po))
    for k, s in SHIP.items(): print(k, s['status'], sorted(s['pos']), 'delivered' if s['delivered'] else '')
