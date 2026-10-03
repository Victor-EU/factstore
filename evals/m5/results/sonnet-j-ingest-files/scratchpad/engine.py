import re,os,sys,json,email,collections
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
import factstore
from parse import *
NY=ZoneInfo("America/New_York"); LA=ZoneInfo("America/Los_Angeles"); SH=ZoneInfo("Asia/Shanghai")
MODE = sys.argv[1] if len(sys.argv)>1 else 'real'
DRY = MODE=='dry'
RANK={s:i for i,s in enumerate("draft sent confirmed in_production ready shipped received".split())}
MON={m:i+1 for i,m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
REPORT=collections.defaultdict(list)
def note(k,m): REPORT[k].append(m)

# ---- store snapshot
def q(sql): return factstore.query(sql).rows if hasattr(factstore.query(sql),'rows') else None
_r=factstore.query('select s.v, c.e from "supplier/code" s join "supplier/code" c using(e)')
SUP={}
for row in factstore.query('select v,e from "supplier/code"').rows: SUP[row[0]]=row[1]
ITEMS={r[0] for r in factstore.query('select v from "factory/item_code"').rows}
SKU_HS={r[0]:r[1] for r in factstore.query('select i.v,h.v from "factory/item_code" i join "sku/hs_code" h using(e)').rows}
EXIST_PO={r[0] for r in factstore.query('select v from "po/number"').rows}
print(len(SUP),len(ITEMS),len(SKU_HS),len(EXIST_PO))

# ---- state
class PO: pass
POS={}      # number -> dict
def po(n):
    if n not in POS: POS[n]=dict(n=n,status=None,lines={},sup=None,pi=None,etd=None,placed=False,new=n not in EXIST_PO)
    return POS[n]
PI2PO={}
SHIPS=[]    # shipment records
CREATED=collections.Counter(); SEEN=set()
def created(kind,key):
    if (kind,key) not in SEEN: SEEN.add((kind,key)); CREATED[kind]+=1
CUR=[None]
def ship_ref(s):
    if s['hbl'] and not (s.get('hbl_ev') is CUR[0] and s['booking']): return ["shipment/hbl",s['hbl']]
    return ["shipment/booking_no",s['booking']]
def tz_for(loc): return SH if loc.startswith('CN') else (LA if loc=='USLAX' else NY)
def at(d,loc):  # date -> instant midnight local port time
    dt=datetime(d.year,d.month,d.day,tzinfo=tz_for(loc)); return dt.isoformat()
def pdate(s): 
    d,m,y=s.split(); return date(int(y),MON[m],int(d))
def norm_po(s,ctx_year=None):
    """returns (canonical, loose?)"""
    m=re.fullmatch(r'PO-(\d{4})-(\d{4})',s.strip())
    if m: return s.strip(),False
    digits=re.findall(r'\d+',s)
    if len(digits)==2 and len(digits[0])==4: return f"PO-{digits[0]}-{digits[1].zfill(4)}",False
    n=digits[-1].zfill(4)
    c=[k for k in POS if k.endswith('-'+n)]
    if len(c)==1: return c[0],True
    return None,True

# ---- event emission
class Ev:
    def __init__(s,issued,kind,hash_,url): s.issued=issued; s.kind=kind; s.hash=hash_; s.url=url; s.tx=collections.defaultdict(list)
    def add(s,e,a,v,conf="1"): s.tx[conf].append({"e":e,"a":a,"v":v})
def flush(ev):
    order=sorted(ev.tx.items(),key=lambda kv:-float(kv[0]))
    n=0
    for conf,facts in order:
        if not facts: continue
        head=[{"e":["document/hash",ev.hash],"a":"document/url","v":ev.url},
              {"e":["document/hash",ev.hash],"a":"document/issued_at","v":ev.issued},
              {"e":"tmp:tx","a":"core/evidence","v":["document/hash",ev.hash]},
              {"e":"tmp:tx","a":"core/confidence","v":conf}]
        allf=head+facts
        if DRY: LOG.append((ev.url,conf,facts)); continue
        r=factstore.transact(allf,dry_run=(MODE=='validate')); n+=1
        TXN.append((ev.url,conf,len(allf)))
LOG=[]
TXN=[]

# ---- load PDFs
EVENTS=[]
PIS={};CIS=[];QCS=[]
for f in sorted(os.listdir(EX+"/supplier_docs")):
    if f.startswith('CI-PL'): d=parse_ci(f); d['issued']=at(date.fromisoformat(d['date']),'CN'); CIS.append(d); EVENTS.append(('ci',d))
    elif f.startswith('LCI'): d=parse_qc(f); d['issued']=at(date.fromisoformat(d['date']),'CN'); QCS.append(d); EVENTS.append(('qc',d))
    else: d=parse_pi(f); d['issued']=at(date.fromisoformat(d['date']),'CN'); PIS[d['po']]=d; EVENTS.append(('pi',d))
# pre-register PO lines so chat/email handling can look up
for d in PIS.values():
    p=po(d['po']); p['sup']=d['sup']; p['pi']=d['pi']; PI2PO[d['pi']]=d['po']
# ---- load chats
CHATFILES={'DGRF':'DGRF_Jason.txt','FSMJ':'FSMJ_Grace.txt','HZTY':'HZTY_Coco.txt','NBBW':'NBBW_Lily.txt','NBQS':'NBQS_Sunny.txt','SZHT':'SZHT_Kevin.txt','XMYD':'XMYD_Eric.txt','YWLX':'YWLX_Amy.txt'}
for code,fn in CHATFILES.items():
    txt=open(f"{EX}/wechat/{fn}",encoding='utf-8').read()
    body=txt.split("\n\n",1)[1]
    msgs=[b for b in body.split("\n\n") if b.strip()]
    for i,b in enumerate(msgs,1):
        lines=b.rstrip("\n").split("\n")
        m=re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$',lines[0]); assert m,(fn,i,lines[0])
        dt=datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
        d=dict(code=code,n=i,sender=m.group(2),text="\n".join(lines[1:]),dt=dt,issued=dt.isoformat(),hash=sha("\n".join(lines).encode()),url=f"wechat/{fn}#{i}")
        EVENTS.append(('chat',d))
# ---- load email
raw=open(EX+"/email/ops_inbox.mbox","rb").read()
for p in re.split(rb'(?m)^(?=From )',raw):
    if not p.strip(): continue
    if p.endswith(b"\n\n"): p=p[:-1]
    m=email.message_from_bytes(p); dt=parsedate_to_datetime(m['Date'])
    d=dict(hash=sha(p),url="mid:"+m['Message-ID'].strip('<>'),dt=dt,issued=dt.isoformat(),subj=m['Subject'],body=m.get_payload(decode=True).decode())
    EVENTS.append(('mail',d))
RANKK={'pi':0,'chat':1,'qc':2,'ci':3,'mail':4}
EVENTS.sort(key=lambda e:(datetime.fromisoformat(e[1]['issued']),RANKK[e[0]]))
print(len(EVENTS),collections.Counter(k for k,_ in EVENTS))

def set_status(ev,pn,new,conf="1"):
    p=po(pn); 
    if p['status'] is None or RANK[new]>RANK[p['status']]:
        p['status']=new; ev.add(["po/number",pn],"po/status",new,conf)
def po_line_key(pn,item):
    p=po(pn)
    for k,v in p['lines'].items():
        if v['item']==item: return k
    return None
def shipments_for_po(pn):
    out=[s for s in SHIPS if pn in s['pos'] or any(l.startswith(pn+'/') or l.split('/',1)[1].startswith(pn+'/') for l in s['lines'])]
    return out
def ship_pos(s):
    r=set(s['pos'])
    for k in s['lines']: r.add(k.split('/',1)[1].rsplit('/',1)[0])
    return r
def find_ship(hbl=None,booking=None,cont=None):
    for s in SHIPS:
        if hbl and s['hbl']==hbl: return s
        if booking and s['booking']==booking: return s
        if cont and cont!='LCL' and s['cont']==cont and (not hbl or not s['hbl']): return s
    return None
def match_booking(vessel,pos_):
    """unmatched booking on same vessel/voyage carrying overlapping POs"""
    c=[s for s in SHIPS if s['booking'] and not s['hbl'] and s['vessel']==vessel and (s['pos'] & pos_)]
    if len(c)==1: return c[0],"vv+po"
    c=[s for s in SHIPS if s['booking'] and not s['hbl'] and s['vessel']==vessel and not s['pos']]
    return None,None
def new_ship(**k):
    s=dict(booking=None,hbl=None,cont=None,vessel=None,pos=set(),lines={},dep=False,atd=None,delivered=False,orig=None,dest=None,loose=False,status=None,mode=None); s.update(k); SHIPS.append(s); return s

def update_shipped(ev,s,conf_hbl="1"):
    for pn in ship_pos(s):
        p=po(pn)
        if p['status'] and RANK[p['status']]>=RANK['shipped']:
            done=True
        else:
            # lines add up?
            tot={}
            for sh in shipments_for_po(pn):
                for k,l in sh['lines'].items():
                    lk=k.split('/',1)[1]
                    if lk.startswith(pn+'/'): tot[lk]=tot.get(lk,0)+l
            ok1= p['lines'] and all(tot.get(k,0)>=float(v['qty']) for k,v in p['lines'].items())
            sh=shipments_for_po(pn)
            bk=[x for x in sh if x['booking']]
            ok2= bool(bk) and all(x['dep'] for x in bk) and all(x['dep'] for x in sh)
            done=bool(ok1 or ok2)
            if done: set_status(ev,pn,'shipped')
        if done and s['atd']:
            d=max(x['atd'] for x in shipments_for_po(pn) if x['atd'])
            if p['etd']!=d:
                p['etd']=d; ev.add(["po/number",pn],"po/etd",d.isoformat())

def handle_pi(d):
    ev=Ev(d['issued'],'pi',d['hash'],d['url']); P=["po/number",d['po']]; p=po(d['po']); created('purchase order',d['po']) if p['new'] else None
    ev.add(P,"po/pi_number",d['pi']); ev.add(P,"po/supplier",SUP[d['sup']]); ev.add(P,"po/etd",d['etd']); p['etd']=date.fromisoformat(d['etd'])
    ev.add(P,"core/currency",d['cur'])
    set_status(ev,d['po'],'confirmed')
    for i,r in enumerate(d['rows'],1):
        key=f"{d['po']}/{i}"; code=f"{d['sup']}:{r['item']}"
        if code not in ITEMS: note('unresolved',f"{d['url']}: item code {code} has no SKU"); continue
        L=["po_line/key",key]; created('PO line',key)
        ev.add(L,"core/part_of",P); ev.add(L,"po_line/sku",["factory/item_code",code]); ev.add(L,"po_line/quantity",r['qty']); ev.add(L,"po_line/unit_price",r['price'])
        p['lines'][key]=dict(item=r['item'],qty=r['qty'],sku=code)
    S=["supplier/code",d['sup']]
    ev.add(S,"supplier/name_cn",d['name_cn']); ev.add(S,"supplier/name",d['bene']); ev.add(S,"supplier/address",d['addr'])
    ev.add(S,"supplier/incoterm",d['incoterm']); ev.add(S,"supplier/payment_terms",d['pay']); ev.add(S,"supplier/currency",d['cur']); ev.add(S,"supplier/port",d['port'])
    p['total']=sum(float(r['qty'])*float(r['price']) for r in d['rows']); p['pay']=d['pay']
    flush(ev)

def handle_qc(d):
    ev=Ev(d['issued'],'qc',d['hash'],d['url']); Q=["qc/report_no",d['no']]; created('inspection',d['no'])
    ev.add(Q,"qc/po",["po/number",d['po']]); ev.add(Q,"qc/inspected_on",d['date']); ev.add(Q,"qc/result",d['result'])
    ev.add(Q,"qc/inspector",d['agency'].title()); ev.add(Q,"qc/sample_size",d['n'])
    if d['result']=='PASS': set_status(ev,d['po'],'ready')
    flush(ev)

def attach_lines(ev,s,rows,hbl):
    for pn,item,ctns,qty in rows:
        lk=po_line_key(pn,item)
        if not lk: note('unresolved',f"{ev.url}: {pn} item {item} has no PO line"); continue
        key=f"{hbl}/{lk}"; SL=["shipment_line/key",key]; created('shipment line',key)
        ev.add(SL,"core/part_of",ship_ref(s)); ev.add(SL,"shipment_line/po_line",["po_line/key",lk])
        ev.add(SL,"shipment_line/quantity",qty); ev.add(SL,"shipment_line/cartons",ctns)
        s['lines'][key]=float(qty)

def handle_ci(d):
    ev=Ev(d['issued'],'ci',d['hash'],d['url']); CUR[0]=ev
    s=find_ship(hbl=d['hbl'])
    how=None
    if not s:
        s,how=match_booking(d['vessel'],{d['po']})
        if not s:
            c=[x for x in SHIPS if not x['hbl'] and x['cont']==d['cont'] and d['cont']!='LCL']
            s=c[0] if c else None; how='container' if s else None
    if s and not s['hbl']:
        ev.add(ship_ref(s),"shipment/hbl",d['hbl'], "1" if not s.get('loose') else "0.9"); s['hbl']=d['hbl']; s['hbl_ev']=ev
    elif not s:
        s=new_ship(hbl=d['hbl'],vessel=d['vessel'],orig=d['orig'],dest=d['dest']); created('shipment',d['hbl']); note('unresolved',f"{d['url']}: no booking found for HBL {d['hbl']} ({d['vessel']}); shipment created from the invoice alone")
    S=ship_ref(s)
    if d['cont']!='LCL':
        if s['cont'] and s['cont']!=d['cont']: note('conflict',f"{d['url']}: container {d['cont']} vs earlier {s['cont']} on {d['hbl']}")
        ev.add(S,"shipment/container_no",d['cont']); s['cont']=d['cont']
    if s['vessel'] and s['vessel']!=d['vessel']: note('conflict',f"{d['url']}: vessel {d['vessel']} vs booking {s['vessel']} on {d['hbl']}")
    ev.add(S,"shipment/vessel",d['vessel']); ev.add(S,"shipment/origin",d['orig']); ev.add(S,"shipment/destination",d['dest'])
    s['vessel']=d['vessel']; s['orig']=s['orig'] or d['orig']; s['dest']=s['dest'] or d['dest']
    rows=[(d['po'],r['item'],r['ctns'],r['qty']) for r in d['rows']]
    attach_lines(ev,s,rows,d['hbl']); s['pos'].add(d['po']); s['dep']=True
    for r in d['rows']:
        code=f"{d['sup']}:{r['item']}"
        if code in SKU_HS:
            if SKU_HS[code]!=r['hs']: note('hs',f"{code}: store has {SKU_HS[code]}, {d['url']} prints {r['hs']}")
        elif code in ITEMS: ev.add(["factory/item_code",code],"sku/hs_code",r['hs'])
    update_shipped(ev,s)
    flush(ev)

# ---- chat
def china_date_after(msgdt,mo,dy):
    base=msgdt.astimezone(SH).date()
    for y in (base.year,base.year+1):
        try: c=date(y,mo,dy)
        except ValueError: continue
        if c>=base: return c
PEND={c:[] for c in CHATFILES}   # pending payment messages per chat
LASTACK={}
LOADQ={c:[] for c in CHATFILES}
def handle_chat(d):
    if d['sender'].startswith('Maya'): handle_maya(d)
    else: handle_sup(d)
def handle_maya(d):
    t=d['text']; code=d['code']; ev=Ev(d['issued'],'chat',d['hash'],d['url'])
    m=re.search(r'(PO-\d{4}-\d{4})',t)
    if m and (re.match(r"Hi \w+! PO ",t) or re.match(r"Hi \w+, new PO",t) or re.match(r"\w+, here's PO",t)):
        pn=m.group(1); p=po(pn); P=["po/number",pn]
        if p['new']: created('purchase order',pn)
        ev.add(P,"po/placed_on",d['dt'].date().isoformat()); ev.add(P,"po/supplier",SUP[code])
        if p['sup'] and p['sup']!=code: note('conflict',f"{d['url']}: {pn} sent to {code} but PI says {p['sup']}")
        p['sup']=code; set_status(ev,pn,'sent'); p['placed']=True
    elif re.search(r'deposit',t,re.I):
        m2=re.search(r'deposit for (PO-\d{4}-\d{4})',t)
        amt=re.search(r'(?:USD|CNY) ([\d,]+\.\d\d)',t); amt=float(amt.group(1).replace(',','')) if amt else None
        PEND[code].append(dict(kind='deposit',po=m2.group(1) if m2 else None,amt=amt,dt=d['dt']))
    elif re.match(r'Balance (?:paid )?for (PO-\d{4}-\d{4})',t) or 'balance' in t.lower() and 'sent' in t.lower() or t.startswith('B/L copy'):
        m2=re.search(r'(PO-\d{4}-\d{4})',t)
        PEND[code].append(dict(kind='balance',po=m2.group(1) if m2 else None,amt=None,dt=d['dt']))
        if m2 and 'paid' in t: LOADQ[code].append(m2.group(1))
    flush(ev)
def resolve_deposit(code,item):
    if item['po']: return item['po'],"0.9"
    c=[]
    for pn,p in POS.items():
        if p['sup']!=code or 'total' not in p: continue
        mo=re.search(r'(\d+)% deposit',p['pay'])
        pct=int(mo.group(1))/100 if mo else None
        if pct and item['amt'] and abs(p['total']*pct-item['amt'])<0.02*1+0.5: c.append(pn)
        elif pct is None and item['amt'] is not None and abs(item['amt']-p['total'])<0.5: c.append(pn)
    if len(c)==1: return c[0],"0.8"
    note('unresolved',f"deposit {item['amt']} on {code} at {item['dt']:%Y-%m-%d} matches {c or 'no PO'}")
    return None,None
def handle_sup(d):
    t=d['text']; code=d['code']; ev=Ev(d['issued'],'chat',d['hash'],d['url'])
    # ETD slip
    m=re.search(r'(PO-\d{4}-\d{4}).*?(?:ETD for \1 will be|交期要推迟到)\s*(\d+)[/月](\d+)',t) or None
    pn=None;mo=dy=None
    m1=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',t)
    m2=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',t)
    m3=re.search(r'Hi, (\S+) 大货要晚一点.*?预计(\d+)/(\d+)出货',t)
    conf="0.9"
    if m1: pn,mo,dy=m1.group(1),int(m1.group(2)),int(m1.group(3))
    elif m2: pn,mo,dy=m2.group(1),int(m2.group(2)),int(m2.group(3))
    elif m3:
        pn=PI2PO.get(m3.group(1)); mo,dy=int(m3.group(2)),int(m3.group(3))
        if not pn: note('unresolved',f"{d['url']}: PI {m3.group(1)} unknown")
    if pn and mo:
        nd=china_date_after(d['dt'],mo,dy); p=po(pn)
        if p['sup'] and p['sup']!=code: note('conflict',f"{d['url']}: {pn} slip in {code} chat but PO is {p['sup']}'s")
        if p['status'] and RANK[p['status']]>=RANK['shipped']: note('unresolved',f"{d['url']}: ETD slip for {pn} after it shipped; not applied")
        else:
            ev.add(["po/number",pn],"po/etd",nd.isoformat(),conf); p['etd']=nd
    # post-PI date confirmations: compare only
    m4=re.match(r'(?:交期(\d+)月(\d+)号左右)?(?:，)?(?:ETD(?: around)? (\d+)/(\d+))?$',t)
    if m4 and (m4.group(1) or m4.group(3)):
        mo=int(m4.group(1) or m4.group(3)); dy=int(m4.group(2) or m4.group(4))
        # which PO: the supplier's latest PI
        cands=[x for x in POS.values() if x['sup']==code and x['etd'] and x['pi'] and x['status'] in('confirmed',)]
        cands.sort(key=lambda x:x['n'])
        nd=china_date_after(d['dt'],mo,dy)
        if cands and cands[-1]['etd']==nd: pass
        else: note('unresolved',f"{d['url']}: ETD note {mo}/{dy} differs from latest PI date ({cands[-1]['etd'] if cands else None}); not applied")
    # acknowledgements
    if re.match(r'(定金收到了|Received, thank you|收到，谢谢)',t):
        pend=PEND[code]
        pend[:]=[it for it in pend if d['dt']-it['dt']<=timedelta(days=7)]
        item=None
        for want in ('deposit','balance'):
            if t.startswith('定金') and want=='balance': break
            for it in pend:
                if it['kind']==want: item=it; break
            if item: break
        if item:
            pend.remove(item)
            if item['kind']=='deposit':
                pn,conf=resolve_deposit(code,item)
                if pn:
                    LASTACK[code]=pn
                    set_status(ev,pn,'in_production',conf)
    elif t=='大货生产中':
        pn=LASTACK.get(code)
        if pn: set_status(ev,pn,'in_production',"0.8")
    # container loaded
    m5=re.search(r'(?:Container (\w{4}\d{7}) loaded today|已装柜 container loaded: (\w{4}\d{7}) seal)',t)
    if m5:
        cont=m5.group(1) or m5.group(2); q=LOADQ[code]
        cand=[pn for pn in q]
        pn=None
        for x in reversed(cand):
            if any((not s['cont'] or s['cont']==cont) and s['mode']!='LCL' for s in shipments_for_po(x)): pn=x;break
        if pn:
            q.remove(pn)
            sh=[s for s in shipments_for_po(pn) if (not s['cont'] or s['cont']==cont) and s['mode']!='LCL']
            s=sh[0]
            if s['cont']!=cont:
                ev.add(ship_ref(s),"shipment/container_no",cont,"0.8"); s['cont']=cont
        else: note('unresolved',f"{d['url']}: container {cont} loaded but no booking/PO to attach it to")
    flush(ev)

# ---- email
def parse_equip(s):
    if s.startswith('LCL'): return 'LCL'
    return re.search(r'x(\w+)$',s).group(1)
def handle_mail(d):
    ev=Ev(d['issued'],'mail',d['hash'],d['url']); CUR[0]=ev; b=d['body']; subj=d['subj']
    if subj.startswith('Booking Confirmation'):
        g=lambda k: re.search(k+r': (.+)',b).group(1).strip()
        so=g('SO'); vessel=g('Vessel/Voyage'); mode=parse_equip(g('Equipment'))
        m=re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)',b); o,dst=m.groups()
        etd=pdate(g('ETD')); eta=pdate(g('ETA'))
        pos_=set(); loose=False
        for tok in g('POs').split(','):
            c,l=norm_po(tok)
            if c is None: note('unresolved',f"{d['url']}: PO reference '{tok.strip()}' unresolved"); continue
            pos_.add(c); loose|=l
        s=find_ship(booking=so)
        if not s:
            # maybe an invoice-first shipment on the same vessel with these POs
            c=[x for x in SHIPS if not x['booking'] and x['vessel']==vessel and (ship_pos(x)&pos_)]
            s=c[0] if c else None
            if s: s['booking']=so; ev.add(["shipment/hbl",s['hbl']],"shipment/booking_no",so)
        if not s: s=new_ship(booking=so); created('shipment',so)
        s['vessel']=vessel; s['pos']|=pos_; s['orig']=o; s['dest']=dst; s['loose']=s['loose'] or loose; s['mode']=mode
        S=ship_ref(s)
        ev.add(S,"shipment/mode",mode); ev.add(S,"shipment/vessel",vessel); ev.add(S,"shipment/origin",o); ev.add(S,"shipment/destination",dst)
        ev.add(S,"shipment/etd",at(etd,o)); ev.add(S,"shipment/eta",at(eta,dst)); ev.add(S,"shipment/status","booked"); s['status']='booked'
        for pn in pos_:
            if pn in POS: pass
            else: note('unresolved',f"{d['url']}: booking carries {pn}, which has no PO in the documents")
    elif subj.startswith('RE: Booking Confirmation'):
        so=re.search(r'SO (\S+)',subj).group(1); s=find_ship(booking=so)
        m=re.search(r'New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})',b)
        if not s: note('unresolved',f"{d['url']}: rolled booking {so} unknown"); return
        ev.add(ship_ref(s),"shipment/etd",at(pdate(m.group(1)),s['orig'])); ev.add(ship_ref(s),"shipment/eta",at(pdate(m.group(2)),s['dest']))
    elif subj.startswith('Shipping Advice'):
        g=lambda k: re.search(k+r': (.+)',b).group(1).strip()
        hbl=g('HBL'); cs=g('Container/Seal'); cont=cs.split(' / ')[0]; vessel=g('Vessel/Voyage')
        m=re.search(r'ATD (\w+): (\d+ \w+ \d{4})',b); atd=pdate(m.group(2))
        eta=pdate(re.search(r'ETA [\w/ ]+: (\d+ \w+ \d{4})',b).group(1))
        rows=[(m.group(1),m.group(2),m.group(3),m.group(4).replace(',','')) for m in re.finditer(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+([\d,]+) pcs',b,re.M)]
        pos_={r[0] for r in rows}
        s=find_ship(hbl=hbl); hconf="1"
        if not s:
            s,how=match_booking(vessel,pos_)
            if s and s['loose']: hconf="0.9"
            if not s:
                c=[x for x in SHIPS if not x['hbl'] and x['cont']==cont and cont!='LCL']
                s=c[0] if c else None
        if s and not s['hbl']:
            ev.add(ship_ref(s),"shipment/hbl",hbl,hconf); s['hbl']=hbl; s['hbl_ev']=ev
        if not s:
            s=new_ship(hbl=hbl,vessel=vessel); created('shipment',hbl); note('unresolved',f"{d['url']}: no booking for HBL {hbl} ({vessel}); shipment created from the pre-alert alone")
        S=ship_ref(s)
        if cont!='LCL':
            if s['cont'] and s['cont']!=cont: note('conflict',f"{d['url']}: container {cont} vs earlier {s['cont']} on {hbl}")
            ev.add(S,"shipment/container_no",cont); s['cont']=cont
        orig_=s['orig'] or 'CN'; dest_=s['dest'] or 'USNYC'
        ev.add(S,"shipment/etd",at(atd,orig_)); ev.add(S,"shipment/eta",at(eta,dest_)); ev.add(S,"shipment/status","departed"); s['status']='departed'
        s['atd']=atd; s['dep']=True; s['pos']|=pos_
        attach_lines(ev,s,rows,hbl)
        update_shipped(ev,s)
    elif subj.startswith('ETA update'):
        hbl=re.search(r'HBL (\S+)',subj).group(1); s=find_ship(hbl=hbl)
        eta=pdate(re.search(r'revised ETA (\d+ \w+ \d{4})',b).group(1))
        if not s: note('unresolved',f"{d['url']}: ETA update for unknown HBL {hbl}"); return
        ev.add(ship_ref(s),"shipment/eta",at(eta,s['dest']))
    elif subj.startswith('Arrival Notice'):
        m=re.search(r'HBL (\S+) \(.*?\) on (.+?) is arriving (.+?) on (\d+ \w+ \d{4})',b); hbl=m.group(1)
        s=find_ship(hbl=hbl)
        if not s: note('unresolved',f"{d['url']}: arrival for unknown HBL {hbl}"); return
        ev.add(ship_ref(s),"shipment/status","arrived"); ev.add(ship_ref(s),"shipment/eta",at(pdate(m.group(4)),s['dest'])); s['status']='arrived'
    elif subj.startswith('Receipt complete'):
        ref=re.search(r'Receiving complete for (\S+) under (\S+)',b).group(1)
        s=find_ship(hbl=ref) or find_ship(cont=ref)
        if not s: note('unresolved',f"{d['url']}: receipt for unknown {ref}"); return
        ev.add(ship_ref(s),"shipment/status","delivered"); ev.add(ship_ref(s),"shipment/delivered_at",d['issued']); s['delivered']=True
        for l in re.findall(r'^\s+(.+?): expected (\d+), received (\d+), damaged (\d+)',b,re.M):
            if l[1]!=l[2] or l[3]!='0': note('receipt',f"{ref} {d['issued'][:10]}: {l[0]} expected {l[1]} received {l[2]} damaged {l[3]}")
        for pn in ship_pos(s):
            if all(x['delivered'] for x in shipments_for_po(pn)): set_status(ev,pn,'received')
    elif subj.startswith('Entry Summary'):
        no=re.search(r'Entry (\S+) filed for (\S+)\.',b); en,ref=no.groups()
        s=find_ship(hbl=ref) or find_ship(cont=ref)
        if not s: note('unresolved',f"{d['url']}: entry {en} for unknown {ref}"); return
        v=lambda k: float(re.search(k+r': USD ([\d,\.]+)',b).group(1).replace(',',''))
        duty=v(r'Duty \(HTS\)')+v('Section 301')+v('Additional duties'); fees=v('MPF')+v('HMF')
        assert abs(duty+fees-v('Total duties and fees'))<0.02,(en,duty,fees)
        E=["customs/entry_no",en]; created('customs entry',en)
        ev.add(E,"customs/shipment",ship_ref(s)); ev.add(E,"customs/filed_on",d['dt'].date().isoformat())
        ev.add(E,"customs/entered_value",f"{v('Entered value'):.2f}"); ev.add(E,"customs/duty",f"{duty:.2f}"); ev.add(E,"customs/fees",f"{fees:.2f}"); ev.add(E,"core/currency","USD")
    else: note('unresolved',f"{d['url']}: unrecognised email '{subj}'"); return
    flush(ev)

H={'pi':handle_pi,'qc':handle_qc,'ci':handle_ci,'chat':handle_chat,'mail':handle_mail}
for k,d in EVENTS:
    try: H[k](d)
    except Exception as e:
        import traceback; traceback.print_exc(); print("FAILED",k,d.get('url')); raise
print("shipments",len(SHIPS))
json.dump({k:v for k,v in REPORT.items()},open('report.json','w'),indent=1)
print('tx',len(TXN))
json.dump(dict(created=CREATED),open('created.json','w'))
if DRY: json.dump([(u,c,f) for u,c,f in LOG],open('dry.json','w'),default=str)
for k,v in REPORT.items(): print(k,len(v))
print(CREATED)
print(collections.Counter(p['status'] for p in POS.values()))
