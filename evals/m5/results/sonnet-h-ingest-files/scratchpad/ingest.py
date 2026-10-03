import re, json, sys, hashlib, datetime as dt, collections
from decimal import Decimal as Dec
from zoneinfo import ZoneInfo
import parse_pdf, mail2
EXP = parse_pdf.EXP
NY, LA, CN = ZoneInfo('America/New_York'), ZoneInfo('America/Los_Angeles'), ZoneInfo('Asia/Shanghai')
PORT_TZ = {'CNYTN': CN, 'CNNGB': CN, 'CNXMN': CN, 'CNNSA': CN, 'USNYC': NY, 'USLAX': LA}
PORT_NAME = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Xiamen': 'CNXMN', 'Nansha': 'CNNSA',
             'New York/Newark': 'USNYC', 'Los Angeles': 'USLAX'}
SUP_CODE = {'HETAI': 'SZHT', 'LANXIN': 'YWLX', 'MINGJIA': 'FSMJ', 'MINGTU': 'NBBW', 'QISHENG': 'NBQS',
            'RUIFENG': 'DGRF', 'TIANYI': 'HZTY', 'YUANDA': 'XMYD'}
CHAT_SUP = {'DGRF': 'DGRF', 'FSMJ': 'FSMJ', 'HZTY': 'HZTY', 'NBBW': 'NBBW', 'NBQS': 'NBQS', 'SZHT': 'SZHT',
            'XMYD': 'XMYD', 'YWLX': 'YWLX'}
