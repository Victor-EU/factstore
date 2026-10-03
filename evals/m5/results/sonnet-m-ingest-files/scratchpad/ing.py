import re, glob, os, json, hashlib, sys, collections, mailbox
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
import pypdf, factstore

ROOT = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-m-l3ll44x6/ingest/work/exports'
NY = ZoneInfo('America/New_York')
CN = timezone(timedelta(hours=8))
REPORT = collections.defaultdict(list)   # unresolved / notes


def note(k, m):
    REPORT[k].append(m)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def num(s):
    return s.replace(',', '')


SUP_BY_NAME = {'MINGTU': 'NBBW', 'HETAI': 'SZHT', 'LANXIN': 'YWLX', 'MINGJIA': 'FSMJ',
               'RUIFENG': 'DGRF', 'QISHENG': 'NBQS', 'YUANDA': 'XMYD', 'TIANYI': 'HZTY'}
PORT_LOCODE = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Xiamen': 'CNXMN', 'Nansha': 'CNNSA'}
PORT_TZ = {'CN': CN, 'USNYC': NY, 'USLAX': ZoneInfo('America/Los_Angeles')}
CUR = {'RMB': 'CNY', 'USD': 'USD'}
STATUS_ORDER = ['draft', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received']
SHIP_ORDER = ['booked', 'departed', 'arrived', 'delivered']


def port_dt(d, locode):
    """date at 00:00 local time of the port"""
    tz = CN if locode.startswith('CN') else PORT_TZ[locode]
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def iso(dt):
    return dt.isoformat()


# ---------------------------------------------------------------- documents
class Doc:
    def __init__(self, kind, hash_, url, issued, text, **kw):
        self.kind, self.hash, self.url, self.issued, self.text = kind, hash_, url, issued, text
        self.__dict__.update(kw)
        self.order = 0


def load_pdfs():
    docs = []
    for f in sorted(glob.glob(ROOT + '/supplier_docs/*.pdf')):
        b = open(f, 'rb').read()
        text = '\n'.join(p.extract_text() for p in pypdf.PdfReader(f).pages)
        n = os.path.basename(f)
        url = 'supplier_docs/' + n
        if n.startswith('CI-PL_'):
            d = re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)', text)
            docs.append(Doc('cipl', sha(b), url, datetime.fromisoformat(d.group(2)).replace(tzinfo=CN), text))
        elif n.startswith('LCI-'):
            d = re.search(r'Inspection date: (\d{4}-\d\d-\d\d)', text)
            docs.append(Doc('qc', sha(b), url, datetime.fromisoformat(d.group(1)).replace(tzinfo=CN), text))
        else:
            d = re.search(r'PI No\.: (\S+)[^\n]*\n[^\n]*Date: (\d{4}-\d\d-\d\d)', text)
            docs.append(Doc('pi', sha(b), url, datetime.fromisoformat(d.group(2)).replace(tzinfo=CN), text))
    return docs


def load_chats():
    docs = []
    for f in sorted(glob.glob(ROOT + '/wechat/*.txt')):
        fn = os.path.basename(f)
        code = fn.split('_')[0]
        t = open(f, encoding='utf-8').read()
        parts = re.split(r'\n\n(?=\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )', t)
        for n, blk in enumerate(parts[1:], 1):
            blk = blk.rstrip('\n')
            lines = blk.split('\n')
            m = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$', lines[0])
            ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            body = '\n'.join(lines[1:]).strip()
            d = Doc('chat', sha(blk.encode('utf-8')), f'wechat/{fn}#{n}', ts, blk,
                    code=code, sender=m.group(2), body=body, file=fn, n=n)
            docs.append(d)
    return docs


def load_mail():
    raw = open(ROOT + '/email/ops_inbox.mbox', 'rb').read()
    pieces = re.split(rb'(?:(?<=\n\n)|^)(?=From )', raw)
    docs = []
    for p in pieces:
        if not p.strip():
            continue
        if p.endswith(b'\n\n'):
            p = p[:-1]
        import email
        msg = email.message_from_bytes(p.split(b'\n', 1)[1])
        mid = msg['Message-ID'].strip('<>')
        issued = email.utils.parsedate_to_datetime(msg['Date'])
        body = msg.get_payload()
        docs.append(Doc('mail', sha(p), 'mid:' + mid, issued, body, subject=msg['Subject'], hdr=msg))
    return docs


