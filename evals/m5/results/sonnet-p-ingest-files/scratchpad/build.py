import warnings; warnings.filterwarnings('ignore')
from chat import *
import emails as E
from decimal import Decimal
from datetime import date as Date
LA=ZoneInfo('America/Los_Angeles')
PREF={'RF':'DGRF','MJ':'FSMJ','TY':'HZTY','MT':'NBBW','QS':'NBQS','HT':'SZHT','YD':'XMYD','LX':'YWLX'}
PORT={'Yantian':'CNYTN','Ningbo':'CNNGB','Nansha':'CNNSA','Xiamen':'CNXMN'}
SPORT={'New York/Newark':'USNYC','Los Angeles':'USLAX'}
sup_of={po:PREF[d['pi'][:2]] for po,d in pis.items()}
LOG=[]   # report notes
def note(k,m): LOG.append((k,m))
def inst(ds,loc):
    y,m,d=map(int,ds.split('-'))
    tz={'USNYC':NY,'USLAX':LA}.get(loc, timezone(timedelta(hours=8)))
    return datetime(y,m,d,tzinfo=tz).isoformat()
CN8=timezone(timedelta(hours=8))
def pdf_issued(ds): return datetime.strptime(ds,'%Y-%m-%d').replace(tzinfo=CN8).isoformat()
# ---------- PO / line maps
known_pos=set(pis)
for c in chats:
    for m in re.finditer(r'PO-\d{4}-\d{4}',c['body']): known_pos.add(m.group(0))
line_idx={}   # (po,item)->idx
for po,d in pis.items():
    for i,r in enumerate(d['rows'],1): line_idx[(po,r['item'])]=i
ordered={ (po,i):Decimal(r['qty']) for po,d in pis.items() for i,r in enumerate(d['rows'],1)}
def pl_key(po,item): return f"{po}/{line_idx[(po,item)]}"
def resolve_po(s):
    m=re.search(r'(\d{4})-(\d{4})',s)
    if m: return f"PO-{m.group(1)}-{m.group(2)}", True
    n=int(re.search(r'(\d+)',s).group(1)); c=[p for p in known_pos if int(p[-4:])==n]
    assert len(c)==1,(s,c); return c[0], False
# ---------- shipments: prepass linking
class Ship:
    def __init__(s): s.hbl=None; s.so=None; s.asserted=set(); s.pos=set(); s.link_conf='1'; s.dest=None; s.origin=None; s.container=None; s.vessel=None; s.status=0; s.departed=False; s.delivered=False
ships=[]; by_hbl={}; by_so={}
bookings=[r for r in E.ev if r['kind']=='booking']
for r in bookings:
    S=Ship(); S.so=r['so']; ships.append(S); by_so[r['so']]=S
    rp=[resolve_po(x) for x in re.search(r'POs: (.+)',r['e']['body']).group(1).split(',')]
    r['pos']=[p for p,_ in rp]; S.pos=set(r['pos']); S.link_conf='1' if all(ok for _,ok in rp) else '0.9'
    r['S']=S
for r in E.ev:
    if r['kind']=='prealert':
        h=r['hbl']
        S=by_hbl.get(h)
        if not S:
            pos={l[0] for l in r['lines']}
            cand=[b for b in bookings if b['vessel']==r['vessel'] and set(b['pos'])<=pos and b['S'].hbl is None]
            if len(cand)==1: S=cand[0]['S']
            else:
                if cand: note('ambiguous',f'{h} {cand}')
                S=Ship(); ships.append(S)
            S.hbl=h; by_hbl[h]=S
            S.link_conf=S.link_conf if S.so else '1'
        r['S']=S
        S.pos|={l[0] for l in r['lines']}
for d in docs:
    if d['kind']=='CI':
        S=by_hbl.get(d['hbl'])
        if not S: note('CI without pre-alert',d['url']); S=Ship(); S.hbl=d['hbl']; ships.append(S); by_hbl[d['hbl']]=S
        d['S']=S
by_cont={}
for r in E.ev:
    if r['kind']=='prealert' and r['container']!='LCL': by_cont[r['container']]=r['S']
for d in docs:
    if d['kind']=='CI' and d['container']!='LCL': by_cont.setdefault(d['container'],d['S'])
po_ships={}  # po->set(S) of shipments carrying it (booking or prealert)
for S in ships:
    for p in S.pos: po_ships.setdefault(p,set()).add(S)
for b in bookings:
    if b['S'].hbl is None: note('booking without pre-alert/CI',f"{b['so']} {b['pos']}")
