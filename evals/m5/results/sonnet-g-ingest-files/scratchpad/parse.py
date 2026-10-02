import re, glob, os, hashlib, mailbox, datetime as dt
from zoneinfo import ZoneInfo

ROOT = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-g-v0iw_3ay/ingest/work/exports'
TXT = '/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-g-v0iw-3ay-ingest-work/65c3d298-4680-40f5-a01a-7c557b3384e8/scratchpad/txt'
CN = ZoneInfo('Asia/Shanghai'); NY = ZoneInfo('America/New_York'); LA = ZoneInfo('America/Los_Angeles')
PORT_TZ = {'CNYTN': CN, 'CNNGB': CN, 'CNNSA': CN, 'CNXMN': CN, 'USNYC': NY, 'USLAX': LA}
PORTNAME = {'New York/Newark': 'USNYC', 'Los Angeles': 'USLAX', 'Yantian': 'CNYTN', 'Ningbo': 'CNNGB',
            'Nansha': 'CNNSA', 'Xiamen': 'CNXMN'}
SUPPLIER_BY_KEY = {'Hetai': 'SZHT', 'Lanxin': 'YWLX', 'Mingjia': 'FSMJ', 'Mingtu': 'NBBW', 'Qisheng': 'NBQS',
                   'Ruifeng': 'DGRF', 'Tianyi': 'HZTY', 'Yuanda': 'XMYD'}
MON = {m: i + 1 for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def num(s):
    return s.replace(',', '')


def sup_code(text):
    for k, v in SUPPLIER_BY_KEY.items():
        if k.lower() in text.lower():
            return v
    raise ValueError('supplier? ' + text[:60])


def local_instant(d, port):
    """date -> iso instant, 00:00 local at the port"""
    t = dt.datetime(d.year, d.month, d.day, tzinfo=PORT_TZ[port])
    return t.isoformat()


def dmy(s):
    m = re.match(r'(\d+) (\w{3}) (\d{4})', s.strip())
    return dt.date(int(m[3]), MON[m[2]], int(m[1]))


def po_norm(s):
    """loose PO name -> (PO-YYYY-NNNN, exact?)"""
    m = re.fullmatch(r'PO-(\d{4})-(\d{4})', s.strip())
    if m:
        return s.strip(), True
    m = re.fullmatch(r'(?i)po[#\s-]*(?:(\d{4})-)?0*(\d+)', s.strip())
    n = int(m[2])
    y = int(m[1]) if m[1] else (2025 if n >= 143 else 2026)
    return 'PO-%d-%04d' % (y, n), False


# ---------------------------------------------------------------- PDFs
def pdf_docs():
    out = []
    for f in sorted(glob.glob(ROOT + '/supplier_docs/*.pdf')):
        b = open(f, 'rb').read()
        name = os.path.basename(f)
        t = open(f'{TXT}/{name}.txt').read()
        d = dict(hash=sha(b), url='supplier_docs/' + name, text=t, name=name)
        if name.startswith('CI-PL_'):
            d.update(parse_ci(t))
        elif name.startswith('LCI-'):
            d.update(parse_qc(t))
        else:
            d.update(parse_pi(t))
        out.append(d)
    return out


def parse_pi(t):
    L = t.splitlines()
    d = dict(kind='pi')
    d['name_cn'] = L[0].strip()
    d['address'] = L[2].strip()
    d['pi_no'] = re.search(r'PI No\.: (\S+)', t)[1]
    ds = re.search(r'Date: (\d{4}-\d\d-\d\d)', t)[1]
    d['date'] = dt.date.fromisoformat(ds)
    d['issued'] = dt.datetime(d['date'].year, d['date'].month, d['date'].day, tzinfo=CN)
    d['po'] = re.search(r'Your PO: (PO-\d{4}-\d{4})', t)[1]
    d['beneficiary'] = re.search(r'Beneficiary: (.+)', t)[1].strip()
    d['supplier'] = sup_code(d['beneficiary'])
    d['incoterm'] = re.search(r'Price term: (.+)', t)[1].strip()
    d['port'] = PORTNAME[d['incoterm'].split()[-1]]
    d['payment'] = re.search(r'Payment: (.+)', t)[1].strip()
    m = re.search(r'Delivery: about (\w{3}) (\d+), (\d{4}) \(ETD\)', t)
    d['etd'] = dt.date(int(m[3]), MON[m[1]], int(m[2]))
    items = []
    for i, l in enumerate(L):
        m = re.fullmatch(r'([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)', l.strip())
        if m:
            code = L[i - 2].split()[0]
            items.append(dict(code=code, qty=num(m[1]), ctns=m[2], price=num(m[4]), cur=m[3]))
            d['currency'] = 'CNY' if m[3] == 'RMB' else m[3]
    d['items'] = items
    tot = sum(float(i['qty']) * float(i['price']) for i in items)
    assert abs(tot - float(num(re.search(r'TOTAL (?:USD|RMB) ([\d,.]+)', t)[1]))) < 0.01, (d['pi_no'], tot)
    return d


def parse_ci(t):
    d = dict(kind='ci')
    m = re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})', t)
    d['inv_no'], ds, d['po'] = m[1], m[2], m[3]
    d['date'] = dt.date.fromisoformat(ds)
    d['issued'] = dt.datetime(d['date'].year, d['date'].month, d['date'].day, tzinfo=CN)
    m = re.search(r'From (\w+) to (\w+) by sea, (.+?)\s{2,}Container: (\S+)\s+B/L: (\S+)', t)
    d['origin'], d['dest'], d['vessel'], d['container'], d['hbl'] = m.groups()
    d['supplier'] = sup_code(t.splitlines()[1])
    L = t.splitlines()
    items = []
    for i, l in enumerate(L):
        m = re.fullmatch(r'(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)', l.strip())
        if m:
            items.append(dict(code=L[i - 2].split()[0], hs=m[1], qty=num(m[2])))
    ctn = {}
    for l in L:
        m = re.fullmatch(r'(\d+)-(\d+) (\S+) (\d+) (\d+) ([\d,]+) .*', l.strip())
        if m:
            ctn[m[3]] = m[4]
    d['items'] = items
    for it in items:
        it['ctns'] = ctn[it['code']]
    assert len(ctn) == len(items), d['inv_no']
    return d