# ---------------------------------------------------------------- store snapshot
def snapshot():
    r = factstore.query('select c.v code, s.v hs, k.v sup from "factory/item_code" c '
                        'join "sku/hs_code" s using(e) join "sku/supplier" sp using(e) join "supplier/code" k on k.e=sp.v')
    items = {}
    for row in r.rows:
        items[row[0]] = (row[1], row[2])
    pos = {row[0] for row in factstore.query('select v from "po/number"').rows}
    return items, pos


# ---------------------------------------------------------------- state
class PO:
    def __init__(self, n):
        self.n = n; self.status = None; self.etd = None; self.sup = None; self.pi = None
        self.lines = []          # dicts key,item,qty
        self.total = 0.0; self.dep = None; self.etd_doc = None


class Ship:
    def __init__(self):
        self.hbl = None; self.booking = None; self.vessel = None; self.pos = set()
        self.status = None; self.etd = None; self.eta = None; self.origin = None; self.dest = None
        self.container = None; self.lines = {}; self.eta_doc = None; self.etd_doc = None

    def ref(self):
        return ['shipment/hbl', self.hbl] if self.hbl else ['shipment/booking_no', self.booking]


class Plan:
    def __init__(self):
        self.items, self.store_pos = snapshot()
        self.pos = {}
        self.ships = []
        self.pi2po = {}
        self.txs = []          # (doc, conf, facts)
        self.docs_seen = set()
        self.pending = {}
        self.last_pi = {}
        self.entries = {}
        self.known_pos = set(self.store_pos)

    # ---- helpers
    def po(self, n):
        if n not in self.pos:
            self.pos[n] = PO(n)
        return self.pos[n]

    def emit(self, doc, facts, conf='1'):
        if not facts:
            return
        pre = []
        if doc.hash not in self.docs_seen:
            self.docs_seen.add(doc.hash)
            pre = [{'e': ['document/hash', doc.hash], 'a': 'document/url', 'v': doc.url},
                   {'e': ['document/hash', doc.hash], 'a': 'document/issued_at', 'v': iso(doc.issued)}]
        meta = [{'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', doc.hash]},
                {'e': 'tmp:tx', 'a': 'core/confidence', 'v': conf}]
        # a booking gaining its HBL in this transaction is addressed by the booking number throughout
        for f in facts:
            if f['a'] == 'shipment/hbl' and f['e'][0] == 'shipment/booking_no':
                alias = ['shipment/hbl', f['v']]
                for g in facts:
                    if g is f: continue
                    if g['e'] == alias: g['e'] = f['e']
                    if g['v'] == alias: g['v'] = f['e']
        self.txs.append((doc, conf, pre + meta + facts))

    def bump_po(self, po, status, facts, doc):
        p = self.po(po)
        if p.status is None or STATUS_ORDER.index(status) > STATUS_ORDER.index(p.status):
            p.status = status
            facts.append({'e': ['po/number', po], 'a': 'po/status', 'v': status})

    def set_po_etd(self, po, d, doc, facts):
        p = self.po(po)
        if p.etd_doc and doc.issued < p.etd_doc:
            note('stale_etd', f'{doc.url}: {po} etd {d} older than {p.etd}'); return
        if p.status in ('shipped', 'received'):
            note('etd_after_shipped', f'{doc.url}: {po} etd {d} ignored, PO already {p.status}'); return
        p.etd = d; p.etd_doc = doc.issued
        facts.append({'e': ['po/number', po], 'a': 'po/etd', 'v': d.isoformat()})

    def norm_po(self, s, year_hint):
        m = re.search(r'(\d{4})-(\d{4})', s)
        if m:
            return f'PO-{m.group(1)}-{m.group(2)}'
        m = re.search(r'(\d{1,4})\s*$', s)
        if m:
            seq = int(m.group(1))
            cands = [p for p in self.known_pos if int(p[-4:]) == seq]
            if len(cands) > 1:
                cands.sort(key=lambda p: abs(int(p[3:7]) - year_hint))
            if cands:
                return cands[0]
        return None

    def find_ship(self, hbl=None, booking=None, vessel=None, pos=None, container=None):
        for s in self.ships:
            if hbl and s.hbl == hbl: return s
            if booking and s.booking == booking: return s
        if container and container != 'LCL':
            for s in self.ships:
                if s.container == container: return s
        if vessel and pos:
            c = [s for s in self.ships if not s.hbl and s.vessel == vessel and (s.pos & set(pos))]
            if len(c) == 1: return c[0]
            if len(c) > 1:
                note('ambiguous_booking', f'{vessel} {pos}: {[x.booking for x in c]}')
                return sorted(c, key=lambda s: -len(s.pos & set(pos)))[0]
        return None