# ---------- tx machinery
TX=[]
cur={}   # (ekey,attr)->value
def doc_facts(doc):
    return [{"e":["document/hash",doc['hash']],"a":"document/url","v":doc['url']},
            {"e":["document/hash",doc['hash']],"a":"document/issued_at","v":doc['issued']}]
class T:
    def __init__(t,doc,conf,label): t.doc=doc; t.conf=conf; t.label=label; t.f=[]
    def add(t,ekey,e,a,v,vkey=None):
        k=(ekey,a); vv=vkey if vkey is not None else (json.dumps(v) if not isinstance(v,str) else v)
        if cur.get(k)==vv: return
        cur[k]=vv; t.f.append({"e":e,"a":a,"v":v})
    def done(t):
        if not t.f: return
        facts=doc_facts(t.doc)+[{"e":"tmp:tx","a":"core/evidence","v":["document/hash",t.doc['hash']]},{"e":"tmp:tx","a":"core/confidence","v":t.conf}]+t.f
        TX.append(dict(issued=t.doc['issued'],label=t.label,conf=t.conf,facts=facts,doc=t.doc['url']))
PO=lambda p:["po/number",p]
RANK={'draft':0,'sent':1,'confirmed':2,'in_production':3,'ready':4,'shipped':5,'received':6}
def set_status(t,po,st):
    c=cur.get((po,'po/status'))
    if c is None or RANK[c]<RANK[st]: t.add(po,PO(po),'po/status',st); return True
    return False
def sref(S,gives):
    """lookup for shipment S using an identifier already asserted"""
    if 'hbl' in S.asserted: return ["shipment/hbl",S.hbl]
    if 'so' in S.asserted: return ["shipment/booking_no",S.so]
    return None
def skey(S): return 'ship:'+(S.hbl or S.so)
def open_ship(doc,S,gives,label,facts_conf='1'):
    """returns (lookup) after possibly writing a link tx; gives = set of ids the doc states"""
    ref=sref(S,gives)
    newids=[i for i in gives if i not in S.asserted]
    if ref is None:
        # create under first id given
        first='hbl' if 'hbl' in gives else 'so'
        ref=["shipment/hbl",S.hbl] if first=='hbl' else ["shipment/booking_no",S.so]
        S.asserted.add(first); newids=[i for i in gives if i!=first and i not in S.asserted]
        t=T(doc,'1',label+' ids'); 
        t.add(skey(S)+first,ref,'shipment/hbl' if first=='hbl' else 'shipment/booking_no',S.hbl if first=='hbl' else S.so); t.done()
    if newids:
        t=T(doc,S.link_conf,label+' link')
        for i in newids:
            t.add(skey(S)+i,ref,'shipment/hbl' if i=='hbl' else 'shipment/booking_no',S.hbl if i=='hbl' else S.so); S.asserted.add(i)
        t.done()
    return sref(S,gives)
def ship_ref(S): return sref(S,set())
# ---------- events
events=[]
def ev_add(dt,pri,kind,payload): events.append((dt,pri,len(events),kind,payload))
for d in docs:
    if d['kind']=='?': continue
    dt=datetime.strptime(d['date'],'%Y-%m-%d').replace(tzinfo=CN8)
    d['issued']=dt.isoformat(); ev_add(dt,0,d['kind'],d)
for r in E.ev:
    e=r['e']; r['hash']=e['hash']; r['url']=e['url']; r['issued']=e['dt'].isoformat()
    ev_add(e['dt'],1,r['kind'],r)
for c in chats:
    if c['k']:
        c['issued']=c['dt'].isoformat(); c['hash']=c['hash']; ev_add(c['dt'],1,'chat_'+c['k'],c)
events.sort(key=lambda x:(x[0],x[1],x[2]))
# deposit resolution
deposits=[]  # (dt,sup,po)
def pct_of(po):
    return Decimal(re.search(r'(\d+)% deposit',pis[po]['payment']).group(1))/100 if '% deposit' in pis[po]['payment'] else None
tot={po:sum(Decimal(r['qty'])*Decimal(r['price']) for r in d['rows']) for po,d in pis.items()}
for c in chats:
    if c['mine'] and re.search(r'[Dd]eposit',c['body']):
        m=re.search(r'(PO-\d{4}-\d{4})',c['body'])
        if m: po=m.group(1)
        else:
            amt=Decimal(num(re.search(r'(?:USD|CNY) ([\d,.]+)',c['body']).group(1)).rstrip('.'))
            cand=[p for p in pis if sup_of[p]==c['sup'] and pct_of(p) and (tot[p]*pct_of(p)).quantize(Decimal('0.01'))==amt]
            if len(cand)!=1: note('deposit unresolved',f"{c['url']} {amt} {cand}"); continue
            po=cand[0]
        deposits.append((c['dt'],c['sup'],po,c['url'],bool(m)))
