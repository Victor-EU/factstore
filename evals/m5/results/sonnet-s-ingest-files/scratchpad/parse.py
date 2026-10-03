import re, glob, os, hashlib, mailbox, datetime as dt
from zoneinfo import ZoneInfo
import pypdf

ROOT = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-s-kfe1uo8m/ingest/work/exports'
NY = ZoneInfo('America/New_York')
LA = ZoneInfo('America/Los_Angeles')
CN = dt.timezone(dt.timedelta(hours=8))
MON = {m: i + 1 for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}
PFX = {'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'MT': 'NBBW', 'QS': 'NBQS', 'RF': 'DGRF', 'TY': 'HZTY', 'YD': 'XMYD'}
CHAT_SUP = {'DGRF': 'DGRF', 'FSMJ': 'FSMJ', 'HZTY': 'HZTY', 'NBBW': 'NBBW', 'NBQS': 'NBQS', 'SZHT': 'SZHT',
            'XMYD': 'XMYD', 'YWLX': 'YWLX'}
PORT = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Nansha': 'CNNSA', 'Xiamen': 'CNXMN'}
TZ_OF = {'CN': CN, 'USNYC': NY, 'USLAX': LA}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def num(s):
    return s.replace(',', '')


def local_midnight(d, loc):
    tz = TZ_OF.get(loc[:2] if loc.startswith('CN') else loc, CN)
    return dt.datetime(d.year, d.month, d.day, tzinfo=tz)


def iso(t):
    s = t.isoformat()
    return s


def pdf_text(f):
    return "\n".join(p.extract_text() or '' for p in pypdf.PdfReader(f).pages)


def parse_pi(t, f):
    d = {}
    d['pi'] = re.search(r'PI No\.: (\S+)', t).group(1)
    d['date'] = dt.date.fromisoformat(re.search(r'Date: (\d{4}-\d\d-\d\d)', t).group(1))
    d['po'] = re.search(r'Your PO: (PO-\d{4}-\d{4})', t).group(1)
    lines = t.split('\n')
    d['name_cn'] = lines[0].strip()
    d['address'] = lines[2].strip()
    d['bene'] = re.search(r'Beneficiary: (.+)', t).group(1).strip()
    d['incoterm'] = re.search(r'Price term: (.+)', t).group(1).strip()
    d['payment'] = re.search(r'Payment: (.+)', t).group(1).strip()
    m = re.search(r'Delivery: about (\w+) (\d+), (\d{4}) \(ETD\)', t)
    d['etd'] = dt.date(int(m.group(3)), MON[m.group(1)[:3]], int(m.group(2)))
    rows = re.findall(r'^(\S+) [^\n]*\n[^\n]*\n([\d,]+) (\d+) (USD|RMB|CNY) ([\d.,]+) (?:USD|RMB|CNY) ([\d.,]+)$', t, re.M)
    d['rows'] = [dict(item=r[0], qty=num(r[1]), ctns=r[2], ccy='CNY' if r[3] == 'RMB' else r[3], price=num(r[4]),
                      amt=num(r[5])) for r in rows]
    m = re.search(r'TOTAL (USD|RMB|CNY) ([\d.,]+)', t)
    d['ccy'] = 'CNY' if m.group(1) == 'RMB' else m.group(1)
    d['total'] = num(m.group(2))
    assert abs(sum(float(r['amt']) for r in d['rows']) - float(d['total'])) < 0.01, f
    m = re.search(r'T/T (\d+)% deposit', d['payment'])
    d['dep_pct'] = int(m.group(1)) if m else 0
    port = re.search(r'FOB (\w+)', d['incoterm']).group(1)
    d['port'] = PORT[port]
    return d


def parse_ci(t, f):
    d = {}
    m = re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})', t)
    d['inv'], d['date'], d['po'] = m.group(1), dt.date.fromisoformat(m.group(2)), m.group(3)
    m = re.search(r'From (\w{5}) to (\w{5}) by sea, (MV [^\n]*?)\s+Container: (\S+)\s+B/L: (\S+)', t)
    d['origin'], d['dest'], d['vessel'], d['container'], d['hbl'] = m.groups()
    rows = re.findall(r'^(\S+) [^\n]*\n[^\n]*\n(\d{4}\.\d{2}\.\d{4}) ([\d,]+) (USD|RMB|CNY) ([\d.,]+) (?:USD|RMB|CNY) ([\d.,]+)$', t, re.M)
    d['rows'] = [dict(item=r[0], hs=r[1], qty=num(r[2])) for r in rows]
    pl = re.findall(r'^(\d+(?:-\d+)?) (\S+) (\d+) (\d+) ([\d,]+) ', t.split('PACKING LIST')[1], re.M)
    d['ctns'] = {p[1]: p[2] for p in pl}
    assert len(d['rows']) == len(d['ctns']) and len(d['rows']) > 0, (f, len(d['rows']), len(d['ctns']))
    for r in d['rows']:
        assert r['item'] in d['ctns'], (f, r)
    return d


