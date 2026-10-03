import re, glob, os, json, hashlib, email.utils
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pypdf
EXP='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-i-lmlh_664/ingest/work/exports'
NY=ZoneInfo('America/New_York'); CN=timezone(timedelta(hours=8))
def sha(b): return hashlib.sha256(b).hexdigest()
def num(s): return s.replace(',','')
docs=[]

# ---------- PDFs
for f in sorted(glob.glob(EXP+'/supplier_docs/*.pdf')):
    b=open(f,'rb').read(); bn=os.path.basename(f)
    t="\n".join(p.extract_text() for p in pypdf.PdfReader(f).pages)
    d=dict(hash=sha(b),url='supplier_docs/'+bn,text=t,file=bn)
    L=t.split('\n')
    if bn.startswith('LCI-'):
        d['kind']='qc'
        d['report_no']=re.search(r'Report No\.: (\S+)',t).group(1)
        d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
        d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
        d['result']=re.search(r'Overall result: (\w+)',t).group(1)
        d['sample']=int(re.search(r'sample size (\d+)',t).group(1))
        d['inspector']=L[0].strip()
        d['supplier']=re.search(r'Supplier: (.*)',t).group(1)
        d['issued']=datetime.fromisoformat(d['date']+'T00:00:00+08:00')
    elif bn.startswith('CI-PL_'):
        d['kind']='ci'
        m=re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (\S+)',t)
        d['inv'],d['date'],d['po']=m.groups()
        m=re.search(r'From (\w+) to (\w+) by sea, (.*?)\s+Container: (\S+)\s+B/L: (\S+)',t)
        d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
        d['issued']=datetime.fromisoformat(d['date']+'T00:00:00+08:00')
        rows=[]
        for i,l in enumerate(L):
            m=re.match(r'^(\S+) .*',l)
            m2=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d.,]+) (USD|RMB) ([\d.,]+)$',l)
            if m2:
                code=L[i-2].split(' ')[0]
                rows.append(dict(code=code,hs=m2.group(1),qty=int(num(m2.group(2))),cur=m2.group(3),price=num(m2.group(4))))
        pl={}
        for l in L:
            m=re.match(r'^(\d+)-(\d+) (\S+) (\d+) (\d+) ([\d,]+) ',l)
            if m: pl[m.group(3)]=pl.get(m.group(3),0)+int(m.group(4))
        for r in rows: r['ctns']=pl.get(r['code'])
        d['rows']=rows; d['plcodes']=list(pl)
    else:
        d['kind']='pi'
        d['name_cn']=L[0].strip(); d['name_caps']=L[1].strip(); d['address']=L[2].strip()
        d['pi_no']=re.search(r'PI No\.: (\S+)',t).group(1)
        d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
        d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
        d['issued']=datetime.fromisoformat(d['date']+'T00:00:00+08:00')
        rows=[]
        for i,l in enumerate(L):
            m=re.match(r'^([\d,]+) (\d+) (USD|RMB) ([\d.,]+) (USD|RMB) ([\d.,]+)$',l)
            if m:
                rows.append(dict(code=L[i-2].split(' ')[0],qty=int(num(m.group(1))),ctns=int(m.group(2)),cur=m.group(3),price=num(m.group(4))))
        d['rows']=rows
        d['price_term']=re.search(r'Price term: (.*)',t).group(1).strip()
        d['payment']=re.search(r'Payment: (.*)',t).group(1).strip()
        d['delivery']=re.search(r'Delivery: about (\w+ \d+, \d{4})',t).group(1)
        d['beneficiary']=re.search(r'Beneficiary: (.*)',t).group(1).strip()
    docs.append(d)

# ---------- chats
CODES={'DGRF':'DGRF','FSMJ':'FSMJ','HZTY':'HZTY','NBBW':'NBBW','NBQS':'NBQS','SZHT':'SZHT','XMYD':'XMYD','YWLX':'YWLX'}
for f in sorted(glob.glob(EXP+'/wechat/*.txt')):
    bn=os.path.basename(f); sup=bn.split('_')[0]
    raw=open(f,encoding='utf-8').read()
    blocks=re.split(r'\n\s*\n',raw.strip('\n'))
    n=0
    for blk in blocks:
        lines=blk.split('\n')
        m=re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$',lines[0])
        if not m: continue
        n+=1
        ts=datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
        docs.append(dict(kind='chat',hash=sha('\n'.join(lines).encode()),url=f'wechat/{bn}#{n}',file=bn,sup=sup,
            n=n,issued=ts,sender=m.group(2),text='\n'.join(lines[1:])))

# ---------- emails
raw=open(EXP+'/email/ops_inbox.mbox','rb').read()
parts=[p for p in re.split(rb'(?m)^(?=From \S+@\S+ )',raw) if p.strip()]
for p in parts:
    if p.endswith(b'\n\n'): p=p[:-1]
    s=p.decode()
    hdr,_,body=s.partition('\n\n')
    H={}
    for l in hdr.split('\n')[1:]:
        k,_,v=l.partition(': ');H[k]=v
    mid=H['Message-ID'].strip('<>')
    dt=email.utils.parsedate_to_datetime(H['Date'])
    docs.append(dict(kind='email',hash=sha(p),url='mid:'+mid,subject=H['Subject'],issued=dt,body=body,frm=H['From']))
if __name__=='__main__':
    import collections
    print(collections.Counter(d['kind'] for d in docs))
    print(len(set(d['hash'] for d in docs)))