# ---------- handlers
lines_sh={}     # (po,idx)->{key:qty}
def sum_ship(po,idx): return sum(lines_sh.get((po,idx),{}).values())
sup_done=set()
def h_PI(d):
    po=d['po']; code=PREF[d['pi'][:2]]; S_='sup:'+code
    t=T(d,'1',f"PI {d['pi']}")
    t.add(po,PO(po),'po/pi_number',d['pi']); t.add(po,PO(po),'po/supplier',["supplier/code",code],code)
    t.add(po,PO(po),'po/etd',d['etd']); t.add(po,PO(po),'core/currency',d['cur'])
    place=d['incoterm'].split(' ',1)[1]
    SU=["supplier/code",code]
    t.add(S_,SU,'supplier/name',d['name']); t.add(S_,SU,'supplier/name_cn',d['name_cn']); t.add(S_,SU,'supplier/address',d['addr'])
    t.add(S_,SU,'supplier/incoterm',d['incoterm']); t.add(S_,SU,'supplier/payment_terms',d['payment'].replace('T/T ',''))
    t.add(S_,SU,'supplier/currency',d['cur']); t.add(S_,SU,'supplier/port',PORT[place])
    for i,r in enumerate(d['rows'],1):
        k=f"{po}/{i}"; L=["po_line/key",k]
        t.add(k,L,'core/part_of',PO(po)); t.add(k,L,'po_line/sku',["factory/item_code",f"{code}:{r['item']}"],f"{code}:{r['item']}")
        t.add(k,L,'po_line/quantity',r['qty']); t.add(k,L,'po_line/unit_price',r['price'])
    set_status(t,po,'confirmed'); t.done()
def h_CI(d):
    S=d['S']; code=sup_of[d['po']]
    ref=open_ship(d,S,{'hbl'},f"CI {d['inv']}")
    t=T(d,'1',f"CI {d['inv']}"); K=skey(S)
    if d['container']!='LCL': t.add(K,ref,'shipment/container_no',d['container'])
    t.add(K,ref,'shipment/vessel',d['vessel']); t.add(K,ref,'shipment/origin',d['origin']); t.add(K,ref,'shipment/destination',d['dest'])
    for r in d['rows']:
        k=pl_key(d['po'],r['item']); key=f"{d['hbl']}/{k}"; L=["shipment_line/key",key]
        t.add(key,L,'core/part_of',ref,d['hbl']); t.add(key,L,'shipment_line/po_line',["po_line/key",k],k)
        t.add(key,L,'shipment_line/quantity',r['qty']); t.add(key,L,'shipment_line/cartons',str(d['cartons'][r['item']]))
        lines_sh.setdefault((d['po'],line_idx[(d['po'],r['item'])]),{})[key]=Decimal(r['qty'])
        hs=HS.get(f"{code}:{r['item']}")
        if hs is None: t.add('sku:'+code+r['item'],["factory/item_code",f"{code}:{r['item']}"],'sku/hs_code',r['hs'])
        elif hs!=r['hs']: note('HS differs',f"{d['url']} {code}:{r['item']} store {hs} CI {r['hs']}")
        pi_q=ordered[(d['po'],line_idx[(d['po'],r['item'])])]
        if Decimal(r['qty'])!=pi_q: note('CI qty != PO qty',f"{d['url']} {r['item']} {r['qty']} vs {pi_q}")
    t.done(); S.departed=True
def h_QC(d):
    t=T(d,'1',f"QC {d['report']}"); R=["qc/report_no",d['report']]; k='qc:'+d['report']
    t.add(k,R,'qc/po',PO(d['po']),d['po']); t.add(k,R,'qc/inspected_on',d['date']); t.add(k,R,'qc/result',d['result'])
    t.add(k,R,'qc/inspector','LinkCheck Inspection Services'); t.add(k,R,'qc/sample_size',d['sample'])
    if d['result']=='PASS': set_status(t,d['po'],'ready')
    t.done()
def h_chat_po_sent(c):
    po=c['po']; t=T(c,'1',f"chat PO sent {po}")
    t.add(po,PO(po),'po/placed_on',c['dt'].date().isoformat()); t.add(po,PO(po),'po/supplier',["supplier/code",c['sup']],c['sup'])
    set_status(t,po,'sent'); t.done()