def parse_lci(t, f):
    d = {}
    d['agency'] = t.split('\n')[0].strip().title()
    d['report'] = re.search(r'Report No\.: (\S+)', t).group(1)
    d['date'] = dt.date.fromisoformat(re.search(r'Inspection date: (\d{4}-\d\d-\d\d)', t).group(1))
    d['po'] = re.search(r'PO No\.: (PO-\d{4}-\d{4})', t).group(1)
    d['sample'] = re.search(r'sample size (\d+)', t).group(1)
    d['result'] = re.search(r'Overall result: (\w+)', t).group(1)
    return d


def load_docs():
    ev = []
    for f in sorted(glob.glob(ROOT + '/supplier_docs/*.pdf')):
        b = open(f, 'rb').read()
        t = pdf_text(f)
        name = os.path.basename(f)
        e = dict(hash=sha(b), url='supplier_docs/' + name, file=name)
        if name.startswith('CI-PL_'):
            e['kind'] = 'ci'; e['d'] = parse_ci(t, name); date = e['d']['date']
        elif name.startswith('LCI-'):
            e['kind'] = 'lci'; e['d'] = parse_lci(t, name); date = e['d']['date']
        else:
            e['kind'] = 'pi'; e['d'] = parse_pi(t, name); date = e['d']['date']
            e['d']['sup'] = PFX[name[:2]]
        e['t'] = dt.datetime(date.year, date.month, date.day, tzinfo=CN)
        ev.append(e)
    return ev


def load_chats():
    ev = []
    for f in sorted(glob.glob(ROOT + '/wechat/*.txt')):
        name = os.path.basename(f)
        sup = name.split('_')[0]
        raw = open(f, 'rb').read().decode('utf-8')
        blocks = re.split(r'\n\n', raw)
        n = 0
        for blk in blocks:
            lines = blk.strip('\n').split('\n')
            m = re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$', lines[0])
            if not m:
                continue
            n += 1
            t = dt.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            text = '\n'.join(lines[1:])
            raw_msg = ('\n'.join(lines) + '\n').encode('utf-8')
            ev.append(dict(kind='chat', t=t, hash=sha(raw_msg), url=f'wechat/{name}#{n}', sup=sup,
                           me=m.group(2).startswith('Maya'), text=text, n=n, file=name))
    return ev


def d_of(s):
    m = re.match(r'(\d+) (\w{3}) (\d{4})', s.strip())
    return dt.date(int(m.group(3)), MON[m.group(2)], int(m.group(1)))