# ---------------------------------------------------------------- PI
def h_pi(P, doc):
    t = doc.text; L = t.split('\n')
    pi = re.search(r'PI No\.: (\S+)', t).group(1)
    po = re.search(r'Your PO: (PO-\d{4}-\d{4})', t).group(1)
    name_en = L[1].strip()
    code = next(c for k, c in SUP_BY_NAME.items() if k in name_en.upper())
    name_cn, addr = L[0].strip(), L[2].strip()
    bene = re.search(r'Beneficiary: (.*)', t).group(1).strip()
    term = re.search(r'Price term: (.*)', t).group(1).strip()
    pay = re.search(r'Payment: (.*)', t).group(1).strip()
    dm = re.search(r'Delivery: about (\w+) (\d+), (\d{4})', t)
    etd = datetime.strptime(f'{dm.group(1)} {dm.group(2)} {dm.group(3)}', '%b %d %Y').date()
    items = []
    for i, l in enumerate(L):
        m = re.match(r'^([\d,]+) (\d+) (USD|RMB) ([\d.,]+) (USD|RMB) ([\d.,]+)$', l)
        if m:
            items.append((L[i - 2].split()[0], int(num(m.group(1))), m.group(3), num(m.group(4)), float(num(m.group(6)))))
    total = float(num(re.search(r'^TOTAL (?:USD|RMB) ([\d.,]+)', t, re.M).group(1)))
    if abs(sum(i[4] for i in items) - total) > 0.01:
        note('pi_total_mismatch', f'{doc.url}: lines {sum(i[4] for i in items)} vs {total}')
    cur = CUR[items[0][2]]
    p = P.po(po)
    if p.lines:
        note('pi_repeat', f'{doc.url}: {po} already has lines from {p.pi}')
    p.sup = code; p.pi = pi; p.total = total
    dp = re.search(r'(\d+)% deposit', pay)
    p.dep = int(dp.group(1)) / 100 if dp else None
    P.pi2po[pi] = po
    P.last_pi[code] = po; p.pi_etd = etd
    P.known_pos.add(po)
    facts = []
    pe = ['po/number', po]
    facts += [{'e': pe, 'a': 'po/pi_number', 'v': pi},
              {'e': pe, 'a': 'po/supplier', 'v': ['supplier/code', code]},
              {'e': pe, 'a': 'core/currency', 'v': cur}]
    P.set_po_etd(po, etd, doc, facts)
    P.bump_po(po, 'confirmed', facts, doc)
    for n, (item, q, c, price, amt) in enumerate(items, 1):
        full = f'{code}:{item}'
        if full not in P.items:
            note('unknown_item', f'{doc.url}: {full}'); continue
        key = f'{po}/{n}'
        p.lines.append({'key': key, 'item': full, 'qty': q})
        le = ['po_line/key', key]
        facts += [{'e': le, 'a': 'core/part_of', 'v': pe},
                  {'e': le, 'a': 'po_line/sku', 'v': ['factory/item_code', full]},
                  {'e': le, 'a': 'po_line/quantity', 'v': str(q)},
                  {'e': le, 'a': 'po_line/unit_price', 'v': price}]
    se = ['supplier/code', code]
    port = PORT_LOCODE[term.split()[-1]]
    facts += [{'e': se, 'a': 'supplier/name_cn', 'v': name_cn},
              {'e': se, 'a': 'supplier/name', 'v': bene},
              {'e': se, 'a': 'supplier/address', 'v': addr},
              {'e': se, 'a': 'supplier/incoterm', 'v': term},
              {'e': se, 'a': 'supplier/payment_terms', 'v': pay},
              {'e': se, 'a': 'supplier/currency', 'v': cur},
              {'e': se, 'a': 'supplier/port', 'v': port}]
    P.emit(doc, facts)