def h_etd(c,conf,label):
    t=T(c,conf,label); t.add(c['po'],PO(c['po']),'po/etd',c['etd'].isoformat()); t.done()
def h_chat_etd_named(c): h_etd(c,'0.85' if 'pino' in c else '0.9',f"chat ETD {c['po']}")
UNN={}
for c in chats:
    if c['k']=='etd_unnamed':
        m=[po for po,d in pis.items() if sup_of[po]==c['sup'] and d['etd']==c['etd'].isoformat()]
        assert len(m)==1; c['po']=m[0]
def h_chat_etd_unnamed(c): h_etd(c,'0.8',f"chat ETD (PO via PI) {c['po']}")
def h_chat_container(c):
    po=[p for p,d in [(d['po'],d) for d in docs if d['kind']=='CI' and d['container']==c['container'] and sup_of[d['po']]==c['sup']]]
    if not po: note('container msg without CI',c['url']); return
    S=by_cont[c['container']]
    if not S.asserted: note('container msg: shipment not yet in store, left to CI',c['url']); return
    t=T(c,'0.9',f"chat container {c['container']}"); t.add(skey(S),ship_ref(S),'shipment/container_no',c['container']); t.done()
def recent_deposit(c,days=5):
    best=None
    for dt,sup,po,url,named in deposits:
        if sup==c['sup'] and dt<=c['dt'] and (c['dt']-dt).days<=days: best=(po,url)
    return best
def h_chat_ack(c):
    r=recent_deposit(c)
    if not r: note('ack without deposit',f"{c['url']} {c['body']}"); return
    t=T(c,'0.9',f"chat ack deposit {r[0]}"); set_status(t,r[0],'in_production'); t.done()
def h_chat_in_prod(c):
    cand=[po for dt,sup,po,url,n in deposits if sup==c['sup'] and dt<=c['dt'] and RANK.get(cur.get((po,'po/status')),0)<RANK['ready']]
    cand=list(dict.fromkeys(cand))
    if len(cand)!=1: note('in-production msg ambiguous, skipped',f"{c['url']} {cand}"); return
    t=T(c,'0.7',f"chat in production {cand[0]}"); set_status(t,cand[0],'in_production'); t.done()
def loc_of_ship(S): return S.dest
def h_booking(r):
    S=r['S']; ref=open_ship(r,S,{'so'},f"booking {r['so']}"); S.dest=r['pod']; S.origin=r['pol']
    t=T(r,'1',f"booking {r['so']}"); K=skey(S)
    mode={'LCL':'LCL','1x20GP':'20GP','1x40HQ':'40HQ'}[r['mode']]
    t.add(K,ref,'shipment/mode',mode); t.add(K,ref,'shipment/vessel',r['vessel']); t.add(K,ref,'shipment/origin',r['pol']); t.add(K,ref,'shipment/destination',r['pod'])
    t.add(K,ref,'shipment/etd',inst(r['etd'],r['pol'])); t.add(K,ref,'shipment/eta',inst(r['eta'],r['pod']))
    if S.status<1: t.add(K,ref,'shipment/status','booked'); S.status=1
    t.done()
def h_rolled(r):
    S=by_so[r['so']]; t=T(r,'1',f"rolled {r['so']}"); K=skey(S)
    t.add(K,ship_ref(S),'shipment/etd',inst(r['etd'],S.origin)); t.add(K,ship_ref(S),'shipment/eta',inst(r['eta'],S.dest)); t.done()
def po_complete(po):
    return all(sum_ship(po,i)>=ordered[(po,i)] for (p,i) in ordered if p==po)
