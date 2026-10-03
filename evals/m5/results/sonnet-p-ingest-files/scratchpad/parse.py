import re,glob,os,hashlib,json,pypdf
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-p-v76cz30z/ingest/work/exports'
def num(s): return s.replace(',','')
CUR={'RMB':'CNY','USD':'USD'}
def pdf_text(f):
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(f).pages)
docs=[]
for f in sorted(glob.glob(EX+'/supplier_docs/*.pdf')):
    b=open(f,'rb').read(); h=hashlib.sha256(b).hexdigest(); t=pdf_text(f); L=t.split('\n')
    url='supplier_docs/'+os.path.basename(f)
    d=dict(hash=h,url=url,text=t)
    if 'PROFORMA INVOICE' in t:
        d['kind']='PI'
        d['name_cn']=L[0]; d['addr']=L[2]
        d['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
        d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
        d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
        d['name']=re.search(r'Beneficiary: (.+)',t).group(1).strip()
        d['incoterm']=re.search(r'Price term: (.+)',t).group(1).strip()
        d['payment']=re.search(r'Payment: (.+)',t).group(1).strip()
        m=re.search(r'Delivery: about (\w+ \d+, \d{4})',t); d['etd']=datetime.strptime(m.group(1),'%b %d, %Y').date().isoformat()
        rows=[]
        for i,l in enumerate(L):
            m=re.match(r'^([\d,]+) ([\d,]+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$',l)
            if m: rows.append(dict(item=L[i-2].split()[0],qty=num(m.group(1)),cur=CUR[m.group(3)],price=num(m.group(4))))
        d['rows']=rows; d['cur']=rows[0]['cur']
        d['supplier_code']=None
    elif 'COMMERCIAL INVOICE' in t:
        d['kind']='CI'
        m=re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})',t)
        d['inv'],d['date'],d['po']=m.groups()
        m=re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t)
        d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
        rows=[]
        for i,l in enumerate(L):
            m=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$',l)
            if m: rows.append(dict(item=L[i-2].split()[0],hs=m.group(1),qty=num(m.group(2))))
        d['rows']=rows
        ct={}
        for l in L:
            m=re.match(r'^\d+(?:-\d+)? (\S+) (\d+) (\d+) ([\d,]+) ',l)
            if m: ct[m.group(1)]=ct.get(m.group(1),0)+int(m.group(2))
        d['cartons']=ct
    elif 'Pre-Shipment Inspection Report' in t:
        d['kind']='QC'
        g=lambda p: re.search(p,t).group(1).strip()
        d['report']=g(r'Report No\.: (\S+)'); d['date']=g(r'Inspection date: (\S+)')
        d['po']=g(r'PO No\.: (\S+)'); d['result']=g(r'Overall result: (\w+)')
        d['sample']=g(r'sample size (\d+)'); d['inspector']=L[0]
    else: d['kind']='?'
    docs.append(d)
# emails
raw=open(EX+'/email/ops_inbox.mbox','rb').read()
parts=[p for p in re.split(rb'(?m)^(?=From \S+@\S+ )',raw) if p.strip()]
emails=[]
parts=[p[:-1] if p.endswith(b'\n\n') else p for p in parts]
for p in parts:
    s=p.decode()
    hdr,body=s.split('\n\n',1)
    H=dict(re.findall(r'(?m)^([A-Za-z-]+): (.*)$',hdr))
    dt=parsedate_to_datetime(H['Date'])
    emails.append(dict(raw=p,hash=hashlib.sha256(p).hexdigest(),url='mid:'+H['Message-ID'].strip('<>'),
        subject=H['Subject'],dt=dt,body=body,frm=H['From']))
# chats
chats=[]
for f in sorted(glob.glob(EX+'/wechat/*.txt')):
    t=open(f,encoding='utf-8').read()
    # messages: header line "YYYY-MM-DD HH:MM:SS sender" followed by text lines until blank line
    fn=os.path.basename(f)
    lines=t.split('\n')
    msgs=[];cur=None
    for i,l in enumerate(lines):
        if re.match(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ',l):
            cur=[l];msgs.append(cur)
        elif l=='' : cur=None
        elif cur is not None: cur.append(l)
    for n,m in enumerate(msgs,1):
        txt='\n'.join(m)
        chats.append(dict(file=fn,n=n,text=txt,hash=hashlib.sha256(txt.encode()).hexdigest(),url=f'wechat/{fn}#{n}',
            ts=m[0][:19],sender=m[0][20:],body='\n'.join(m[1:])))
if __name__=='__main__':
    from collections import Counter
    print(Counter(d['kind'] for d in docs), len(emails), len(chats))
    for d in docs:
        if d['kind']=='PI': print(d['pi'],d['date'],d['po'],d['etd'],d['cur'],len(d['rows']),d['incoterm'],d['payment'])
