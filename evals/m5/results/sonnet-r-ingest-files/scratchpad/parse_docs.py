import re,glob,os,hashlib,json,pypdf
from datetime import datetime,date
from zoneinfo import ZoneInfo
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-r-fnyh54rx/ingest/work/exports/'
CST=ZoneInfo('Asia/Shanghai')
def num(s): return s.replace(',','')
def pdf_docs():
    out=[]
    for f in sorted(glob.glob(W+'supplier_docs/*.pdf')):
        b=open(f,'rb').read()
        t="\n".join(p.extract_text() for p in pypdf.PdfReader(f).pages)
        d=dict(hash=hashlib.sha256(b).hexdigest(),url='supplier_docs/'+os.path.basename(f),text=t,name=os.path.basename(f)[:-4])
        L=t.split('\n')
        if 'PROFORMA INVOICE' in t: d.update(parse_pi(t,L))
        elif 'COMMERCIAL INVOICE' in t: d.update(parse_ci(t,L))
        elif 'Inspection Report' in t: d.update(parse_qc(t,L))
        else: raise Exception(f)
        out.append(d)
    return out
def mid(dstr): return datetime.strptime(dstr,'%Y-%m-%d').replace(tzinfo=CST)
def parse_pi(t,L):
    r=dict(kind='pi')
    r['name_cn']=L[0]; r['addr']=L[2]
    r['code']=re.search(r'sales@(\w+)\.example',t).group(1).upper()
    r['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
    r['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    r['issued']=mid(r['date'])
    r['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    r['legal']=re.search(r'Beneficiary: (.+)',t).group(1).strip()
    r['incoterm']=re.search(r'Price term: (.+)',t).group(1).strip()
    r['payment']=re.search(r'Payment: (.+)',t).group(1).strip()
    m=re.search(r'Delivery: about (\w+ \d+, \d{4}) \(ETD\)',t)
    r['etd']=datetime.strptime(m.group(1),'%b %d, %Y').date().isoformat()
    r['dep']=re.search(r'(\d+)% deposit',r['payment'])
    r['dep']=int(r['dep'].group(1)) if r['dep'] else None
    items=[]
    for m in re.finditer(r'^(\S+) .*\n.*\n([\d,]+) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',t,re.M):
        items.append(dict(item=m.group(1),qty=num(m.group(2)),ctns=num(m.group(3)),cur=m.group(4),price=num(m.group(5)),amt=num(m.group(6))))
    r['items']=items
    tot=re.search(r'TOTAL (USD|RMB) ([\d,.]+)',t)
    r['cur']='CNY' if tot.group(1)=='RMB' else 'USD'; r['total']=num(tot.group(2))
    from decimal import Decimal as D
    assert sum(D(i['amt']) for i in items)==D(r['total']),r['pi']
    for i in items: assert D(i['qty'])*D(i['price'])==D(i['amt'])
    return r
def parse_ci(t,L):
    r=dict(kind='ci')
    r['code']=re.search(r'sales@(\w+)\.example',t).group(1).upper()
    m=re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (\S+)',t)
    r['inv'],r['date'],r['po']=m.groups(); r['issued']=mid(r['date'])
    m=re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t)
    r['origin'],r['dest'],r['vessel'],r['container'],r['hbl']=m.groups()
    items=[]
    for m in re.finditer(r'^(\S+) .*\n.*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) (?:USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d.,]+)$',t,re.M):
        items.append(dict(item=m.group(1),hs=m.group(2),qty=num(m.group(3))))
    r['items']=items
    pl={}
    for m in re.finditer(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) ',t,re.M):
        pl[m.group(1)]=dict(ctns=m.group(2),pcs=num(m.group(4)))
    r['pl']=pl
    assert set(pl)=={i['item'] for i in items},r['inv']
    for i in items: assert pl[i['item']]['pcs']==i['qty']
    return r
def parse_qc(t,L):
    r=dict(kind='qc')
    r['report']=re.search(r'Report No\.: (\S+)',t).group(1)
    r['date']=re.search(r'Inspection date: (\S+)',t).group(1); r['issued']=mid(r['date'])
    r['po']=re.search(r'PO No\.: (\S+)',t).group(1)
    r['result']=re.search(r'Overall result: (\w+)',t).group(1)
    r['sample']=re.search(r'sample size (\d+)',t).group(1)
    r['agency']=L[0].title()
    return r
if __name__=='__main__':
    ds=pdf_docs()
    from collections import Counter
    print(Counter(d['kind'] for d in ds))
    for d in ds:
        if d['kind']=='pi': print(d['pi'],d['po'],d['code'],d['cur'],d['dep'],d['etd'],len(d['items']),d['incoterm'],d['payment'])
    for d in ds:
        if d['kind']=='ci': print(d['inv'],d['po'],d['container'],d['hbl'],d['vessel'],d['origin'],d['dest'],len(d['items']))
    for d in ds:
        if d['kind']=='qc': print(d['report'],d['po'],d['result'],d['sample'],d['agency'])