def h_prealert(r):
    S=r['S']; h=r['hbl']
    ref=open_ship(r,S,{'hbl'},f"pre-alert {h}")
    pod=SPORT[r['pod_name']]; pol=PORT[r['pol_name']]
    if S.dest and S.dest!=pod: note('dest mismatch',f"{h} {S.dest} {pod}")
    S.dest=pod; S.origin=pol
    t=T(r,'1',f"pre-alert {h}"); K=skey(S)
    if r['container']!='LCL': t.add(K,ref,'shipment/container_no',r['container'])
    t.add(K,ref,'shipment/etd',inst(r['etd'],pol)); t.add(K,ref,'shipment/eta',inst(r['eta'],pod))
    if S.status<2: t.add(K,ref,'shipment/status','departed'); S.status=2
    for po,item,ctns,pcs in r['lines']:
        k=pl_key(po,item); key=f"{h}/{k}"; L=["shipment_line/key",key]
        t.add(key,L,'core/part_of',ref,h); t.add(key,L,'shipment_line/po_line',["po_line/key",k],k)
        t.add(key,L,'shipment_line/quantity',str(pcs)); t.add(key,L,'shipment_line/cartons',str(ctns))
        old=lines_sh.get((po,line_idx[(po,item)]),{}).get(key)
        if old is not None and old!=pcs: note('pre-alert qty != CI qty',f"{h} {k} {pcs} vs {old}")
        lines_sh.setdefault((po,line_idx[(po,item)]),{})[key]=Decimal(pcs)
    t.done(); S.departed=True
    for po in dict.fromkeys(l[0] for l in r['lines']):
        A=all(x.departed for x in po_ships[po]) and bool(po_ships[po]); B=po_complete(po)
        if A!=B: note('shipped criteria disagree',f"{po} bookings-all-departed={A} lines-sum-complete={B} at {h}")
        if A or B:
            t=T(r,'1' if A==B else '0.8',f"PO shipped {po}")
            if set_status(t,po,'shipped'): t.add(po,PO(po),'po/etd',r['etd'])
            t.done()
def h_eta(r):
    S=by_hbl[r['hbl']]; t=T(r,'1',f"ETA {r['hbl']}"); t.add(skey(S),ship_ref(S),'shipment/eta',inst(r['eta'],S.dest)); t.done()
def h_arrival(r):
    S=by_hbl[r['hbl']]; loc=SPORT[r['port']]
    if S.dest!=loc: note('arrival port != destination',f"{r['hbl']} {r['port']} {S.dest}")
    t=T(r,'1',f"arrival {r['hbl']}"); K=skey(S)
    if S.status<3: t.add(K,ship_ref(S),'shipment/status','arrived'); S.status=3
    t.add(K,ship_ref(S),'shipment/eta',inst(r['date'],loc)); t.done()
def h_receipt(r):
    ref_=r['ref']; S=by_hbl.get(ref_) or by_cont.get(ref_)
    t=T(r,'1',f"receipt {r['rcv']}"); K=skey(S)
    t.add(K,ship_ref(S),'shipment/status','delivered'); S.status=4; S.delivered=True
    t.add(K,ship_ref(S),'shipment/delivered_at',r['dt'].isoformat()); t.done()
    for po in [p for p,ss in po_ships.items() if S in ss and cur.get((p,'po/status'))=='shipped']:
        carrying={x for x in po_ships[po] if x.hbl}
        if all(x.delivered for x in carrying):
            t=T(r,'1',f"PO received {po}"); set_status(t,po,'received'); t.done()
def h_entry(r):
    b=r['e']['body']; g=lambda p:Decimal(num(re.search(p+r': USD ([\d,.]+)',b).group(1)))
    val=g('Entered value'); duty=g(r'Duty \(HTS\)')+g('Section 301')+g('Additional duties'); fees=g('MPF')+g('HMF'); tot_=g('Total duties and fees')
    if duty+fees!=tot_: note('entry total mismatch',f"{r['entry']}")
    ref_=r['ref']; S=by_hbl.get(ref_) or by_cont.get(ref_)
    t=T(r,'1',f"entry {r['entry']}"); k='cust:'+r['entry']; C=["customs/entry_no",r['entry']]
    t.add(k,C,'customs/shipment',["shipment/hbl",S.hbl],S.hbl); t.add(k,C,'customs/filed_on',r['dt'].date().isoformat())
    t.add(k,C,'customs/entered_value',str(val)); t.add(k,C,'customs/duty',str(duty)); t.add(k,C,'customs/fees',str(fees)); t.add(k,C,'core/currency','USD'); t.done()
HS={}
def load_hs(rows):
    for code,hs in rows: HS[code]=hs
H={'PI':h_PI,'CI':h_CI,'QC':h_QC,'booking':h_booking,'rolled':h_rolled,'prealert':h_prealert,'eta':h_eta,'arrival':h_arrival,'receipt':h_receipt,'entry':h_entry,
   'chat_po_sent':h_chat_po_sent,'chat_etd_named':h_chat_etd_named,'chat_etd_unnamed':h_chat_etd_unnamed,'chat_container':h_chat_container,
   'chat_ack_prod':h_chat_ack,'chat_ack_recv':h_chat_ack,'chat_in_prod':h_chat_in_prod}
def run(hs_rows):
    load_hs(hs_rows)
    for dt,pri,_,kind,p in events:
        if kind in H: H[kind](p)
        elif kind.startswith('chat_'): note('unhandled chat kind',kind)