# ---------------------------------------------------------------- CI/PL
def parse_cipl(doc):
    t = doc.text; L = t.split('\n')
    h = re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (PO-\d{4}-\d{4})', t)
    r = re.search(r'From (\w+) to (\w+) by sea, (MV .+?)\s+Container: (\S+)\s+B/L: (\S+)', t)
    rows = []
    for i, l in enumerate(L):
        m = re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d.,]+) (USD|RMB) ([\d.,]+)$', l)
        if m:
            rows.append((L[i - 2].split()[0], m.group(1), int(num(m.group(2)))))
    ctns = collections.Counter(); pcs = collections.Counter()
    for l in L:
        m = re.match(r'^(\d+(?:-\d+)?) (\S+) (\d+) (\d+) ([\d,]+) [\d.,]+ \S+ [\d.]+$', l)
        if m:
            ctns[m.group(2)] += int(m.group(3)); pcs[m.group(2)] += int(num(m.group(5)))
    return dict(inv=h.group(1), po=h.group(3), origin=r.group(1), dest=r.group(2), vessel=r.group(3),
                container=r.group(4), hbl=r.group(5), rows=rows, ctns=ctns, pcs=pcs)


def ship_lines(P, doc, s, po, rows, facts):
    """rows: (item_full, qty, cartons)"""
    p = P.po(po)
    for item, q, c in rows:
        pl = next((l for l in p.lines if l['item'] == item), None)
        if not pl:
            note('no_po_line', f'{doc.url}: {po} {item}'); continue
        key = f'{s.hbl}/{pl["key"]}'
        e = ['shipment_line/key', key]
        old = s.lines.get(pl['key'])
        if old is not None and old != q:
            note('line_qty_disagree', f'{doc.url}: {key} {old} -> {q}')
        s.lines[pl['key']] = q
        facts += [{'e': e, 'a': 'core/part_of', 'v': s.ref()},
                  {'e': e, 'a': 'shipment_line/po_line', 'v': ['po_line/key', pl['key']]},
                  {'e': e, 'a': 'shipment_line/quantity', 'v': str(q)}]
        if c is not None:
            facts.append({'e': e, 'a': 'shipment_line/cartons', 'v': str(c)})


def attach_hbl(P, s, hbl, facts):
    if not s.hbl:
        facts.append({'e': ['shipment/booking_no', s.booking], 'a': 'shipment/hbl', 'v': hbl})
        s.hbl = hbl


def h_cipl(P, doc):
    d = parse_cipl(doc)
    po = d['po']
    p = P.po(po); p.sup = p.sup
    s = P.find_ship(hbl=d['hbl'], vessel=d['vessel'], pos=[po])
    facts = []
    if s is None:
        s = Ship(); s.hbl = d['hbl']; P.ships.append(s)
    else:
        attach_hbl(P, s, d['hbl'], facts)
    s.pos.add(po)
    se = ['shipment/hbl', d['hbl']]
    if d['container'] != 'LCL':
        facts.append({'e': se, 'a': 'shipment/container_no', 'v': d['container']}); s.container = d['container']
    s.vessel = s.vessel or d['vessel']
    facts.append({'e': se, 'a': 'shipment/vessel', 'v': d['vessel']})
    facts += [{'e': se, 'a': 'shipment/origin', 'v': d['origin']}, {'e': se, 'a': 'shipment/destination', 'v': d['dest']}]
    s.origin, s.dest = d['origin'], d['dest']
    code = p.sup
    rows = []
    for item, hs, q in d['rows']:
        full = f'{code}:{item}'
        if full not in P.items:
            note('unknown_item', f'{doc.url}: {full}'); continue
        if d['pcs'].get(item) != q:
            note('pl_qty_mismatch', f'{doc.url}: {item} invoice {q} vs packing {d["pcs"].get(item)}')
        rows.append((full, q, d['ctns'].get(item)))
        sku_hs = P.items[full][0]
        if sku_hs != hs:
            note('hs_mismatch', f'{doc.url}: {full} invoice {hs} vs SKU {sku_hs}')
    ship_lines(P, doc, s, po, rows, facts)
    eval_pos(P, doc, [po], facts)
    P.emit(doc, facts)


