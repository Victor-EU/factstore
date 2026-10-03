import re,glob,os,hashlib,sys,json,collections
from datetime import datetime,date,timedelta,timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo
SC=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SC)
EXP='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-l-_p6upixp/ingest/work/exports/'
import factstore
from mb import msgs
from chat import load as load_chat, W as CHATDIR
COMMIT = len(sys.argv)>1 and sys.argv[1]=='commit'
CN=ZoneInfo('Asia/Shanghai'); NY=ZoneInfo('America/New_York'); LA=ZoneInfo('America/Los_Angeles')
PORTTZ={'CN':CN,'USNYC':NY,'USLAX':LA}
def tzof(loc): return CN if loc.startswith('CN') else PORTTZ[loc]
LOC={'Yantian':'CNYTN','Ningbo':'CNNGB','Nansha':'CNNSA','Xiamen':'CNXMN','New York/Newark':'USNYC','Los Angeles':'USLAX'}
SUP={'HT':'SZHT','LX':'YWLX','MJ':'FSMJ','MT':'NBBW','QS':'NBQS','RF':'DGRF','TY':'HZTY','YD':'XMYD'}
CHATSUP={'DGRF':'DGRF','FSMJ':'FSMJ','HZTY':'HZTY','NBBW':'NBBW','NBQS':'NBQS','SZHT':'SZHT','XMYD':'XMYD','YWLX':'YWLX'}
RANK_PO={s:i for i,s in enumerate(['draft','sent','confirmed','in_production','ready','shipped','received'])}
RANK_SH={'booked':1,'departed':2,'arrived':3,'delivered':4}
def iso(dt): return dt.isoformat()
def at(d,loc): return iso(datetime(d.year,d.month,d.day,tzinfo=tzof(loc)))
def pdate(s): return datetime.strptime(s,'%d %b %Y').date()
def num(s): return s.replace(',','')

# known SKUs / hs
items={}  # code -> hs
for r in factstore.query('select c.v, h.v from "factory/item_code" c join "sku/hs_code" h using(e)').rows: items[r[0]]=r[1]

docs=[]  # dict(kind,hash,url,issued,data)
# ---------- PDFs
import pypdf
for f in sorted(glob.glob(EXP+'supplier_docs/*.pdf')):
    b=open(f,'rb').read(); h=hashlib.sha256(b).hexdigest()
    t="\n".join(p.extract_text() or '' for p in pypdf.PdfReader(f).pages)
    n=os.path.basename(f)
    url='supplier_docs/'+n
    if n.startswith('CI-PL_'):
        m=re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})',t)
        docs.append(dict(kind='cipl',hash=h,url=url,issued=datetime.fromisoformat(m.group(2)).replace(tzinfo=CN),text=t,n=n))
    elif n.startswith('LCI-'):
        d=re.search(r'Inspection date: (\S+)',t).group(1)
        docs.append(dict(kind='qc',hash=h,url=url,issued=datetime.fromisoformat(d).replace(tzinfo=CN),text=t,n=n))
    else:
        d=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
        docs.append(dict(kind='pi',hash=h,url=url,issued=datetime.fromisoformat(d).replace(tzinfo=CN),text=t,n=n))
