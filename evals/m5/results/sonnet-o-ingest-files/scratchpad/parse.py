import re,glob,os,json,hashlib,mailbox
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
EXP='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-o-fbektazt/ingest/work/exports'
import pypdf
CN=ZoneInfo('Asia/Shanghai'); NY=ZoneInfo('America/New_York'); LA=ZoneInfo('America/Los_Angeles')
DOM={'nbbw':'NBBW','szht':'SZHT','ywlx':'YWLX','dgrf':'DGRF','hzty':'HZTY','fsmj':'FSMJ','nbqs':'NBQS','xmyd':'XMYD'}
PORT={'Yantian':'CNYTN','Ningbo':'CNNGB','Xiamen':'CNXMN','Nansha':'CNNSA','Shanghai':'CNSHA','Shenzhen':'CNSZX'}
def num(s): return s.replace(',','')
def iso(dt): return dt.isoformat()
docs=[]  # each: kind,hash,url,issued,data
def pdfs():
    for f in sorted(glob.glob(EXP+'/supplier_docs/*.pdf')):
        b=open(f,'rb').read(); h=hashlib.sha256(b).hexdigest()
        t="\n".join(p.extract_text() or '' for p in pypdf.PdfReader(f).pages)
        url='supplier_docs/'+os.path.basename(f)
        L=[l for l in t.split('\n')]
        if 'PROFORMA INVOICE' in t[:400]: yield pi(t,L,h,url)
        elif 'COMMERCIAL INVOICE' in t[:400]: yield ci(t,L,h,url)
        elif 'Pre-Shipment Inspection' in t[:200]: yield qc(t,L,h,url)
        else: raise Exception('unknown '+url)
def cn_midnight(d): return datetime.strptime(d,'%Y-%m-%d').replace(tzinfo=CN)
def pi(t,L,h,url):
    d={}
    d['pi_no']=re.search(r'PI No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    d['name_cn']=L[0].strip(); d['name_caps']=L[1].strip(); d['address']=L[2].strip()
    d['code']=DOM[re.search(r'@(\w+)\.example',t).group(1)]
    d['name']=re.search(r'Beneficiary: (.+)',t).group(1).strip()
    pt=re.search(r'Price term: (.+)',t).group(1).strip(); d['incoterm']=pt
    d['port']=PORT[pt.split()[-1]]
    d['payment']=re.search(r'Payment: (.+)',t).group(1).strip()
    m=re.search(r'Delivery: about (\w+ \d+, \d{4})',t); d['etd']=datetime.strptime(m.group(1),'%b %d, %Y').date().isoformat()
    rows=[]
    for i,l in enumerate(L):
        m=re.match(r'^([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$',l)
        if m:
            item=L[i-2].split()[0]
            rows.append(dict(item=item,qty=num(m.group(1)),ctns=m.group(2),cur=m.group(3),price=num(m.group(4)),amt=num(m.group(6))))
    d['rows']=rows; d['cur']='CNY' if rows[0]['cur']=='RMB' else rows[0]['cur']
    tot=re.search(r'TOTAL (USD|RMB) ([\d,.]+)',t); 
    assert abs(sum(float(r['amt']) for r in rows)-float(num(tot.group(2))))<0.01,url
    assert all(abs(float(r['qty'])*float(r['price'])-float(r['amt']))<0.01 for r in rows),url
    return dict(kind='pi',hash=h,url=url,issued=iso(cn_midnight(d['date'])),d=d)
def ci(t,L,h,url):
    d={}
    d['inv']=re.search(r'Invoice No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Invoice No\.: \S+\s+Date: (\d{4}-\d\d-\d\d)',t).group(1)
    pos=set(re.findall(r'Order: (PO-\d{4}-\d{4})',t)); assert len(pos)==1,url; d['po']=pos.pop()
    m=re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t)
    d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
    d['code']=DOM[re.search(r'@(\w+)\.example',t).group(1)]
    rows={}
    for i,l in enumerate(L):
        m=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$',l)
        if m: rows[L[i-2].split()[0]]=dict(item=L[i-2].split()[0],hs=m.group(1),qty=num(m.group(2)))
    pk=t.split('PACKING LIST')[1]
    for l in pk.split('\n'):
        m=re.match(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) ',l)
        if m: rows[m.group(1)]['ctns']=m.group(2); assert num(m.group(4))==rows[m.group(1)]['qty'],url
    assert all('ctns' in r for r in rows.values()),url
    d['rows']=list(rows.values())
    return dict(kind='ci',hash=h,url=url,issued=iso(cn_midnight(d['date'])),d=d)
def qc(t,L,h,url):
    d={}
    d['inspector']=L[0].strip().title()
    d['no']=re.search(r'Report No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
    d['po']=re.search(r'PO No\.: (PO-\d{4}-\d{4})',t).group(1)
    d['sample']=re.search(r'sample size (\d+)',t).group(1)
    d['result']=re.search(r'Overall result: (\w+)',t).group(1)
    return dict(kind='qc',hash=h,url=url,issued=iso(cn_midnight(d['date'])),d=d)
def chats():
    for f in sorted(glob.glob(EXP+'/wechat/*.txt')):
        base=os.path.basename(f)
        txt=open(f,encoding='utf-8').read()
        lines=txt.split('\n')
        i=0; msgs=[]
        cur=None
        for l in lines:
            if re.match(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ',l):
                cur=[l]; msgs.append(cur)
            elif l=='' : cur=None
            elif cur is not None: cur.append(l)
        for n,m in enumerate(msgs,1):
            raw='\n'.join(m)
            ts=datetime.strptime(m[0][:19],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            sender=m[0][20:]
            yield dict(kind='chat',hash=hashlib.sha256(raw.encode()).hexdigest(),url=f'wechat/{base}#{n}',issued=iso(ts),
                       d=dict(file=base,sender=sender,text='\n'.join(m[1:]),ts=iso(ts),n=n,code=base[:4]))
def mails():
    mb=mailbox.mbox(EXP+'/email/ops_inbox.mbox')
    for k in mb.keys():
        raw=mb.get_bytes(k,from_=True); msg=mb[k]
        body=msg.get_payload(decode=True).decode()
        from email.utils import parsedate_to_datetime
        dt=parsedate_to_datetime(msg['Date'])
        mid=msg['Message-ID'].strip('<>')
        yield dict(kind='mail',hash=hashlib.sha256(raw).hexdigest(),url='mid:'+mid,issued=iso(dt),
                   d=dict(subject=msg['Subject'],frm=msg['From'],body=body,date=iso(dt)))
if __name__=='__main__':
    allv=list(pdfs())+list(chats())+list(mails())
    json.dump(allv,open('docs.json','w'),ensure_ascii=False,indent=0)
    import collections
    print(collections.Counter(d['kind'] for d in allv))
    print(len({d['hash'] for d in allv}),len(allv))
