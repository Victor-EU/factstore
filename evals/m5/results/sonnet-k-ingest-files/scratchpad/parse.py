import re,json,hashlib,glob,os
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
S=os.path.dirname(os.path.abspath(__file__))
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-k-mid97be7/ingest/work/exports'
SH=ZoneInfo('Asia/Shanghai');NY=ZoneInfo('America/New_York');LA=ZoneInfo('America/Los_Angeles')
PFX={'HT':'SZHT','LX':'YWLX','MJ':'FSMJ','MT':'NBBW','QS':'NBQS','RF':'DGRF','TY':'HZTY','YD':'XMYD'}
CHATSUP={'DGRF':'DGRF','FSMJ':'FSMJ','HZTY':'HZTY','NBBW':'NBBW','NBQS':'NBQS','SZHT':'SZHT','XMYD':'XMYD','YWLX':'YWLX'}
PORTS={'Ningbo':'CNNGB','Yantian':'CNYTN','Xiamen':'CNXMN','Nansha':'CNNSA'}
def num(s): return Decimal(s.replace(',',''))
def iso(dt): return dt.isoformat()
def day_at(d,tz): return datetime(d.year,d.month,d.day,tzinfo=tz)
def portz(code): return {'US':None}.get(code[:2]) or (SH if code.startswith('CN') else (NY if code=='USNYC' else LA))
def dmy(s): return datetime.strptime(s,'%d %b %Y').date()
idx={n:h for n,h,l in json.load(open(S+'/pdfidx.json'))}
def txt(n): return open(f'{S}/txt/{n}.txt').read()

def parse_pi(n):
    t=txt(n); L=[l.strip() for l in t.split('\n')]
    d={'name':n,'hash':idx[n],'url':f'supplier_docs/{n}.pdf','kind':'pi'}
    d['sup']=PFX[n[:2]]
    d['name_cn']=L[0]
    d['address']=L[2]
    m=re.search(r'PI No\.: (\S+)',t); d['pi']=m.group(1)
    m=re.search(r'Date: (\d{4}-\d\d-\d\d)',t); d['date']=m.group(1)
    d['issued']=iso(day_at(date.fromisoformat(d['date']),SH))
    d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    d['incoterm']=re.search(r'Price term: (.*)',t).group(1).strip()
    d['port']=PORTS[d['incoterm'].split()[-1]]
    d['terms']=re.search(r'Payment: (.*)',t).group(1).strip()
    m=re.search(r'Delivery: about (\w{3} \d\d, \d{4}) \(ETD\)',t); d['etd']=datetime.strptime(m.group(1),'%b %d, %Y').date().isoformat()
    d['bene']=re.search(r'Beneficiary: (.*)',t).group(1).strip()
    items=[];total=Decimal(0)
    for i,l in enumerate(L):
        m=re.match(r'^([\d,]+) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',l)
        if m:
            item=L[i-2].split()[0]
            q,c,cur,p,a=m.groups()
            assert num(q)*num(p)==num(a),(n,l)
            items.append(dict(item=item,qty=str(num(q)),ctns=str(num(c)),price=str(num(p)),amt=num(a),cur='CNY' if cur=='RMB' else cur))
            total+=num(a)
    d['items']=items
    d['cur']=items[0]['cur']
    m=re.search(r'TOTAL (?:USD|RMB) ([\d,.]+)',t); assert num(m.group(1))==total,(n,total)
    pct=re.search(r'(\d+)% deposit',d['terms']); d['dep']=int(pct.group(1)) if pct else 0; d['total']=total
    return d

def parse_ci(n):
    t=txt(n); L=[l.strip() for l in t.split('\n')]
    d={'name':n,'hash':idx[n],'url':f'supplier_docs/{n}.pdf','kind':'ci'}
    d['sup']=PFX[n.split('_')[1][:2]]
    m=re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})',t); d['inv'],d['date'],d['po']=m.groups()
    d['issued']=iso(day_at(date.fromisoformat(d['date']),SH))
    m=re.search(r'From (\w+) to (\w+) by sea, (MV .*?)\s+Container: (\S+)\s+B/L: (\S+)',t); d['origin'],d['dest'],d['vessel'],d['cont'],d['hbl']=m.groups()
    rows=[];pl={}
    for i,l in enumerate(L):
        m=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',l)
        if m:
            rows.append(dict(item=L[i-2].split()[0],hs=m.group(1),qty=str(num(m.group(2))),price=m.group(4)))
        m=re.match(r'^(\d+(?:-\d+)?) (\S+) (\d+) (\d+) ([\d,]+) [\d,.]+ \S+ [\d.]+$',l)
        if m:
            pl[m.group(2)]=dict(ctns=m.group(3),pcs=str(num(m.group(5))),perctn=m.group(4))
    d['rows']=rows;d['pl']=pl
    for r in rows:
        assert r['item'] in pl and pl[r['item']]['pcs']==r['qty'],(n,r)
    assert len(rows)==len(pl),n
    d['order_ref']=re.search(r'Invoice No\.: CI-(\S+)',t).group(1)
    return d

def parse_qc(n):
    t=txt(n)
    d={'name':n,'hash':idx[n],'url':f'supplier_docs/{n}.pdf','kind':'qc'}
    d['report']=re.search(r'Report No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
    d['issued']=iso(day_at(date.fromisoformat(d['date']),SH))
    d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
    d['result']=re.search(r'Overall result: (\w+)',t).group(1)
    d['n']=re.search(r'sample size (\d+)',t).group(1)
    d['inspector']=' '.join(w.capitalize() for w in t.split('\n')[0].split())
    return d

def parse_emails():
    E=json.load(open(S+'/emails.json'));out=[]
    raw=open(EX+'/email/ops_inbox.mbox','rb').read()
    for e in E:
        t=e['text']
        d={'kind':'email','hash':hashlib.sha256(t.encode()[:-1]).hexdigest(),'url':'mid:'+e['mid'],'issued':e['date'],'subj':e['subj'],'text':t}
        out.append(d)
    return out

def parse_chats():
    out=[]
    for f in sorted(glob.glob(EX+'/wechat/*.txt')):
        base=os.path.basename(f); sup=CHATSUP[base.split('_')[0]]
        lines=open(f,encoding='utf-8').read().split('\n')
        msgs=[];cur=None
        for l in lines:
            m=re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$',l)
            if m and (cur is None or cur['blank']):
                cur={'ts':m.group(1),'sender':m.group(2),'lines':[l],'blank':False,'text':[]}; msgs.append(cur)
            elif cur is not None:
                if l.strip()=='' : cur['blank']=True
                elif not cur['blank']: cur['lines'].append(l); cur['text'].append(l)
        for i,m in enumerate(msgs,1):
            dt=datetime.strptime(m['ts'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            out.append({'kind':'chat','sup':sup,'file':base,'n':i,'hash':hashlib.sha256('\n'.join(m['lines']).encode()).hexdigest(),
                'url':f'wechat/{base}#{i}','issued':iso(dt),'dt':dt,'sender':m['sender'],'maya':m['sender'].startswith('Maya'),'text':'\n'.join(m['text'])})
    return out