# ---------- chats
for f in sorted(os.listdir(CHATDIR)):
    for m in load_chat(f):
        dt=datetime.strptime(m['ts'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
        docs.append(dict(kind='chat',hash=m['hash'],url=m['url'],issued=dt,m=m,sup=CHATSUP[f[:4]]))
# ---------- emails
for m in msgs:
    s=m['subj']
    k=('booking_rolled' if 'ROLLED' in s else 'booking' if s.startswith('Booking') else 'prealert' if s.startswith('Shipping Advice') else 'eta' if s.startswith('ETA update') else 'arrival' if s.startswith('Arrival') else 'customs' if s.startswith('Entry Summary') else 'receipt' if s.startswith('Receipt complete') else None)
    assert k,s
    docs.append(dict(kind=k,hash=m['hash'],url='mid:'+m['mid'],issued=m['dt'],m=m))
docs.sort(key=lambda d:d['issued'])
print(len(docs),'documents',collections.Counter(d['kind'] for d in docs),file=sys.stderr)

# ---------- state
pos={}; pi2po={}; shipments=[]; sup_of_po={}
txs=[]; report=collections.defaultdict(list); lowconf=[]
def emit(doc,conf,facts):
    head=[{"e":["document/hash",doc['hash']],"a":"document/url","v":doc['url']},
          {"e":["document/hash",doc['hash']],"a":"document/issued_at","v":iso(doc['issued'])},
          {"e":"tmp:tx","a":"core/evidence","v":["document/hash",doc['hash']]},
          {"e":"tmp:tx","a":"core/confidence","v":str(conf)}]
    txs.append(dict(doc=doc,conf=conf,facts=head+facts))
    if conf!=1: lowconf.append((doc['url'],conf,[f for f in facts][:3]))
def F(e,a,v): return {"e":e,"a":a,"v":v}
def PO(n): return ["po/number",n]
def getpo(n):
    return pos.setdefault(n,dict(num=n,status=None,etd=None,sup=None,pi=None,lines={},cur=None,rate=None,terms=None,total=D(0),placed=None))
def po_status(po,new,facts):
    P=getpo(po)
    if P['status'] is None or RANK_PO[new]>RANK_PO[P['status']]:
        P['status']=new; facts.append(F(PO(po),'po/status',new)); return True
    return False
def normpo(tok):
    m=re.search(r'(20\d\d)-(\d{4})',tok)
    if m: return f'PO-{m.group(1)}-{m.group(2)}'
    m=re.search(r'(\d+)',tok); n=int(m.group(1))
    return f'PO-2025-{n:04d}' if n>=100 else f'PO-2026-{n:04d}'
def sref(s):
    return ["shipment/hbl",s['hbl']] if s['hbl'] else ["shipment/booking_no",s['booking']]
def find_ship(hbl=None,booking=None,vessel=None,poset=None,create=True):
    for s in shipments:
        if hbl and s['hbl']==hbl: return s
    for s in shipments:
        if booking and s['booking']==booking: return s
    if vessel and poset:
        for s in shipments:
            if s['vessel']==vessel and (not hbl or not s['hbl']) and (s['pos']&poset): return s
    if not create: return None
    s=dict(hbl=None,booking=None,vessel=vessel,container=None,origin=None,dest=None,status=None,pos=set(),bpos=set(),lines={},etd=None,eta=None,departed=False,delivered=False,mode=None,atd_date=None)
    shipments.append(s); return s
def ship_by_container(c,dt):
    c_=[s for s in shipments if s['container']==c and s['etd'] and datetime.fromisoformat(s['etd'])<=dt+timedelta(days=1)] or [s for s in shipments if s['container']==c]
    return max(c_,key=lambda s:s['etd'] or '') if c_ else None
def ship_status(s,new,facts):
    if s['status'] is None or RANK_SH[new]>RANK_SH[s['status']]:
        s['status']=new; facts.append(F(sref(s),'shipment/status',new))
def setattr_(s,key,attr,val,facts):
    if val is not None and s[key]!=val:
        s[key]=val; facts.append(F(sref(s),attr,val))

def line_rows(t):  # CI rows
    return re.findall(r'(?m)^(\S+) [^\n]*\n[^\n]*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) (?:USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d.,]+)$',t)

def do_pi(d):
    t=d['text']; L=t.split('\n')
    pi=re.search(r'PI No\.: (\S+)',t).group(1); po=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    code=re.search(r'sales@(\w+)\.example',t).group(1).upper()
    rows=re.findall(r'(?m)^(\S+) [^\n]*\n[^\n]*\n([\d,]+) ([\d,]+) (USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d.,]+)$',t)
    cur='CNY' if rows[0][3]=='RMB' else rows[0][3]
    term=re.search(r'Price term: (\w+) (\w+)',t); pay=re.search(r'Payment: (.*)',t).group(1).strip()
    etd=datetime.strptime(re.search(r'Delivery: about (\w+ \d+, \d{4})',t).group(1),'%b %d, %Y').date()
    legal=re.search(r'Beneficiary: (.*)',t).group(1).strip()
    rate=re.search(r'at ([\d.]+) RMB/USD',t)
    S=["supplier/code",code]
    f=[F(PO(po),'po/pi_number',pi),F(PO(po),'po/supplier',S),F(PO(po),'po/etd',etd.isoformat()),F(PO(po),'core/currency',cur),
       F(S,'supplier/name',legal),F(S,'supplier/name_cn',L[0].strip()),F(S,'supplier/address',L[2].strip()),F(S,'supplier/incoterm',term.group(1)),
       F(S,'supplier/payment_terms',pay),F(S,'supplier/currency',cur),F(S,'supplier/port',LOC[term.group(2)])]
    P=getpo(po); P.update(pi=pi,sup=code,etd=etd.isoformat(),cur=cur,terms=pay,rate=D(rate.group(1)) if rate else None)
    pi2po[pi]=po
    tot=D(0)
    for i,(item,qty,ctns,c,price,amt) in enumerate(rows,1):
        key=f'{po}/{i}'; ic=f'{code}:{item}'
        if ic not in items: report['unresolved'].append(f'{d["url"]}: item code {ic} has no SKU'); continue
        f+= [F(["po_line/key",key],'core/part_of',PO(po)),F(["po_line/key",key],'po_line/sku',["factory/item_code",ic]),
             F(["po_line/key",key],'po_line/quantity',num(qty)),F(["po_line/key",key],'po_line/unit_price',num(price))]
        P['lines'][key]=dict(sku=ic,qty=D(num(qty)),price=D(num(price))); tot+=D(num(amt))
    P['total']=tot
    po_status(po,'confirmed',f)
    emit(d,1,f)

def po_line_for(po,item):
    P=pos.get(po)
    if not P: return None
    for k,l in P['lines'].items():
        if l['sku'].split(':',1)[1]==item: return k
def check_shipped(po,s,facts_out,dep_date):
    P=getpo(po)
    if not P['lines'] or (P['status'] and RANK_PO[P['status']]>=RANK_PO['shipped']): return
    carry=[x for x in shipments if po in x['pos']]
    cond1=all(sum((x['lines'].get(k,(D(0),0))[0] for x in shipments),D(0))>=l['qty'] for k,l in P['lines'].items())
    cond2=bool(carry) and all(x['departed'] for x in carry)
    if cond1 or cond2:
        P['status']='shipped'; facts_out.append(F(PO(po),'po/status','shipped'))
        if dep_date: facts_out.append(F(PO(po),'po/etd',dep_date)); P['etd']=dep_date
        if not cond1: report['notes'].append(f'{po} marked shipped though shipment lines do not cover ordered quantities (all bookings departed)')
def ship_lines(d,s,rows,facts,hbl):
    # rows: (po,item,qty,ctns)
    for po,item,qty,ctns in rows:
        k=po_line_for(po,item)
        if not k: report['unresolved'].append(f'{d["url"]}: no PO line for {po} {item}'); continue
        key=f'{hbl}/{k}'
        old=s['lines'].get(k)
        if old and (old[0]!=D(num(qty)) or (ctns is not None and old[1]!=int(ctns))): report['notes'].append(f'{d["url"]}: line {key} differs from earlier document: {old} vs {qty}/{ctns}')
        s['lines'][k]=(D(num(qty)), int(ctns) if ctns is not None else (old[1] if old else None)); s['pos'].add(po)
        f=[F(["shipment_line/key",key],'core/part_of',sref(s)),F(["shipment_line/key",key],'shipment_line/po_line',["po_line/key",k]),F(["shipment_line/key",key],'shipment_line/quantity',num(qty))]
        if ctns is not None: f.append(F(["shipment_line/key",key],'shipment_line/cartons',str(int(ctns))))
        facts+=f

def do_cipl(d):
    t=d['text']
    m=re.search(r'Order: (PO-\d{4}-\d{4})\s*\nFrom (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t) or re.search(r'Order: (PO-\d{4}-\d{4})\s+From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t)
    po,org,dst,vessel,cont,hbl=m.groups()
    code=pos[po]['sup'] if po in pos and pos[po]['sup'] else None
    if not code: report['unresolved'].append(f'{d["url"]}: PO {po} has no PI read before this invoice'); return
    s=find_ship(hbl=hbl,vessel=vessel,poset={po})
    f=[]
    pending=None
    if not s['hbl']:
        if s['booking']: f.append(F(sref(s),'shipment/hbl',hbl)); pending=hbl
        else: s['hbl']=hbl
    if cont!='LCL': setattr_(s,'container','shipment/container_no',cont,f)
    setattr_(s,'vessel','shipment/vessel',vessel,f); setattr_(s,'origin','shipment/origin',org,f); setattr_(s,'dest','shipment/destination',dst,f)
    s['seen_doc']=True; s['departed']=True
    rows=line_rows(t)
    pl={}
    for a,b in [(x[0],x[1]) for x in re.findall(r'(?m)^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) ',t)]: pl[a]=b
    sl=[]
    for item,hs,qty,price,amt in rows:
        ic=f'{code}:{item}'
        if ic in items and items[ic]!=hs: report['hs'].append(f'{d["url"]}: {ic} invoice HS {hs} differs from SKU HS {items[ic]}')
        sl.append((po,item,qty,pl.get(item)))
    ship_lines(d,s,sl,f,hbl)
    emit(d,1,f)
    if pending: s['hbl']=pending
    if s['atd_date']:
        g=[]; check_shipped(po,s,g,s['atd_date'])
        if g: emit(d,1,g)

def do_qc(d):
    t=d['text']
    no=re.search(r'Report No\.: (\S+)',t).group(1); po=re.search(r'PO No\.: (PO-\d{4}-\d{4})',t).group(1)
    on=re.search(r'Inspection date: (\S+)',t).group(1); res=re.search(r'Overall result: (\w+)',t).group(1)
    size=re.search(r'sample size (\d+)',t).group(1); insp=t.split('\n')[0].title().replace('Linkcheck','LinkCheck')
    R=["qc/report_no",no]
    f=[F(R,'qc/po',PO(po)),F(R,'qc/inspected_on',on),F(R,'qc/result',res),F(R,'qc/inspector',insp),F(R,'qc/sample_size',size)]
    getpo(po)
    if res=='PASS': po_status(po,'ready',f)
    emit(d,1,f)

# ---------- chat / email
def ack_pending():pass
chat_state=collections.defaultdict(lambda:dict(lastpi=None,dep=None))
containers_chat=[]
def cn_date(m,d_):  # message instant -> next occurrence of month/day on/after, in China
    base=d_['issued'].astimezone(CN).date()
    dt=date(base.year,m[0],m[1])
    if dt<base: dt=date(base.year+1,m[0],m[1])
    return dt
def do_chat(d):
    m=d['m']; t=m['text']; st=chat_state[d['sup']]; sup=d['sup']; maya=m['sender'].startswith('Maya')
    S=["supplier/code",sup]
    if maya:
        r=re.search(r'(?:new PO |^Hi \w+! PO |here\'s )(PO-\d{4}-\d{4})',t)
        if r and 'attached' in t or r and 'PO PO-' in t or r and "here's" in t:
            po=r.group(1)
            if re.search(r'new PO|! PO |here\'s',t):
                getpo(po)['placed']=1
                emit(d,1,[F(PO(po),'po/placed_on',d['issued'].date().isoformat()),F(PO(po),'po/supplier',S)]); report['placed'].append(po); return
        r=re.search(r'[Dd]eposit.*?USD ([\d,]+\.\d\d)',t)
        if r:
            nm=re.search(r'(PO-\d{4}-\d{4})',t); st['dep']=(D(num(r.group(1))),nm.group(1) if nm else None,d); return
        if t.startswith('Balance'): st['dep']=None
        return
    # supplier messages
    if m['text'].startswith('[文件]'):
        r=re.search(r'\[文件\] (.+)\.pdf',t); 
        if r and r.group(1) in pi2po: st['lastpi']=r.group(1)
        elif r: st['lastpi']=r.group(1)
        return
    r=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',t) or re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',t)
    if r:
        po=r.group(1); dt=cn_date((int(r.group(2)),int(r.group(3))),d)
        getpo(po); emit(d,0.9,[F(PO(po),'po/etd',dt.isoformat())]); getpo(po)['etd']=dt.isoformat(); report['slips'].append((po,dt.isoformat(),d['url'])); return
    r=re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',t)
    if r:
        pi=r.group(1)
        if pi not in pi2po: report['unresolved'].append(f'{d["url"]}: PI {pi} unknown'); return
        po=pi2po[pi]; dt=cn_date((int(r.group(2)),int(r.group(3))),d)
        emit(d,0.8,[F(PO(po),'po/etd',dt.isoformat())]); getpo(po)['etd']=dt.isoformat(); report['slips'].append((po,dt.isoformat(),d['url'])); return
    r=re.match(r'(?:交期(\d+)月(\d+)号左右|ETD (\d+)/(\d+))',t)
    if r:
        mo=int(r.group(1) or r.group(3)); dd=int(r.group(2) or r.group(4)); pi=st['lastpi']
        po=pi2po.get(pi)
        if not po: report['unresolved'].append(f'{d["url"]}: ETD message without known PI ({pi})'); return
        dt=cn_date((mo,dd),d)
        if pos[po]['etd']==dt.isoformat(): report['restated'].append(d['url']); return
        emit(d,0.8,[F(PO(po),'po/etd',dt.isoformat())]); pos[po]['etd']=dt.isoformat(); return
    r=re.search(r'(?:container loaded: |Container )([A-Z]{4}\d{7})',t)
    if r: containers_chat.append((r.group(1),d,sup)); return
    if re.match(r'(Received, thank you|收到，谢谢|定金收到了)',t) and st['dep']:
        amt,named,ddoc=st['dep']; st['dep']=None
        po=named
        if not po:
            best=None
            for n,P in pos.items():
                if P['sup']!=sup or not P['terms'] or not P['total']: continue
                pc=re.search(r'(\d+)% deposit',P['terms'])
                if not pc: continue
                exp=P['total']*D(pc.group(1))/100
                if P['cur']=='CNY': exp=exp/P['rate']
                diff=abs(exp-amt)/amt
                if diff<D('0.01') and (best is None or diff<best[0]) and P['status'] and RANK_PO[P['status']]<RANK_PO['in_production']: best=(diff,n)
            po=best[1] if best else None
        if not po: report['unresolved'].append(f'{d["url"]}: deposit ack, PO not identified (USD {amt})'); return
        f=[]
        if po_status(po,'in_production',f): emit(d,0.9,f)
        return
    # others
    for pat,k in [(r'上调|降价|涨价|\+\d+%|-\d%','price'),(r'放假','holiday'),(r'Samples sent|DHL','sample')]:
        if re.search(pat,t): report[k].append(d['url']); return

def parse_booking(d,rolled=False):
    m=d['m']; b=m['body']; s_=m['subj']
    so=re.search(r'SO (\S+)',s_).group(1)
    if rolled:
        r=re.search(r'New ETD (\d\d \w{3} \d{4}), ETA (\d\d \w{3} \d{4})',b)
        s=find_ship(booking=so,create=False)
        if not s: report['unresolved'].append(f'{d["url"]}: rolled booking {so} not found'); return
        f=[]; 
        setattr_(s,'etd','shipment/etd',at(pdate(r.group(1)),s['origin'] or 'CN'),f); setattr_(s,'eta','shipment/eta',at(pdate(r.group(2)),s['dest']),f)
        emit(d,1,f); return
    eq=re.search(r'Equipment: (\S+)',b).group(1); mode='LCL' if eq=='LCL' else re.sub(r'^1x','',eq)
    vessel=re.search(r'Vessel/Voyage: (.+)',b).group(1).strip()
    pol,pod=re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)',b).groups()
    etd=pdate(re.search(r'ETD: (\d\d \w{3} \d{4})',b).group(1)); eta=pdate(re.search(r'ETA: (\d\d \w{3} \d{4})',b).group(1))
    poset={normpo(x) for x in re.search(r'POs: (.*)',b).group(1).split(',')}
    s=find_ship(booking=so,vessel=vessel,poset=poset)
    s['booking']=s['booking'] or so; s['bpos']|=poset; s['pos']|=poset
    f=[F(["shipment/booking_no",so],'shipment/mode',mode)]
    s['mode']=mode
    setattr_(s,'vessel','shipment/vessel',vessel,f); setattr_(s,'origin','shipment/origin',pol,f); setattr_(s,'dest','shipment/destination',pod,f)
    setattr_(s,'etd','shipment/etd',at(etd,pol),f); setattr_(s,'eta','shipment/eta',at(eta,pod),f)
    ship_status(s,'booked',f); emit(d,1,f)