def eval_pos(P, doc, pos, facts):
    for po in pos:
        p = P.po(po)
        if not p.lines:
            continue
        shipped = collections.Counter()
        carriers = [s for s in P.ships if any(k.startswith(po + '/') for k in s.lines)]
        for s in carriers:
            for k, q in s.lines.items():
                if k.startswith(po + '/'): shipped[k] += q
        if all(shipped[l['key']] >= l['qty'] for l in p.lines):
            if p.status in (None, 'draft', 'sent', 'confirmed', 'in_production', 'ready'):
                p.status = 'shipped'
                facts.append({'e': ['po/number', po], 'a': 'po/status', 'v': 'shipped'})
            deps = [s.etd if s.status in ('departed', 'arrived', 'delivered') else None for s in carriers]
            if p.status == 'shipped' and all(deps):
                last = max(x.date() for x in deps)
                if p.etd != last:
                    p.etd = last; p.etd_doc = doc.issued
                    facts.append({'e': ['po/number', po], 'a': 'po/etd', 'v': last.isoformat()})
            if p.status == 'shipped' and carriers and all(s.status == 'delivered' for s in carriers):
                p.status = 'received'
                facts.append({'e': ['po/number', po], 'a': 'po/status', 'v': 'received'})


# ---------------------------------------------------------------- inspection
def h_qc(P, doc):
    t = doc.text
    rn = re.search(r'Report No\.: (\S+)', t).group(1)
    po = re.search(r'PO No\.: (PO-\d{4}-\d{4})', t).group(1)
    res = re.search(r'Overall result: (\w+)', t).group(1)
    ss = re.search(r'sample size (\d+)', t).group(1)
    insp = t.split('\n')[0].strip().title()
    on = re.search(r'Inspection date: (\S+)', t).group(1)
    e = ['qc/report_no', rn]
    facts = [{'e': e, 'a': 'qc/po', 'v': ['po/number', po]}, {'e': e, 'a': 'qc/inspected_on', 'v': on},
             {'e': e, 'a': 'qc/result', 'v': res}, {'e': e, 'a': 'qc/inspector', 'v': insp},
             {'e': e, 'a': 'qc/sample_size', 'v': ss}]
    P.known_pos.add(po)
    if res == 'PASS':
        P.bump_po(po, 'ready', facts, doc)
    P.emit(doc, facts)


# ---------------------------------------------------------------- chat
def next_md(m, d, after):
    """next occurrence of month m day d on/after date `after`"""
    for y in (after.year, after.year + 1):
        try:
            c = date(y, m, d)
        except ValueError:
            continue
        if c >= after:
            return c