def parse_qc(t):
    d = dict(kind='qc')
    d['report'] = re.search(r'Report No\.: (\S+)', t)[1]
    d['date'] = dt.date.fromisoformat(re.search(r'Inspection date: (\S+)', t)[1])
    d['issued'] = dt.datetime(d['date'].year, d['date'].month, d['date'].day, tzinfo=CN)
    d['po'] = re.search(r'PO No\.: (\S+)', t)[1]
    d['result'] = re.search(r'Overall result: (\w+)', t)[1]
    d['sample'] = re.search(r'sample size (\d+)', t)[1]
    d['agency'] = 'Linkcheck Inspection Services'
    assert t.startswith('LINKCHECK INSPECTION SERVICES')
    return d


# ---------------------------------------------------------------- chats
CHAT_TZ = NY


def chat_docs():
    out = []
    for f in sorted(glob.glob(ROOT + '/wechat/*.txt')):
        base = os.path.basename(f)
        code = base.split('_')[0]
        raw = open(f, encoding='utf-8').read()
        blocks = [b for b in raw.split('\n\n')]
        n = 0
        for b in blocks:
            lines = b.strip('\n').split('\n')
            m = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)', lines[0])
            if not m:
                continue
            n += 1
            ts = dt.datetime.strptime(m[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CHAT_TZ)
            body = '\n'.join(lines[1:])
            ours = m[2].startswith('Maya')
            out.append(dict(kind='chat', file=base, sup=code, n=n, hash=sha('\n'.join(lines).encode()),
                            url=f'wechat/{base}#{n}', issued=ts, ours=ours, body=body))
    return out


# ---------------------------------------------------------------- email
def email_docs():
    path = ROOT + '/email/ops_inbox.mbox'
    raw = open(path, 'rb').read()
    parts = re.split(rb'(?m)^(?=From )', raw)
    out = []
    for p in parts:
        if not p.strip():
            continue
        assert p.endswith(b'\n\n'), p[-20:]
        mb = p[:-1]
        import email
        msg = email.message_from_bytes(p.split(b'\n', 1)[1])
        body = msg.get_payload(decode=True).decode()
        date = email.utils.parsedate_to_datetime(msg['Date'])
        out.append(dict(kind='email', hash=sha(mb), url='mid:' + msg['Message-ID'].strip('<>'), issued=date,
                        subject=msg['Subject'], body=body, sender=msg['From']))
    return out


def parse_email(d):
    s, b = d['subject'], d['body']
    g = lambda pat: re.search(pat, b)
    if s.startswith('Booking Confirmation'):
        d['etype'] = 'booking'
        d['so'] = g(r'SO: (\S+)')[1]
        eq = g(r'Equipment: (.+)')[1]
        d['mode'] = 'LCL' if eq.startswith('LCL') else re.match(r'1x(\w+)', eq)[1]
        d['vessel'] = g(r'Vessel/Voyage: (.+)')[1].strip()
        m = g(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)')
        d['origin'], d['dest'] = m[1], m[2]
        d['etd'] = dmy(g(r'ETD: (.+)')[1]); d['eta'] = dmy(g(r'ETA: (.+)')[1])
        d['pos_raw'] = [x.strip() for x in g(r'POs: (.+)')[1].split(',')]
        d['pos'] = [po_norm(x) for x in d['pos_raw']]
    elif s.startswith('RE: Booking'):
        d['etype'] = 'roll'
        m = g(r'rolled SO (\S+) .*New ETD (.+?), ETA (.+?)\.')
        d['so'] = m[1]; d['etd'] = dmy(m[2]); d['eta'] = dmy(m[3])
    elif s.startswith('Shipping Advice'):
        d['etype'] = 'prealert'
        d['hbl'] = g(r'HBL: (\S+)')[1]
        c = g(r'Container/Seal: (\S+) /')[1]
        d['container'] = None if c == 'LCL' else c
        d['vessel'] = g(r'Vessel/Voyage: (.+)')[1].strip()
        m = g(r'ATD (.+?): (.+)')
        d['atd_port'] = PORTNAME[m[1]]; d['atd'] = dmy(m[2])
        m = g(r'ETA (.+?): (.+)')
        d['eta_port'] = PORTNAME[m[1]]; d['eta'] = dmy(m[2])
        d['rows'] = [dict(po=r[0], code=r[1], ctns=r[2], qty=r[3]) for r in
                     re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs', b, re.M)]
        assert d['rows']
    elif s.startswith('ETA update'):
        d['etype'] = 'eta'
        m = g(r'revised ETA (.+?) for HBL (\S+)')
        d['eta'] = dmy(m[1]); d['hbl'] = m[2]
    elif s.startswith('Arrival Notice'):
        d['etype'] = 'arrival'
        m = g(r'Shipment HBL (\S+) \((\S+)\) on (.+?) is arriving (.+?) on (.+?)\.')
        d['hbl'] = m[1]; d['container'] = None if m[2] == 'LCL' else m[2]
        d['vessel'] = m[3]; d['arr_port'] = PORTNAME[m[4]]; d['arr'] = dmy(m[5])
    elif s.startswith('Entry Summary'):
        d['etype'] = 'entry'
        m = g(r'Entry (\S+) filed for (\S+)\.')
        d['entry'] = m[1]; d['ident'] = m[2]
        v = lambda k: num(g(k + r': USD ([\d,.]+)')[1])
        d['value'] = v('Entered value')
        d['duty'] = '%.2f' % (float(v(r'Duty \(HTS\)')) + float(v('Section 301')) + float(v('Additional duties')))
        d['fees'] = '%.2f' % (float(v('MPF')) + float(v('HMF')))
        d['total'] = v('Total duties and fees')
        assert abs(float(d['duty']) + float(d['fees']) - float(d['total'])) < 0.015, d['entry']
    elif s.startswith('Receipt complete'):
        d['etype'] = 'receipt'
        m = g(r'Receiving complete for (\S+) under (\S+)')
        d['ident'] = m[1]; d['rcv'] = m[2]
        d['disc'] = re.findall(r'^\s+(ACMH-\d+) .*?: expected (\d+), received (\d+), damaged (\d+)', b, re.M)
    else:
        raise ValueError(s)
    return d