def do_prealert(d):
    b=d['m']['body']
    hbl=re.search(r'HBL: (\S+)',b).group(1); cont=re.search(r'Container/Seal: (\S+)',b).group(1)
    vessel=re.search(r'Vessel/Voyage: (.+)',b).group(1).strip()
    po_,atd=re.search(r'ATD (.+?): (\d\d \w{3} \d{4})',b).groups(); dp,eta=re.search(r'ETA (.+?): (\d\d \w{3} \d{4})',b).groups()
    rows=[(a,i,q,c) for a,i,c,q in re.findall(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',b)]
    poset={r[0] for r in rows}
    s=find_ship(hbl=hbl,vessel=vessel,poset=poset)
    f=[]; pending=None
    if not s['hbl']:
        if s['booking']: f.append(F(sref(s),'shipment/hbl',hbl)); pending=hbl
        else: s['hbl']=hbl
    if cont!='LCL': setattr_(s,'container','shipment/container_no',cont,f)
    elif not s['mode']: pass
    setattr_(s,'vessel','shipment/vessel',vessel,f)
    org=LOC[po_]; dst=LOC[dp]
    setattr_(s,'origin','shipment/origin',org,f); setattr_(s,'dest','shipment/destination',dst,f)
    s['atd_date']=pdate(atd).isoformat()
    setattr_(s,'etd','shipment/etd',at(pdate(atd),org),f); setattr_(s,'eta','shipment/eta',at(pdate(eta),dst),f)
    s['departed']=True; ship_status(s,'departed',f)
    ship_lines(d,s,rows,f,hbl); emit(d,1,f)
    if pending: s['hbl']=pending
    g=[]
    for po in sorted(poset): check_shipped(po,s,g,s['atd_date'])
    if g: emit(d,1,g)

def do_eta(d):
    b=d['m']['body']; r=re.search(r'revised ETA (\d\d \w{3} \d{4}) for HBL (\S+)',b)
    s=find_ship(hbl=r.group(2),create=False)
    if not s: report['unresolved'].append(f'{d["url"]}: ETA update for unknown HBL'); return
    f=[]; setattr_(s,'eta','shipment/eta',at(pdate(r.group(1)),s['dest']),f); emit(d,1,f)
def do_arrival(d):
    b=d['m']['body']; r=re.search(r'Shipment HBL (\S+) \((\S+)\) on (.+?) is arriving (.+?) on (\d\d \w{3} \d{4})',b)
    s=find_ship(hbl=r.group(1),create=False)
    if not s: report['unresolved'].append(f'{d["url"]}: arrival for unknown HBL'); return
    f=[]; ship_status(s,'arrived',f); s['eta']=None
    setattr_(s,'eta','shipment/eta',at(pdate(r.group(5)),LOC[r.group(4)]),f); emit(d,1,f)
def do_receipt(d):
    b=d['m']['body']; ident=re.search(r'Receiving complete for (\S+) under',b).group(1)
    s=find_ship(hbl=ident,create=False) if ident.startswith('PBLHB') else ship_by_container(ident,d['issued'])
    if not s: report['unresolved'].append(f'{d["url"]}: receipt for unknown {ident}'); return
    f=[]; ship_status(s,'delivered',f); s['delivered']=True
    f.append(F(sref(s),'shipment/delivered_at',iso(d['issued'])))
    for po in sorted(s['pos']):
        carry=[x for x in shipments if po in x['pos']]
        if all(x['delivered'] for x in carry): po_status(po,'received',f)
    if 'No discrepancies' not in b: report['discrepancies'].append((d['url'],ident,re.findall(r'(?m)^\s+(\S+ \(.*?\): expected \d+, received \d+, damaged \d+)',b)))
    emit(d,1,f)
def do_customs(d):
    b=d['m']['body']; no=re.search(r'Entry (\S+) filed for (\S+?)\.',b); entry,ident=no.groups()
    s=find_ship(hbl=ident,create=False) if ident.startswith('PBLHB') else ship_by_container(ident,d['issued'])
    if not s: report['unresolved'].append(f'{d["url"]}: customs entry {entry}: shipment {ident} not found'); return
    g=lambda k: D(num(re.search(k+r': USD ([\d,.]+)',b).group(1)))
    duty=g(r'Duty \(HTS\)')+g('Section 301')+g('Additional duties'); fees=g('MPF')+g('HMF')
    ev=g('Entered value')
    if duty+fees!=g('Total duties and fees'): report['notes'].append(f'{d["url"]}: duty+fees {duty+fees} != stated total')
    E=["customs/entry_no",entry]
    filed=d['m']['dt'].date().isoformat()
    emit(d,1,[F(E,'customs/shipment',sref(s)),F(E,'customs/filed_on',filed),F(E,'customs/entered_value',str(ev)),F(E,'customs/duty',str(duty)),F(E,'customs/fees',str(fees)),F(E,'core/currency','USD')])

H=dict(pi=do_pi,cipl=do_cipl,qc=do_qc,chat=do_chat,booking=parse_booking,booking_rolled=lambda d:parse_booking(d,True),prealert=do_prealert,eta=do_eta,arrival=do_arrival,receipt=do_receipt,customs=do_customs)
for d in docs: H[d['kind']](d)
# chat containers post-check
for c,d,sup in containers_chat:
    s=[x for x in shipments if x['container']==c]
    if not s: report['unresolved'].append(f'{d["url"]}: chat container {c} matches no shipment')
    else: report['chat_container_ok'].append(d['url'])
print('transactions',len(txs),file=sys.stderr)
json.dump(dict(txs=[dict(url=t['doc']['url'],conf=t['conf'],n=len(t['facts'])) for t in txs]),open(SC+'/txs.json','w'))
with open(SC+'/report.json','w') as fh: json.dump({k:v for k,v in report.items()},fh,default=str,indent=1)
if COMMIT:
    errs=0
    for i,t in enumerate(txs):
        try: r=factstore.transact(t['facts'])
        except Exception as e: errs+=1; print('ERR',i,t['doc']['url'],e); continue
    print('committed',len(txs),'errors',errs)
else:
    bad=0
    for i,t in enumerate(txs):
        try: r=factstore.transact(t['facts'],dry_run=True)
        except Exception as e: bad+=1; print('ERR',i,t['doc']['url'],str(e)[:300])
        else:
            if r.errors or r.unknown_attributes: bad+=1; print('ERR',i,t['doc']['url'],r.errors,r.unknown_attributes)
    print('dry run done, errors',bad)
if os.environ.get('DBG'):
    print(collections.Counter(P['status'] for P in pos.values()))
    for n,P in sorted(pos.items()): print(n,P['status'],P['etd'],P['pi'],P['sup'],P['placed'])
    for s in shipments: print(s['booking'],s['hbl'],s['container'],s['mode'],s['status'],s['etd'],s['eta'],sorted(s['pos']),len(s['lines']),s['delivered'])
    print(report['slips']); print(report['unresolved'])
if os.environ.get('SHOW'):
    for t in txs:
        if re.search(os.environ['SHOW'],t['doc']['url']):
            print(t['doc']['url'],t['conf']); [print('  ',f['e'],f['a'],f['v']) for f in t['facts']]