def load_mail():
    ev = []
    mb = mailbox.mbox(ROOT + '/email/ops_inbox.mbox')
    for k, m in mb.items():
        raw = mb.get_bytes(k, from_=True)
        if not raw.endswith(b'\n'):
            raw += b'\n'
        subj = m['Subject']
        body = m.get_payload()
        t = email_date(m['Date'])
        e = dict(hash=sha(raw), url='mid:' + m['Message-ID'].strip('<>'), t=t, subj=subj, body=body, k=k)
        d = {}
        if subj.startswith('Booking Confirmation'):
            e['kind'] = 'booking'
            d['so'] = re.search(r'^SO: (\S+)', body, re.M).group(1)
            eq = re.search(r'^Equipment: (.+)', body, re.M).group(1)
            d['mode'] = 'LCL' if eq.startswith('LCL') else re.search(r'x(\d+\w+)', eq).group(1)
            d['vessel'] = re.search(r'^Vessel/Voyage: (.+)', body, re.M).group(1).strip()
            m2 = re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)', body)
            d['pol'], d['pod'] = m2.groups()
            d['etd'] = d_of(re.search(r'^ETD: (.+)', body, re.M).group(1))
            d['eta'] = d_of(re.search(r'^ETA: (.+)', body, re.M).group(1))
            d['pos_raw'] = re.search(r'^POs: (.+)', body, re.M).group(1)
        elif subj.startswith('RE: Booking'):
            e['kind'] = 'roll'
            m2 = re.search(r'SO (\S+) due to .*New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})', body)
            d['so'] = m2.group(1); d['etd'] = d_of(m2.group(2)); d['eta'] = d_of(m2.group(3))
        elif subj.startswith('Shipping Advice'):
            e['kind'] = 'prealert'
            d['hbl'] = re.search(r'^HBL: (\S+)', body, re.M).group(1)
            cs = re.search(r'^Container/Seal: (\S+)', body, re.M).group(1)
            d['container'] = cs
            d['vessel'] = re.search(r'^Vessel/Voyage: (.+)', body, re.M).group(1).strip()
            m2 = re.search(r'^ATD [\w ]+: (.+)', body, re.M)
            d['atd'] = d_of(m2.group(1))
            m2 = re.search(r'^ETA [\w /]+: (.+)', body, re.M)
            d['eta'] = d_of(m2.group(1))
            d['lines'] = [dict(po=a, item=b, ctns=c, qty=q) for a, b, c, q in
                          re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs', body, re.M)]
        elif subj.startswith('ETA update'):
            e['kind'] = 'eta'
            m2 = re.search(r'revised ETA (\d+ \w+ \d{4}) for HBL (\S+)', body)
            d['eta'] = d_of(m2.group(1)); d['hbl'] = m2.group(2)
        elif subj.startswith('Arrival Notice'):
            e['kind'] = 'arrival'
            m2 = re.search(r'HBL (\S+) \((\S+)\) on (MV [^\n]*?) is arriving ([\w/ ]+?) on (\d+ \w+ \d{4})', body)
            d['hbl'] = m2.group(1); d['port'] = m2.group(4); d['date'] = d_of(m2.group(5))
        elif subj.startswith('Receipt complete'):
            e['kind'] = 'receipt'
            m2 = re.search(r'Receiving complete for (\S+) under (GSF-RCV-\d+)', body)
            d['ref'] = m2.group(1); d['rcv'] = m2.group(2)
            d['disc'] = re.findall(r'^\s+(ACMH-\d+) .*?expected (\d+), received (\d+), damaged (\d+)', body, re.M)
        elif subj.startswith('Entry Summary'):
            e['kind'] = 'entry'
            d['entry'] = re.search(r'Entry (\S+) filed for (\S+)\.', body).group(1)
            d['ref'] = re.search(r'Entry (\S+) filed for (\S+)\.', body).group(2)
            g = lambda lab: num(re.search(lab + r': USD ([\d.,]+)', body).group(1))
            d['value'] = g('Entered value'); d['hts'] = g(r'Duty \(HTS\)'); d['s301'] = g('Section 301')
            d['add'] = g('Additional duties'); d['mpf'] = g('MPF'); d['hmf'] = g('HMF'); d['total'] = g('Total duties and fees')
        else:
            raise Exception(subj)
        e['d'] = d
        ev.append(e)
    return ev


def email_date(s):
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(s)


if __name__ == '__main__':
    docs = load_docs(); chats = load_chats(); mail = load_mail()
    import collections
    print(collections.Counter(e['kind'] for e in docs), len(chats), collections.Counter(e['kind'] for e in mail))
