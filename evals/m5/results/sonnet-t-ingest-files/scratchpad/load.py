"""Load every document in the exports into plain python structures (no store access)."""
import re, glob, os, json, hashlib, email, email.utils
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-t-ht3vspo0/ingest/work/exports'
NY = ZoneInfo('America/New_York')
CN = timezone(timedelta(hours=8))
LA = ZoneInfo('America/Los_Angeles')

SUP_CN = {'深圳市和泰电器有限公司': 'SZHT', '义乌市蓝欣纺织品有限公司': 'YWLX', '佛山市明嘉陶瓷有限公司': 'FSMJ',
          '宁波明途家居用品有限公司': 'NBBW', '宁波启盛不锈钢制品有限公司': 'NBQS', '东莞市瑞丰硅胶制品有限公司': 'DGRF',
          '杭州天艺玻璃制品有限公司': 'HZTY', '厦门远达竹木制品有限公司': 'XMYD'}
PORTS = {'Yantian': 'CNYTN', 'Ningbo': 'CNNGB', 'Xiamen': 'CNXMN', 'Nansha': 'CNNSA',
         'New York/Newark': 'USNYC', 'Los Angeles': 'USLAX'}
CURR = {'RMB': 'CNY', 'USD': 'USD'}


def num(s):
    return s.replace(',', '')


def pdf_docs():
    hashes = json.load(open(os.path.join(HERE, 'hashes.json')))
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, 'txt', '*.txt'))):
        n = os.path.basename(f)[:-4]
        t = open(f).read()
        d = dict(name=n, text=t, hash=hashes[n], url=f'supplier_docs/{n}.pdf')
        if n.startswith('LCI'):
            d['kind'] = 'qc'
            d.update(parse_qc(t))
        elif n.startswith('CI-PL'):
            d['kind'] = 'ci'
            d.update(parse_ci(t))
        else:
            d['kind'] = 'pi'
            d.update(parse_pi(t))
        out.append(d)
    return out


def at_cn(ds):
    y, m, dd = map(int, ds.split('-'))
    return datetime(y, m, dd, tzinfo=CN)


def parse_pi(t):
    L = t.split('\n')
    r = {}
    r['sup_cn'] = L[0].strip()
    r['sup_code'] = SUP_CN[r['sup_cn']]
    r['sup_en_caps'] = L[1].strip()
    r['address'] = L[2].strip()
    r['pi_no'] = re.search(r'PI No\.: (\S+)', t).group(1)
    r['date'] = re.search(r'Date: (\d{4}-\d\d-\d\d)', t).group(1)
    r['issued'] = at_cn(r['date'])
    r['po'] = re.search(r'Your PO: (PO-\d+-\d+)', t).group(1)
    rows = []
    for i, l in enumerate(L):
        m = re.match(r'^([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$', l)
        if m:
            item = L[i - 2].split(' ')[0]
            rows.append(dict(item=item, qty=num(m.group(1)), ctns=m.group(2), cur=m.group(3), price=num(m.group(4)),
                             amount=num(m.group(5))))
    r['rows'] = rows
    r['cur'] = CURR[rows[0]['cur']]
    r['total'] = num(re.search(r'TOTAL (?:USD|RMB) ([\d,.]+)', t).group(1))
    r['term'] = re.search(r'Price term: (.*)', t).group(1).strip()
    r['payment'] = re.search(r'Payment: (.*)', t).group(1).strip()
    dl = re.search(r'Delivery: about (\w+ \d+, \d{4})', t).group(1)
    r['etd'] = datetime.strptime(dl, '%b %d, %Y').date()
    r['bene'] = re.search(r'Beneficiary: (.*)', t).group(1).strip()
    m = re.search(r'(\d+)% deposit', r['payment'])
    r['deposit_pct'] = int(m.group(1)) if m else 0
    r['port'] = PORTS[r['term'].split()[-1]]
    return r


