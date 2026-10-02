import re,glob,os,json,hashlib,mailbox,datetime as dt
from zoneinfo import ZoneInfo
S=os.path.dirname(os.path.abspath(__file__))
EXP='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-c-xa8fl84a/ingest/work/exports'
NY=ZoneInfo('America/New_York'); CN=ZoneInfo('Asia/Shanghai'); LA=ZoneInfo('America/Los_Angeles')
PORTS={'Yantian':'CNYTN','Ningbo':'CNNGB','Xiamen':'CNXMN','Nansha':'CNNSA','New York/Newark':'USNYC','Los Angeles':'USLAX'}
PORTTZ={'CNYTN':CN,'CNNGB':CN,'CNXMN':CN,'CNNSA':CN,'USNYC':NY,'USLAX':LA}
MON={m:i+1 for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}
def num(s): return s.replace(',','')
def sha(b): return hashlib.sha256(b).hexdigest()
def port_instant(date,locode):
    return dt.datetime(date.year,date.month,date.day,tzinfo=PORTTZ[locode])
def iso(d): return d.isoformat()
SUP={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
EMAILDOM={'nbbw':'NBBW','szht':'SZHT','ywlx':'YWLX','dgrf':'DGRF','fsmj':'FSMJ','xmyd':'XMYD','nbqs':'NBQS','hzty':'HZTY'}
CUR={'USD':'USD','RMB':'CNY'}

def parse_pdfs():
    idx=dict((os.path.basename(f)[:-4],h) for f,h in json.load(open(S+'/pdfidx.json')))
    out=[]
    for n,h in idx.items():
        t=open(f'{S}/txt/{n}.txt').read()
        d=dict(name=n,hash=h,url=f'supplier_docs/{n}.pdf',text=t)
        L=t.split('\n')
        if n.startswith('LCI-'):
            d['kind']='qc'
            d['report']=re.search(r'Report No\.: (\S+)',t).group(1)
            d['date']=dt.date.fromisoformat(re.search(r'Inspection date: (\S+)',t).group(1))
            d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
            d['sample']=int(re.search(r'sample size (\d+)',t).group(1))
            d['result']=re.search(r'Overall result: (\w+)',t).group(1)
            d['inspector']='Linkcheck Inspection Services'
            assert L[0]=='LINKCHECK INSPECTION SERVICES'
            d['supplier_legal']=re.search(r'Supplier: (.*)',t).group(1)
        elif n.startswith('CI-PL'):
            d['kind']='ci'
            m=re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (\S+)',t)
            d['invoice']=m.group(1); d['date']=dt.date.fromisoformat(m.group(2)); d['po']=m.group(3)
            m=re.search(r'From (\w+) to (\w+) by sea, (MV [^\n]*?)\s+Container: (\S+)\s+B/L: (\S+)',t)
            d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
            d['rows']=[]
            for m in re.finditer(r'^(\S+)\n?',t,re.M): pass
            # invoice rows: HS-code lines preceded by item no line
            for m in re.finditer(r'^(\S+) .*\n(?:.*[\u4e00-\u9fff].*\n)?(\d{4}\.\d{2}\.\d{4}) ([\d,]+) (USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d.,]+)$',t,re.M):
                d['rows'].append(dict(item=m.group(1),hs=m.group(2),qty=int(num(m.group(3))),cur=m.group(4)))
            pl=t.split('PACKING LIST')[1]
            d['pl']={}
            for m in re.finditer(r'^(\d+-\d+) (\S+) (\d+) (\d+) ([\d,]+) ',pl,re.M):
                d['pl'][m.group(2)]=d['pl'].get(m.group(2),0)+int(m.group(3))
            m=re.search(r'Container: (\S+)\s+Seal',pl); d['pl_container']=m.group(1)
            d['supcode']=EMAILDOM[re.search(r'sales@(\w+)\.example',t).group(1)]
        else:
            d['kind']='pi'
            d['supcode']=EMAILDOM[re.search(r'sales@(\w+)\.example',t).group(1)]
            d['name_cn']=L[0]; 
            d['address']=L[2]
            d['pi_no']=re.search(r'PI No\.: (\S+)',t).group(1)
            d['date']=dt.date.fromisoformat(re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1))
            d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
            d['rows']=[]
            for m in re.finditer(r'^(\S+) .*\n(?:.*[\u4e00-\u9fff].*\n)?([\d,]+) ([\d,]+) (USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d.,]+)$',t,re.M):
                d['rows'].append(dict(item=m.group(1),qty=int(num(m.group(2))),ctns=int(num(m.group(3))),cur=m.group(4),price=num(m.group(5)),amt=num(m.group(6))))
            d['currency']=CUR[d['rows'][0]['cur']]
            d['incoterm'],d['port_name']=re.search(r'Price term: (\w+) (\w+)',t).groups()
            d['payment']=re.search(r'Payment: (.*)',t).group(1)
            d['etd']=dt.datetime.strptime(re.search(r'Delivery: about (\w+ \d+, \d{4})',t).group(1),'%b %d, %Y').date()
            d['legal']=re.search(r'Beneficiary: (.*)',t).group(1)
            d['total']=num(re.search(r'^TOTAL (?:USD|RMB) ([\d.,]+)',t,re.M).group(1))
        out.append(d)
    return out

def parse_chats():
    out=[]
    for f in sorted(glob.glob(EXP+'/wechat/*.txt')):
        raw=open(f,encoding='utf-8',newline='').read()
        assert '\r' not in raw
        blocks=raw.split('\n\n')
        base=os.path.basename(f); code=base.split('_')[0]
        n=0
        for b in blocks[1:]:
            b=b.strip('\n')
            if not b: continue
            n+=1
            hl,_,txt=b.partition('\n')
            m=re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$',hl)
            ts=dt.datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            out.append(dict(kind='chat',file=base,code=code,n=n,ts=ts,sender=m.group(2),text=txt,
                            hash=sha(b.encode()),url=f'wechat/{base}#{n}',raw=b))
    return out

def parse_mail():
    raw=open(EXP+'/email/ops_inbox.mbox','rb').read()
    parts=re.split(rb'(?m)^(?=From \S+ \w{3} \w{3} +\d+ )',raw)
    parts=[p for p in parts if p.strip()]
    out=[]
    for p in parts:
        b=p[:-1] if p.endswith(b'\n\n') else p
        msg=mailbox.mboxMessage(__import__('email').message_from_bytes(p.split(b'\n',1)[1]))
        body=msg.get_payload()
        mid=msg['Message-ID'].strip('<>')
        ts=__import__('email.utils').utils.parsedate_to_datetime(msg['Date'])
        out.append(dict(kind='mail',hash=sha(b),url='mid:'+mid,ts=ts,subject=msg['Subject'],body=body,
                        sender=msg['From']))
    return out
if __name__=='__main__':
    p=parse_pdfs(); c=parse_chats(); m=parse_mail()
    print(len(p),len(c),len(m))
    import collections
    print(collections.Counter(d['kind'] for d in p))
    for d in p:
        if d['kind']=='pi':
            assert abs(sum(float(r['amt']) for r in d['rows'])-float(d['total']))<0.01,(d['name'],)
        if d['kind']=='ci':
            assert d['container']==d['pl_container'] and d['rows'] and sum(r['qty'] for r in d['rows'])>0,d['name']
            assert set(r['item'] for r in d['rows'])==set(d['pl']),d['name']
    print('ok')