def h_chat(P, doc):
    code, body, snd = doc.code, doc.body, doc.sender
    maya = snd.startswith('Maya')
    cn_day = doc.issued.astimezone(CN).date()
    ny_day = doc.issued.date()
    # --- POs we sent
    if maya:
        m = (re.search(r'PO (PO-\d{4}-\d{4}) for \d+ items', body) or re.search(r'new PO (PO-\d{4}-\d{4}) attached', body)
             or re.search(r"here's (PO-\d{4}-\d{4})\.", body))
        if m:
            po = m.group(1); P.known_pos.add(po)
            P.po(po).sup = code
            facts = [{'e': ['po/number', po], 'a': 'po/placed_on', 'v': ny_day.isoformat()},
                     {'e': ['po/number', po], 'a': 'po/supplier', 'v': ['supplier/code', code]}]
            P.bump_po(po, 'sent', facts, doc)
            P.emit(doc, facts)
            return
        if 'deposit' in body.lower():
            m = re.search(r'(PO-\d{4}-\d{4})', body)
            a = re.search(r'(?:USD|CNY) ([\d,]+\.\d\d)', body)
            P.pending[code] = dict(po=m.group(1) if m else None, amt=float(num(a.group(1))) if a else None,
                                   ts=doc.issued, url=doc.url)
        elif body.startswith('Balance'):
            P.pending.pop(code, None)
        return
    # --- supplier messages
    # ETD moves
    for pat, kind in ((r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)', 'po'),
                      (r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号', 'po'),
                      (r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货', 'pi')):
        m = re.search(pat, body, re.S)
        if m:
            ref = m.group(1)
            if kind == 'pi':
                po = P.pi2po.get(ref)
                if not po:
                    note('unresolved_pi_ref', f'{doc.url}: {ref}'); return
                conf = '0.8'
            else:
                po, conf = ref, '0.9'
            d = next_md(int(m.group(2)), int(m.group(3)), cn_day)
            facts = []
            P.set_po_etd(po, d, doc, facts)
            P.emit(doc, facts, conf)
            return
    # PI announcements with an ETD: redundant with the PI, cross-check only
    m = (re.search(r'ETD(?: around)? (\d+)/(\d+)', body) or re.search(r'交期(\d+)月(\d+)号左右', body))
    if m and 'PO-' not in body:
        d = next_md(int(m.group(1)), int(m.group(2)), cn_day - timedelta(days=200))
        # compare with the latest PI of this supplier
        p = P.pos.get(P.last_pi.get(code))
        if p and (d.month, d.day) != (p.pi_etd.month, p.pi_etd.day):
            note('chat_etd_vs_pi', f'{doc.url}: chat {d} vs {p.n} PI etd {p.pi_etd}')
        return
    # production started
    if body in ('定金收到了，马上安排生产', 'Received, thank you', '收到，谢谢'):
        pend = P.pending.get(code)
        if not pend or doc.issued - pend['ts'] > timedelta(days=10):
            return
        P.pending.pop(code)
        cands = [p for p in P.pos.values() if p.sup == code and p.status == 'confirmed']
        po, conf = None, '0.9'
        if pend['po']:
            po = pend['po']
        else:
            hit = [p for p in cands if p.dep and pend['amt'] and abs(p.total * p.dep - pend['amt']) < 1.0]
            if len(hit) == 1:
                po = hit[0].n
            elif len(cands) == 1:
                po, conf = cands[0].n, '0.8'
            elif cands:
                po, conf = max(cands, key=lambda p: p.etd_doc or datetime.min.replace(tzinfo=CN)).n, '0.7'
                note('deposit_guess', f'{doc.url}: deposit {pend["amt"]} -> {po} among {[c.n for c in cands]}')
        if po:
            facts = []
            P.bump_po(po, 'in_production', facts, doc)
            P.emit(doc, facts, conf)
        else:
            note('unresolved_deposit_ack', f'{doc.url}: deposit {pend["amt"]}')
        return
    if body == '大货生产中':
        cands = [p for p in P.pos.values() if p.sup == code and p.status in ('confirmed',)]
        if cands:
            po = max(cands, key=lambda p: p.etd_doc or datetime.min.replace(tzinfo=CN)).n
            facts = []
            P.bump_po(po, 'in_production', facts, doc)
            P.emit(doc, facts, '0.7')
        return
    # gaps (not facts): price changes, holidays, samples; containers loaded
    if re.search(r'container loaded|loaded today', body):
        m = re.search(r'([A-Z]{4}\d{7})', body)
        note('container_msg', f'{doc.url}: {m.group(1)}')
    elif re.search(r'单价|rebate|prices are up|labour costs|coil prices', body):
        note('price_change', f'{doc.url}: {body.splitlines()[0][:100]}')
    elif re.search(r'放假|holiday', body):
        note('holiday', f'{doc.url}')


# ---------------------------------------------------------------- mail
def dmy(s):
    return datetime.strptime(s, '%d %b %Y').date()


NAME_LOC = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Xiamen': 'CNXMN', 'Nansha': 'CNNSA',
            'New York/Newark': 'USNYC', 'Los Angeles': 'USLAX'}


def set_ship_time(P, s, attr, dt, doc, facts):
    last = getattr(s, attr + '_doc')
    if last and doc.issued < last:
        note('stale_' + attr, f'{doc.url}: {s.ref()} {attr} {dt} older than current'); return
    setattr(s, attr, dt); setattr(s, attr + '_doc', doc.issued)
    facts.append({'e': s.ref(), 'a': f'shipment/{attr}', 'v': iso(dt)})


def set_ship_status(s, st, facts):
    if s.status is None or SHIP_ORDER.index(st) > SHIP_ORDER.index(s.status):
        s.status = st
        facts.append({'e': s.ref(), 'a': 'shipment/status', 'v': st})
        return True
    return False


def h_mail(P, doc):
    subj, body = doc.subject, doc.text
    yr = doc.issued.year
    facts = []
    if subj.startswith('Booking Confirmation'):
        g = lambda k: re.search(k + r': (.*)', body).group(1).strip()
        so = g('SO'); eq = g('Equipment'); vessel = g('Vessel/Voyage')
        pol = re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)', body)
        etd, eta = dmy(g('ETD')), dmy(g('ETA'))
        pos = [P.norm_po(x, yr) for x in re.split(r',\s*', g('POs'))]
        if None in pos:
            note('booking_po_unresolved', f'{doc.url}: {g("POs")}')
        pos = [p for p in pos if p]
        mode = 'LCL' if eq.startswith('LCL') else re.search(r'(20GP|40HQ)', eq).group(1)
        s = P.find_ship(booking=so)
        if s is None:
            s = Ship(); s.booking = so; P.ships.append(s)
        s.pos |= set(pos); s.vessel = vessel; s.origin, s.dest = pol.group(1), pol.group(2)
        e = ['shipment/booking_no', so] if not s.hbl else s.ref()
        facts += [{'e': e, 'a': 'shipment/mode', 'v': mode}, {'e': e, 'a': 'shipment/vessel', 'v': vessel},
                  {'e': e, 'a': 'shipment/origin', 'v': s.origin}, {'e': e, 'a': 'shipment/destination', 'v': s.dest}]
        set_ship_time(P, s, 'etd', port_dt(etd, s.origin), doc, facts)
        set_ship_time(P, s, 'eta', port_dt(eta, s.dest), doc, facts)
        set_ship_status(s, 'booked', facts)
        P.emit(doc, facts)
    elif subj.startswith('RE: Booking Confirmation'):
        so = re.search(r'SO (\S+)', subj).group(1)
        m = re.search(r'New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})', body)
        s = P.find_ship(booking=so)
        if not s:
            note('unresolved_shipment', f'{doc.url}: SO {so}'); return
        set_ship_time(P, s, 'etd', port_dt(dmy(m.group(1)), s.origin), doc, facts)
        set_ship_time(P, s, 'eta', port_dt(dmy(m.group(2)), s.dest), doc, facts)
        P.emit(doc, facts)
    elif subj.startswith('Shipping Advice'):
        hbl = re.search(r'HBL: (\S+)', body).group(1)
        cont = re.search(r'Container/Seal: (\S+)', body).group(1)
        vessel = re.search(r'Vessel/Voyage: (.*)', body).group(1).strip()
        atd = re.search(r'ATD ([^:]+): (\d+ \w+ \d{4})', body)
        eta = re.search(r'ETA ([^:]+): (\d+ \w+ \d{4})', body)
        lines = re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs', body, re.M)
        pos = sorted({l[0] for l in lines})
        s = P.find_ship(hbl=hbl, vessel=vessel, pos=pos)
        if s is None:
            s = Ship(); s.hbl = hbl; P.ships.append(s)
            s.vessel = vessel
        else:
            attach_hbl(P, s, hbl, facts)
        s.pos |= set(pos)
        e = ['shipment/hbl', hbl]
        if cont != 'LCL':
            facts.append({'e': e, 'a': 'shipment/container_no', 'v': cont}); s.container = cont
        s.origin = s.origin or NAME_LOC[atd.group(1)]
        s.dest = s.dest or NAME_LOC[eta.group(1)]
        set_ship_time(P, s, 'etd', port_dt(dmy(atd.group(2)), s.origin), doc, facts)
        set_ship_time(P, s, 'eta', port_dt(dmy(eta.group(2)), s.dest), doc, facts)
        set_ship_status(s, 'departed', facts)
        for po in pos:
            p = P.po(po)
            rows = [(f'{p.sup}:{l[1]}', int(l[3]), int(l[2])) for l in lines if l[0] == po]
            ship_lines(P, doc, s, po, rows, facts)
        eval_pos(P, doc, pos, facts)
        P.emit(doc, facts)
    elif subj.startswith('ETA update'):
        hbl = re.search(r'HBL (\S+)', subj).group(1)
        s = P.find_ship(hbl=hbl)
        if not s:
            note('unresolved_shipment', f'{doc.url}: {hbl}'); return
        set_ship_time(P, s, 'eta', port_dt(dmy(re.search(r'revised ETA (\d+ \w+ \d{4})', body).group(1)), s.dest), doc, facts)
        P.emit(doc, facts)
    elif subj.startswith('Arrival Notice'):
        hbl = re.search(r'HBL (\S+)', subj).group(1)
        s = P.find_ship(hbl=hbl)
        if not s:
            note('unresolved_shipment', f'{doc.url}: {hbl}'); return
        m = re.search(r'arriving (.+?) on (\d+ \w+ \d{4})', body)
        set_ship_status(s, 'arrived', facts)
        set_ship_time(P, s, 'eta', port_dt(dmy(m.group(2)), s.dest), doc, facts)
        P.emit(doc, facts)
    elif subj.startswith('Receipt complete'):
        ref = subj.split(' - ')[-1].strip()
        s = P.find_ship(hbl=ref) or P.find_ship(container=ref)
        if not s:
            note('unresolved_shipment', f'{doc.url}: {ref}'); return
        set_ship_status(s, 'delivered', facts)
        facts.append({'e': s.ref(), 'a': 'shipment/delivered_at', 'v': iso(doc.issued)})
        for l in re.findall(r'^\s+(\S+) \((\S+)\): expected (\d+), received (\d+), damaged (\d+)', body, re.M):
            exp, rec, dam = int(l[2]), int(l[3]), int(l[4])
            if rec != exp or dam:
                note('receipt_discrepancy', f'{ref} {l[0]} {l[1]}: expected {exp}, received {rec}, damaged {dam}')
        eval_pos(P, doc, sorted({k.rsplit('/', 1)[0] for k in s.lines}), facts)
        P.emit(doc, facts)
    elif subj.startswith('Entry Summary'):
        en = re.search(r'Entry (\S+) filed for (\S+)\.', body)
        v = lambda k: float(num(re.search(k + r': USD ([\d,.]+)', body).group(1)))
        entry, ref = en.group(1), en.group(2)
        s = P.find_ship(hbl=ref) or P.find_ship(container=ref)
        if not s:
            note('unresolved_shipment', f'{doc.url}: entry {entry} {ref}'); return
        ev = v('Entered value'); duty = v(r'Duty \(HTS\)') + v('Section 301') + v('Additional duties')
        fees = v('MPF') + v('HMF')
        if abs(duty + fees - v('Total duties and fees')) > 0.02:
            note('entry_total', f'{entry}: {duty}+{fees} vs {v("Total duties and fees")}')
        e = ['customs/entry_no', entry]
        facts += [{'e': e, 'a': 'customs/shipment', 'v': s.ref()},
                  {'e': e, 'a': 'customs/filed_on', 'v': doc.issued.date().isoformat()},
                  {'e': e, 'a': 'customs/entered_value', 'v': f'{ev:.2f}'},
                  {'e': e, 'a': 'customs/duty', 'v': f'{duty:.2f}'},
                  {'e': e, 'a': 'customs/fees', 'v': f'{fees:.2f}'},
                  {'e': e, 'a': 'core/currency', 'v': 'USD'}]
        P.emit(doc, facts)
    else:
        note('unhandled_mail', f'{doc.url}: {subj}')


# ---------------------------------------------------------------- run
def build():
    docs = load_pdfs() + load_chats() + load_mail()
    P = Plan()
    for d in docs:
        P.known_pos |= set(re.findall(r'PO-\d{4}-\d{4}', d.text))
    prio = {'chat': 0, 'pi': 1, 'qc': 2, 'cipl': 3, 'mail': 4}
    docs.sort(key=lambda d: (d.issued.astimezone(timezone.utc), prio[d.kind]))
    H = dict(pi=h_pi, cipl=h_cipl, qc=h_qc, chat=h_chat, mail=h_mail)
    for d in docs:
        H[d.kind](P, d)
    return P, docs