MONTHS = {m: i for i, m in enumerate('January February March April May June July August September October November December'.split(), 1)}
ST_ORDER = ['draft', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received']
SH_ORDER = ['booked', 'departed', 'arrived', 'delivered']


def local_midnight(d, port):
    return dt.datetime(d.year, d.month, d.day, tzinfo=PORT_TZ[port]).isoformat()


def iso(t):
    return t.isoformat()


# ---------- events ----------
def load_events():
    ev = []
    for d in parse_pdf.parse_all():
        d['at'] = dt.datetime.fromisoformat(d['date'][:10]).replace(tzinfo=CN)
        if d['kind'] == 'pi':
            d['sc'] = [v for k, v in SUP_CODE.items() if k in d['name_caps']][0]
            d['at'] = dt.datetime.strptime(d['date'], '%Y-%m-%d').replace(tzinfo=CN)
        ev.append(d)
    raw = open(EXP + '/email/ops_inbox.mbox', 'rb').read()
    parts = [p for p in re.split(rb'(?m)^(?=From (?!:))', raw) if p.strip()]
    E = mail2.build()
    assert len(parts) == len(E)
    for p, e in zip(parts, E):
        e['hash'] = hashlib.sha256(p.rstrip(b'\n') + b'\n').hexdigest()
        e['url'] = 'mid:' + e['mid']
        e['at'] = e['date']
        e['kind'] = 'mail_' + e['kind']
        ev.append(e)
    # chats
    for f in sorted(__import__('glob').glob(EXP + '/wechat/*.txt')):
        code = f.split('/')[-1].split('_')[0]
        lines = open(f, encoding='utf-8').read().split('\n')
        msgs = []
        for ln in lines[2:]:
            m = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$', ln)
            if m and (not msgs or True) and re.match(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ', ln):
                msgs.append({'ts': m.group(1), 'head': ln, 'body': []})
            elif msgs:
                msgs[-1]['body'].append(ln)
        for n, m in enumerate(msgs, 1):
            body = list(m['body'])
            while body and body[-1] == '':
                body.pop()
            text = '\n'.join(body)
            raw_msg = '\n'.join([m['head']] + body)
            who = m['head'][20:]
            ev.append(dict(kind='chat', sup=code, n=n, text=text, who=who, file=f.split('/')[-1],
                           at=dt.datetime.strptime(m['ts'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY),
                           hash=hashlib.sha256(raw_msg.encode('utf-8')).hexdigest(),
                           url=f"wechat/{f.split('/')[-1]}#{n}", mine=who.startswith('Maya')))
    for i, e in enumerate(ev):
        e['seq'] = i
    ev.sort(key=lambda e: (e['at'], e['seq']))
    return ev


def norm_po_ref(s, year_hint):
    m = re.search(r'(\d{4})-(\d{4})', s) or re.search(r'PO#(\d{4})-(\d{4})', s)
    if m:
        return f'PO-{m.group(1)}-{m.group(2)}', True
    n = int(re.search(r'(\d+)', s).group(1))
    y = 2025 if n >= 143 else 2026
    return f'PO-{y}-{n:04d}', False


class Run:
    def __init__(self):
        self.txs = []
        self.po = {}          # po -> state
        self.pi_po = {}       # pi number -> po
        self.sku = {}
        self.shipments = []
        self.last = {}        # (entity key, attr) -> issued_at of current value
        self.notes = collections.defaultdict(list)
        self.deposits = collections.defaultdict(list)  # chat sup -> list of (at, po, conf)

    # -- tx plumbing
    def tx(self, ev, conf, facts):
        if not facts:
            return
        h = ev['hash']
        pre = [{'e': ['document/hash', h], 'a': 'document/url', 'v': ev['url']},
               {'e': ['document/hash', h], 'a': 'document/issued_at', 'v': iso(ev['at'])},
               {'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', h]},
               {'e': 'tmp:tx', 'a': 'core/confidence', 'v': str(conf)}]
        self.txs.append({'ev': ev, 'conf': conf, 'facts': pre + facts})

    def fact(self, e, a, v):
        return {'e': e, 'a': a, 'v': v}

    def guard(self, key, attr, at):
        """False when a newer document already set this value."""
        k = (json.dumps(key), attr)
        if k in self.last and self.last[k] > at:
            self.notes['stale_skipped'].append((key, attr, iso(at)))
            return False
        self.last[k] = at
        return True

    def pstate(self, po):
        return self.po.setdefault(po, dict(status=None, lines={}, sup=None, etd=None, pi=None, cur=None, total=None, dep=None,
                                           placed=None, pi_at=None, ready=False, qty_ship={}, deposit_seen=False))

    def set_status(self, ev, po, status, conf, extra=None):
        st = self.pstate(po)
        cur = st['status']
        if cur is not None and ST_ORDER.index(status) <= ST_ORDER.index(cur):
            return False
        st['status'] = status
        return True

    # ---------- PI ----------
    def do_pi(self, d):
        po = d['po']; st = self.pstate(po)
        sc = d['sc']
        cur = 'CNY' if d['rows'][0]['cur'] == 'RMB' else d['rows'][0]['cur']
        etd = dt.datetime.strptime(d['etd'], '%b %d, %Y').date()
        port_name = re.search(r'FOB (\w+)', d['incoterm']).group(1)
        locode = {'Ningbo': 'CNNGB', 'Yantian': 'CNYTN', 'Shenzhen': 'CNSZX', 'Nansha': 'CNNSA', 'Xiamen': 'CNXMN',
                  'Dongguan': 'CNDGG', 'Ningbo ': 'CNNGB'}.get(port_name, None) or {'Yantian': 'CNYTN'}.get(port_name)
        if not locode:
            self.notes['port_unknown'].append((d['file'], port_name))
        sup = ['supplier/code', sc]
        name = d['beneficiary']
        mp = re.search(r'(\d+)% deposit', d['payment']); pct = int(mp.group(1)) if mp else None
        total = sum(Dec(r['price']) * r['qty'] for r in d['rows'])
        st.update(sup=sc, pi=d['pi'], cur=cur, total=total, dep=(Dec(pct) / 100) if pct else None, pi_at=d['at'], rows=d['rows'])
        self.pi_po[d['pi']] = po
        facts = [self.fact(['po/number', po], 'po/pi_number', d['pi']),
                 self.fact(['po/number', po], 'po/supplier', sup),
                 self.fact(['po/number', po], 'core/currency', cur)]
        if self.guard(po, 'po/etd', d['at']):
            facts.append(self.fact(['po/number', po], 'po/etd', etd.isoformat()))
            st['etd'] = etd
        if self.set_status(d, po, 'confirmed', 1):
            facts.append(self.fact(['po/number', po], 'po/status', 'confirmed'))
        for i, r in enumerate(d['rows'], 1):
            key = f'{po}/{i}'
            sku = ['factory/item_code', f"{sc}:{r['item']}"]
            facts += [self.fact(['po_line/key', key], 'core/part_of', ['po/number', po]),
                      self.fact(['po_line/key', key], 'po_line/sku', sku),
                      self.fact(['po_line/key', key], 'po_line/quantity', str(r['qty'])),
                      self.fact(['po_line/key', key], 'po_line/unit_price', r['price'])]
            st['lines'][r['item']] = dict(key=key, qty=r['qty'])
        facts += [self.fact(sup, 'supplier/name', name), self.fact(sup, 'supplier/name_cn', d['name_cn']),
                  self.fact(sup, 'supplier/address', d['address']), self.fact(sup, 'supplier/incoterm', d['incoterm']),
                  self.fact(sup, 'supplier/payment_terms', d['payment']), self.fact(sup, 'supplier/currency', cur)]
        if locode:
            facts.append(self.fact(sup, 'supplier/port', locode))
        self.tx(d, 1, facts)

    # ---------- QC ----------
    def do_qc(self, d):
        po = d['po']
        q = ['qc/report_no', d['report_no']]
        facts = [self.fact(q, 'qc/po', ['po/number', po]),
                 self.fact(q, 'qc/inspected_on', d['date']),
                 self.fact(q, 'qc/result', d['result']),
                 self.fact(q, 'qc/inspector', d['inspector'].title()),
                 self.fact(q, 'qc/sample_size', str(d['sample']))]
        if d['result'] == 'PASS' and self.set_status(d, po, 'ready', 1):
            facts.append(self.fact(['po/number', po], 'po/status', 'ready'))
        self.tx(d, 1, facts)

    # ---------- shipments ----------
    def find_ship(self, hbl=None, so=None, container=None):
        for s in self.shipments:
            if hbl and s['hbl'] == hbl:
                return s
            if so and s['so'] == so:
                return s
            if container and container != 'LCL' and s['container'] == container:
                return s
        return None

    def lk(self, s):
        return ['shipment/hbl', s['hbl']] if s['hbl'] else ['shipment/booking_no', s['so']]

    def match_booking(self, vessel, pos):
        c = [s for s in self.shipments if s['so'] and not s['hbl'] and s['vessel'] == vessel and (s['pos'] & set(pos))]
        return c

    def attach(self, ev, hbl, vessel, pos):
        """Find or create the shipment for an HBL. Returns (shipment, link_tx_needed)."""
        s = self.find_ship(hbl=hbl)
        if s:
            return s
        c = self.match_booking(vessel, pos)
        if len(c) > 1:
            self.notes['ambiguous_booking'].append((hbl, [x['so'] for x in c]))
        if c:
            s = c[0]
            conf = 0.95 if s['exact_refs'] else 0.9
            self.tx(ev, conf, [self.fact(['shipment/booking_no', s['so']], 'shipment/hbl', hbl)])
            s['hbl'] = hbl
            s['linked_conf'] = conf
            return s
        s = dict(so=None, hbl=hbl, container=None, vessel=vessel, pos=set(pos), status=None, departed=False,
                 delivered=False, exact_refs=True, lines={}, atd=None)
        s['id']=len(self.shipments); self.shipments.append(s)
        self.notes['shipment_without_booking'].append(hbl)
        return s

    def ship_status(self, s, status):
        if s['status'] is None or SH_ORDER.index(status) > SH_ORDER.index(s['status']):
            s['status'] = status
            return True
        return False

    def line_facts(self, s, ev, hbl, po, item, qty, ctns):
        st = self.pstate(po)
        ln = st['lines'].get(item)
        if not ln:
            self.notes['unmatched_line'].append((ev.get('file') or ev['url'], po, item))
            return []
        key = f"{hbl}/{ln['key']}"
        prev = s['lines'].get(ln['key'])
        if prev and (prev[0] != qty or prev[1] != ctns):
            self.notes['line_discrepancy'].append((key, prev, (qty, ctns), ev.get('file') or ev['url']))
        s['lines'][ln['key']] = (qty, ctns)
        s['pos'].add(po)
        return [self.fact(['shipment_line/key', key], 'core/part_of', ['shipment/hbl', hbl]),
                self.fact(['shipment_line/key', key], 'shipment_line/po_line', ['po_line/key', ln['key']]),
                self.fact(['shipment_line/key', key], 'shipment_line/quantity', str(qty)),
                self.fact(['shipment_line/key', key], 'shipment_line/cartons', str(ctns))]

    def po_shipped_check(self, ev, pos, atd_date=None, from_prealert=False):
        """After a shipping document: mark POs shipped when all goods have sailed."""
        for po in sorted(pos):
            st = self.pstate(po)
            # quantities shipped per PO line across all shipments
            tot = collections.Counter()
            for s in self.shipments:
                for lk_, (q, c) in s['lines'].items():
                    if lk_.startswith(po + '/'):
                        tot[lk_] += q
            full = bool(st['lines']) and all(tot[l['key']] >= l['qty'] for l in st['lines'].values())
            books = [s for s in self.shipments if po in s['pos']]
            booked = books and all(s['departed'] for s in books)
            if not (full or booked):
                continue
            facts = []
            if self.set_status(ev, po, 'shipped', 1):
                facts.append(self.fact(['po/number', po], 'po/status', 'shipped'))
                st['shipped_at'] = None
            if from_prealert and atd_date and self.guard(po, 'po/etd', ev['at']):
                facts.append(self.fact(['po/number', po], 'po/etd', atd_date.isoformat()))
                st['etd'] = atd_date
            if facts:
                self.tx(ev, 1, facts)

    def do_ci(self, d):
        po = d['po']; st = self.pstate(po)
        hbl = d['hbl']
        s = self.attach(d, hbl, d['vessel'], [po])
        facts = []
        sl = self.lk(s)
        if d['container'] != 'LCL':
            facts.append(self.fact(sl, 'shipment/container_no', d['container']))
            s['container'] = d['container']
        facts += [self.fact(sl, 'shipment/vessel', d['vessel']), self.fact(sl, 'shipment/origin', d['origin']),
                  self.fact(sl, 'shipment/destination', d['dest'])]
        s['vessel'] = d['vessel']
        s['pos'].add(po)
        for r in d['rows']:
            pl = d['pl'][r['item']]
            facts += self.line_facts(s, d, hbl, po, r['item'], r['qty'], pl['ctns'])
        self.tx(d, 1, facts)
        s['ci_seen'] = True
        s['departed_doc'] = True
        s['departed'] = True      # a commercial invoice means the goods left the factory on this bill
        self.po_shipped_check(d, [po])

    # ---------- emails ----------
    def do_booking(self, e):
        so = e['so']
        mode = {'LCL': 'LCL'}.get(e['equip'].split()[0]) or re.search(r'(20GP|40HQ)', e['equip']).group(1)
        pos = []; exact = True
        for ref in re.findall(r'[Pp][Oo][ #-]?[\d-]+', e['pos']):
            p, ex = norm_po_ref(ref, 0)
            pos.append(p); exact &= (ex and ('PO-' in ref or 'PO#' in ref))
        o, dd = e['pol']
        s = self.find_ship(so=so)
        if s is None:
            s = dict(so=so, hbl=None, container=None, vessel=e['vessel'], pos=set(pos), status=None, departed=False,
                     delivered=False, exact_refs=exact, lines={}, atd=None)
            s['id'] = len(self.shipments); self.shipments.append(s)
        sl = ['shipment/booking_no', so]
        facts = [self.fact(sl, 'shipment/mode', mode), self.fact(sl, 'shipment/vessel', e['vessel']),
                 self.fact(sl, 'shipment/origin', o), self.fact(sl, 'shipment/destination', dd)]
        if self.guard(('ship', s['id']), 'shipment/etd', e['at']):
            facts.append(self.fact(sl, 'shipment/etd', local_midnight(e['etd'], o)))
        if self.guard(('ship', s['id']), 'shipment/eta', e['at']):
            facts.append(self.fact(sl, 'shipment/eta', local_midnight(e['eta'], dd)))
        s['origin'], s['dest'] = o, dd
        if self.ship_status(s, 'booked'):
            facts.append(self.fact(sl, 'shipment/status', 'booked'))
        self.tx(e, 1, facts)

    def do_roll(self, e):
        s = self.find_ship(so=e['so'])
        sl = ['shipment/booking_no', e['so']]
        facts = []
        if self.guard(('ship', s['id']), 'shipment/etd', e['at']):
            facts.append(self.fact(sl, 'shipment/etd', local_midnight(e['etd'], s['origin'])))
        if self.guard(('ship', s['id']), 'shipment/eta', e['at']):
            facts.append(self.fact(sl, 'shipment/eta', local_midnight(e['eta'], s['dest'])))
        self.tx(e, 1, facts)

    def do_prealert(self, e):
        hbl = e['hbl']
        pos = [l[0] for l in e['lines']]
        s = self.attach(e, hbl, e['vessel'], pos)
        sl = ['shipment/hbl', hbl]
        o = PORT_NAME[e['atd_port']]; dd = PORT_NAME[e['eta_port']]
        facts = []
        if e['container'] != 'LCL':
            facts.append(self.fact(sl, 'shipment/container_no', e['container']))
            s['container'] = e['container']
        if self.guard(('ship', s['id']), 'shipment/etd', e['at']):
            facts.append(self.fact(sl, 'shipment/etd', local_midnight(e['atd'], o)))
        if self.guard(('ship', s['id']), 'shipment/eta', e['at']):
            facts.append(self.fact(sl, 'shipment/eta', local_midnight(e['eta'], dd)))
        s['origin'], s['dest'] = o, dd
        if self.ship_status(s, 'departed'):
            facts.append(self.fact(sl, 'shipment/status', 'departed'))
        s['vessel'] = e['vessel']
        for po, item, ctns, pcs in e['lines']:
            facts += self.line_facts(s, e, hbl, po, item, pcs, ctns)
        s['departed'] = True
        s['atd'] = e['atd']
        self.tx(e, 1, facts)
        self.po_shipped_check(e, set(pos), e['atd'], True)

    def do_eta(self, e):
        s = self.find_ship(hbl=e['hbl'])
        if not self.guard(('ship', s['id']), 'shipment/eta', e['at']):
            return
        self.tx(e, 1, [self.fact(['shipment/hbl', e['hbl']], 'shipment/eta', local_midnight(e['eta'], s['dest']))])

    def do_arrival(self, e):
        s = self.find_ship(hbl=e['hbl'])
        port = PORT_NAME[e['port']]
        sl = ['shipment/hbl', e['hbl']]
        facts = []
        if self.ship_status(s, 'arrived'):
            facts.append(self.fact(sl, 'shipment/status', 'arrived'))
        if self.guard(('ship', s['id']), 'shipment/eta', e['at']):
            facts.append(self.fact(sl, 'shipment/eta', local_midnight(e['day'], port)))
        self.tx(e, 1, facts)

    def do_receipt(self, e):
        ref = e['ref']
        s = self.find_ship(hbl=ref) or self.find_ship(container=ref)
        if not s:
            self.notes['unresolved'].append(('receipt', ref)); return
        sl = ['shipment/hbl', s['hbl']]
        facts = []
        if self.ship_status(s, 'delivered'):
            facts.append(self.fact(sl, 'shipment/status', 'delivered'))
        facts.append(self.fact(sl, 'shipment/delivered_at', iso(e['at'])))
        s['delivered'] = True
        self.tx(e, 1, facts)
        if e['disc']:
            self.notes['receipt_discrepancies'].append((e['rcv'], ref, e['disc']))
        for po in sorted(s['pos']):
            carrying = [x for x in self.shipments if po in x['pos']]
            if all(x['delivered'] for x in carrying) and self.set_status(e, po, 'received', 1):
                self.tx(e, 1, [self.fact(['po/number', po], 'po/status', 'received')])

    def do_entry(self, e):
        ref = e['ref']
        s = self.find_ship(hbl=ref) or self.find_ship(container=ref)
        if not s:
            self.notes['unresolved'].append(('entry', e['entry'], ref)); return
        c = ['customs/entry_no', e['entry']]
        duty = Dec(e['hts']) + Dec(e['s301']) + Dec(e['add'])
        fees = Dec(e['mpf']) + Dec(e['hmf'])
        local = e['at']
        self.tx(e, 1, [self.fact(c, 'customs/shipment', ['shipment/hbl', s['hbl']]),
                       self.fact(c, 'customs/filed_on', local.date().isoformat()),
                       self.fact(c, 'customs/entered_value', e['value']),
                       self.fact(c, 'customs/duty', str(duty)), self.fact(c, 'customs/fees', str(fees)),
                       self.fact(c, 'core/currency', 'USD')])

    # ---------- chat ----------
    def china_date(self, e):
        return e['at'].astimezone(CN).date()

    def next_date(self, e, m, d):
        base = self.china_date(e)
        for y in (base.year, base.year + 1):
            try:
                c = dt.date(y, m, d)
            except ValueError:
                continue
            if c >= base:
                return c

    def do_chat(self, e):
        t = e['text']; sup = e['sup']
        if e['mine']:
            m = re.search(r"(?:new PO|here's|PO) (PO-\d{4}-\d{4})", t)
            if m and re.search(r'attached|here\'s|for \d+ items', t):
                po = m.group(1)
                st = self.pstate(po)
                st['placed'] = e['at']
                self.tx(e, 1, [self.fact(['po/number', po], 'po/placed_on', e['at'].date().isoformat()),
                               self.fact(['po/number', po], 'po/supplier', ['supplier/code', sup])])
                if st['sup'] and st['sup'] != sup:
                    self.notes['supplier_conflict'].append((po, st['sup'], sup))
                st['sup'] = sup
                return
            m = re.search(r'Deposit paid today, (USD|CNY) ([\d,.]+)', t) or re.search(r'sent the deposit for (PO-\d{4}-\d{4}) \((USD|CNY) ([\d,.]+)\)', t)
            if m:
                if m.re.pattern.startswith('Deposit'):
                    cur, amt = m.group(1), Dec(m.group(2).replace(',', '').rstrip('.'))
                    cands = [p for p, s in self.po.items() if s['sup'] == sup and s['total'] and s['dep'] and s['cur'] == cur
                             and abs(s['total'] * s['dep'] - amt) < Dec('0.02')]
                    if len(cands) == 1:
                        self.deposits[sup].append((e['at'], cands[0], 0.8))
                    else:
                        self.notes['deposit_unresolved'].append((e['url'], t, cands)); self.deposits[sup].append((e['at'], None, 0))
                else:
                    self.deposits[sup].append((e['at'], m.group(1), 0.9))
                return
            return
        # supplier messages
        # slips
        m = re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', t)
        if m:
            return self.slip(e, m.group(1), int(m.group(2)), int(m.group(3)), 0.9)
        m = re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', t)
        if m:
            return self.slip(e, m.group(1), int(m.group(2)), int(m.group(3)), 0.9)
        m = re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货', t)
        if m:
            po = self.pi_po.get(m.group(1))
            if not po:
                self.notes['unresolved'].append(('slip PI unknown', e['url'], m.group(1))); return
            return self.slip(e, po, int(m.group(2)), int(m.group(3)), 0.8)
        m = re.search(r'[Cc]ontainer(?: loaded)?:? (\w{4}\d{7})', t)
        if m:
            return self.chat_container(e, m.group(1))
        if t in ('定金收到了，马上安排生产',) or (t in ('Received, thank you', '收到，谢谢')):
            dep = [d for d in self.deposits[sup] if d[0] <= e['at']]
            if dep and (e['at'] - dep[-1][0]) < dt.timedelta(days=4) and dep[-1][1]:
                if t.startswith('定金') or True:
                    at, po, conf = dep[-1]
                    if self.set_status(e, po, 'in_production', conf):
                        self.tx(e, conf, [self.fact(['po/number', po], 'po/status', 'in_production')])
            else:
                self.notes['ack_unresolved'].append((e['url'], t))
            return
        if t == '大货生产中':
            cands = [p for p, s in self.po.items() if s['sup'] == sup and s['status'] in ('confirmed', 'in_production')
                     and any(d[1] == p for d in self.deposits[sup])]
            if len(cands) == 1:
                p = cands[0]
                if self.set_status(e, p, 'in_production', 0.7):
                    self.tx(e, 0.7, [self.fact(['po/number', p], 'po/status', 'in_production')])
            elif cands:
                self.notes['production_ambiguous'].append((e['url'], cands))
            return

    def slip(self, e, po, m, d, conf):
        st = self.pstate(po)
        if st['status'] in ('shipped', 'received'):
            self.notes['slip_after_shipped'].append((e['url'], po)); return
        date = self.next_date(e, m, d)
        if not self.guard(po, 'po/etd', e['at']):
            return
        if st['pi_at'] and st['pi_at'] > e['at']:
            self.notes['slip_before_pi'].append((e['url'], po))
        st['etd'] = date
        self.tx(e, conf, [self.fact(['po/number', po], 'po/etd', date.isoformat())])

    def chat_container(self, e, cn):
        info = self.cont_map.get(cn)
        s = self.find_ship(container=cn)
        if not s and info:
            s = self.find_ship(hbl=info[0])
            if not s:
                c = self.match_booking(info[1], info[2])
                s = c[0] if c else None
        if not s:
            self.notes['unresolved'].append(('container msg', e['url'], cn)); return
        s['container'] = cn
        self.tx(e, 0.9, [self.fact(self.lk(s), 'shipment/container_no', cn)])

    cont_map = {}


def main(write=False, only=None):
    ev = load_events()
    r = Run()
    for e in ev:
        if e['kind'] == 'ci' and e['container'] != 'LCL':
            r.cont_map.setdefault(e['container'], (e['hbl'], e['vessel'], [e['po']]))
        if e['kind'] == 'mail_prealert' and e['container'] != 'LCL':
            r.cont_map.setdefault(e['container'], (e['hbl'], e['vessel'], [l[0] for l in e['lines']]))
    for e in ev:
        k = e['kind']
        getattr(r, {'pi': 'do_pi', 'qc': 'do_qc', 'ci': 'do_ci', 'mail_booking': 'do_booking', 'mail_roll': 'do_roll',
                    'mail_prealert': 'do_prealert', 'mail_eta': 'do_eta', 'mail_arrival': 'do_arrival',
                    'mail_receipt': 'do_receipt', 'mail_entry': 'do_entry', 'chat': 'do_chat'}[k])(e)
        # resolve container messages once the shipment is known: handled lazily below
        if k.startswith('mail_') or k == 'ci':
            pass
    return r, ev


if __name__ == '__main__':
    r, ev = main()
    print(len(r.txs))
    for k, v in r.notes.items():
        print(k, len(v))
        for x in v[:12]:
            print('   ', x)