def parse_ci(t):
    r = {}
    r['inv_no'] = re.search(r'Invoice No\.: (\S+)', t).group(1)
    r['date'] = re.search(r'Invoice No\.: \S+\s+Date: (\d{4}-\d\d-\d\d)', t).group(1)
    r['issued'] = at_cn(r['date'])
    r['orders'] = re.findall(r'Order: (PO-\d+-\d+)', t)
    m = re.search(r'From (\w+) to (\w+) by sea, (.*?)\s+Container: (\S+)\s+B/L: (\S+)', t)
    r['origin'], r['dest'], r['vessel'], r['container'], r['hbl'] = m.groups()
    rows = []
    L = t.split('\n')
    for i, l in enumerate(L):
        m = re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$', l)
        if m:
            rows.append(dict(item=L[i - 2].split(' ')[0], hs=m.group(1), qty=num(m.group(2)), cur=m.group(3),
                             price=num(m.group(4))))
    r['rows'] = rows
    pl = {}
    for l in L:
        m = re.match(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) [\d,.]+ \S+ [\d.]+$', l)
        if m:
            pl[m.group(1)] = dict(ctns=m.group(2), pcs=num(m.group(4)))
    r['pl'] = pl
    r['marks'] = re.search(r'Shipping marks: ACME HEARTH / (\S+)', t).group(1)
    return r


def parse_qc(t):
    r = {}
    r['agency'] = t.split('\n')[0].strip()
    r['report_no'] = re.search(r'Report No\.: (\S+)', t).group(1)
    r['date'] = re.search(r'Inspection date: (\S+)', t).group(1)
    r['issued'] = at_cn(r['date'])
    r['po'] = re.search(r'PO No\.: (PO-\d+-\d+)', t).group(1)
    r['result'] = re.search(r'Overall result: (\w+)', t).group(1)
    r['sample'] = re.search(r'sample size (\d+)', t).group(1)
    return r


CHAT_SUP = {'DGRF_Jason': 'DGRF', 'FSMJ_Grace': 'FSMJ', 'HZTY_Coco': 'HZTY', 'NBBW_Lily': 'NBBW',
            'NBQS_Sunny': 'NBQS', 'SZHT_Kevin': 'SZHT', 'XMYD_Eric': 'XMYD', 'YWLX_Amy': 'YWLX'}


def chat_docs():
    out = []
    for f in sorted(glob.glob(os.path.join(EXP, 'wechat', '*.txt'))):
        base = os.path.basename(f)
        raw = open(f, encoding='utf-8').read()
        msgs = []
        cur = None
        for l in raw.split('\n'):
            m = re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$', l)
            if m:
                if cur: msgs.append(cur)
                cur = dict(ts=m.group(1), sender=m.group(2), lines=[l])
            elif cur is not None:
                if l.strip() == '':
                    msgs.append(cur); cur = None
                else:
                    cur['lines'].append(l)
        if cur: msgs.append(cur)
        for n, m in enumerate(msgs, 1):
            body = '\n'.join(m['lines'])
            dt = datetime.strptime(m['ts'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            out.append(dict(kind='chat', file=base[:-4], sup=CHAT_SUP[base[:-4]], n=n,
                            hash=hashlib.sha256(body.encode('utf-8')).hexdigest(),
                            url=f'wechat/{base}#{n}', issued=dt, ours=m['sender'].startswith('Maya'),
                            text='\n'.join(m['lines'][1:])))
    return out


def email_docs():
    raw = open(os.path.join(EXP, 'email', 'ops_inbox.mbox'), 'rb').read()
    parts = [p for p in re.split(rb'(?m)^(?=From \S+ \w{3} \w{3} +\d+ \d\d:\d\d:\d\d \d{4}\r?$)', raw) if p.strip()]
    out = []
    for p in parts:
        if p.endswith(b'\n\n'):
            p = p[:-1]
        msg = email.message_from_bytes(p.split(b'\n', 1)[1])
        mid = msg['Message-ID'].strip('<>')
        dt = email.utils.parsedate_to_datetime(msg['Date'])
        body = msg.get_payload(decode=True).decode('utf-8')
        out.append(dict(kind='email', hash=hashlib.sha256(p).hexdigest(), url=f'mid:{mid}', issued=dt,
                        subject=msg['Subject'], sender=msg['From'], body=body))
    return out


def tz_for(locode):
    return {'USNYC': NY, 'USLAX': LA}.get(locode, CN)


def local_midnight(d, locode):
    """a date given without a time = 00:00 at the port's local time"""
    return datetime(d.year, d.month, d.day, tzinfo=tz_for(locode))


if __name__ == '__main__':
    p = pdf_docs(); c = chat_docs(); e = email_docs()
    print(len(p), len(c), len(e))
    import collections
    print(collections.Counter(d['kind'] for d in p))
    print(len({d['hash'] for d in p + c + e}), len(p + c + e))
