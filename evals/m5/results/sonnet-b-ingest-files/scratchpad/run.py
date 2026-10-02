import sys,re,json,datetime as dt,collections
import factstore
from model import *
from chats import chat_events
from parse_pdf import parse_qc

DRY = '--apply' not in sys.argv
RANK={s:i for i,s in enumerate('draft sent confirmed in_production ready shipped received'.split())}
SRANK={s:i for i,s in enumerate('booked departed arrived delivered'.split())}
SUPID={'DGRF':1219,'FSMJ':1220,'HZTY':1221,'NBBW':1222,'NBQS':1223,'SZHT':1224,'XMYD':1225,'YWLX':1226}
UTC=dt.timezone.utc
report=collections.defaultdict(list)
def R(k,s): report[k].append(s)

# documents already evidenced in the store
read_hashes={r[0] for r in factstore.query('select h.v from "core/evidence" ev join "document/hash" h on h.e=ev.v').rows}

def cn_noon(date_s):
    d=dt.date.fromisoformat(date_s); return dt.datetime(d.year,d.month,d.day,12,tzinfo=CN)

# ---------------------------------------------------------------- events
events=[]   # (utc ts, seq, kind, payload)
def add(ts,kind,**p): events.append((ts.astimezone(UTC),len(events),kind,p))
for f in sorted(H):
    if f.startswith('CI-PL'):
        if H[f] in read_hashes: R('skipped_read',f'supplier_docs/{f}')
        else: R('ci_unread',f)
        continue
    if H[f] in read_hashes: R('skipped_read',f'supplier_docs/{f}'); continue
    if f.startswith('LCI'):
        q=parse_qc(f); add(cn_noon(q['date']),'qc',f=f,q=q)
    else:
        d=PIS[parse_pi(f)['po']]; add(dt.datetime.fromisoformat(d['date']).replace(tzinfo=CN),'pi',f=f,d=d)
for e in chat_events():
    if e['msg']['hash'] in read_hashes: R('skipped_read',e['msg']['url']); continue
    add(e['msg']['ts'],'chat_'+e['kind'],**{k:v for k,v in e.items() if k!='kind'})
EM=emails()
bookings={}; prealerts={}
for e in EM:
    if e['hash'] in read_hashes: R('skipped_read',e['url']); continue
    s=e['subject']
    if s.startswith('Booking Confirmation'):
        b=parse_booking(e); bookings[b['so']]=b; add(e['date'],'booking',e=e,b=b)
    elif s.startswith('RE: Booking'): add(e['date'],'rolled',e=e)
    elif s.startswith('Shipping Advice'):
        p=parse_prealert(e); prealerts[p['hbl']]=p; add(e['date'],'prealert',e=e,p=p)
    elif s.startswith('ETA update'): add(e['date'],'eta_update',e=e)
    elif s.startswith('Arrival Notice'): add(e['date'],'arrival',e=e)
    elif s.startswith('Receipt complete'): add(e['date'],'receipt',e=e)
    elif s.startswith('Entry Summary'): add(e['date'],'entry',e=e)
    else: R('unhandled_email',s)
events.sort(key=lambda x:(x[0],x[1]))

# prealert <-> booking by vessel and shared POs
HBL2SO={}
for h,p in prealerts.items():
    pos={r[0] for r in p['rows']}
    c=[b for b in bookings.values() if b['vessel']==p['vessel'] and pos&set(b['pos'])]
    if len(c)==1: HBL2SO[h]=c[0]['so']
    else: R('unresolved',f'pre-alert {h}: {len(c)} candidate bookings')
SO2HBL={v:k for k,v in HBL2SO.items()}

# ---------------------------------------------------------------- state
po_status={}; po_etd={}; po_sup={}
for po,d in PIS.items(): po_sup[po]=d['sup']
ships={}      # key: so or hbl -> dict
def S(key,**kw):
    s=ships.setdefault(key,dict(so=None,hbl=None,container=None,pod=None,pol=None,status=None,lines={},delivered=False,atd=None))
    s.update(kw); return s
shipkey={}    # any identifier -> canonical key
def find_ship(*ids):
    for i in ids:
        if i in shipkey: return ships[shipkey[i]]
def link(s,*ids):
    for i in ids:
        if i: shipkey[i]=s['_k']
def ship_ref(s):
    return ['shipment/hbl',s['hbl']] if s['hbl_written'] else ['shipment/booking_no',s['so']]

nfacts=0; ntx=0
def tx(doc_hash,url,facts,conf='1',what=''):
    global nfacts,ntx
    if not facts: return
    facts=facts+[{'e':['document/hash',doc_hash],'a':'document/url','v':url},
      {'e':'tmp:tx','a':'core/evidence','v':['document/hash',doc_hash]},
      {'e':'tmp:tx','a':'core/confidence','v':conf}]
    r=factstore.transact(facts,dry_run=DRY)
    ntx+=1; nfacts+=len(facts)
    return r
def F(e,a,v): return {'e':e,'a':a,'v':v}
def status_fact(po,new):
    cur=po_status.get(po)
    if cur is None or RANK[new]>RANK[cur]:
        po_status[po]=new; return [F(['po/number',po],'po/status',new)]
    return []
def new_ship(so=None,hbl=None):
    k=so or hbl
    s=S(k); s['_k']=k; s['so']=so; s['hbl']=hbl; s.setdefault('hbl_written',bool(hbl and not so)); link(s,so,hbl); return s

def po_line_key(po,item):
    d=PIS.get(po)
    if not d: return None
    for i,it in enumerate(d['items'],1):
        if it['item']==item: return f'{po}/{i}',it
    return None

def po_shipped_check(po):
    d=PIS[po]; tot=collections.Counter()
    for s in ships.values():
        for (p,i),(q,c) in s['lines'].items():
            if p==po: tot[i]+=q
    complete=all(tot[it['item']]>=it['qty'] for it in d['items'])
    bks=[b for b in bookings.values() if po in b['pos']]
    allpre=bool(bks) and all(find_ship(b['so'])['hbl'] for b in bks if find_ship(b['so']))
    return complete,allpre

# ---------------------------------------------------------------- process
for ts,_,kind,p in events:
    if kind=='pi':
        d=p['d'];po=d['po'];h=H[p['f']];sup=SUPID[d['sup']];f=[]
        sref=sup
        f+=[F(sref,'supplier/name',d['name'].title().replace('Co., Ltd.','Co., Ltd.') if False else d['name']),F(sref,'supplier/name_cn',d['name_cn']),
            F(sref,'supplier/address',d['address']),F(sref,'supplier/incoterm',d['incoterm']),F(sref,'supplier/payment_terms',re.sub(r'^T/T ','',d['payment']) if False else d['payment'])]
        P=['po/number',po]
        f+=[F(P,'po/pi_number',d['pi']),F(P,'po/supplier',sup),F(P,'po/etd',d['etd']),F(P,'core/currency','CNY' if d['items'][0]['cur']=='RMB' else d['items'][0]['cur'])]
        po_etd[po]=d['etd']
        f+=status_fact(po,'confirmed')
        for i,it in enumerate(d['items'],1):
            L=['po_line/key',f'{po}/{i}']
            f+=[F(L,'core/part_of',P),F(L,'po_line/sku',['factory/item_code',f"{d['sup']}:{it['item']}"]),
                F(L,'po_line/quantity',str(it['qty'])),F(L,'po_line/unit_price',it['price'])]
        tx(h,f"supplier_docs/{p['f']}",f)
    elif kind=='qc':
        q=p['q'];h=H[p['f']];po=q['po'].strip()
        if not re.fullmatch(r'PO-\d{4}-\d{4}',po): R('unresolved',f"QC {q['report']}: PO '{po}'"); continue
        Q=['qc/report_no',q['report']]
        f=[F(Q,'qc/po',['po/number',po]),F(Q,'qc/inspected_on',q['date']),F(Q,'qc/result',q['result']),
           F(Q,'qc/inspector',q['agency'].title()),F(Q,'qc/sample_size',str(q['sample']))]
        if q['result']=='PASS': f+=status_fact(po,'ready')
        tx(h,f"supplier_docs/{p['f']}",f)
    elif kind=='chat_etd_pi':
        po=p['po'];m=p['msg'];dstr=p['date'].isoformat()
        if po_etd.get(po)==dstr: continue
        R('chat_etd_pi_diff',f"{m['url']} {po}: chat {dstr} vs store {po_etd.get(po)}")
    elif kind=='chat_etd_slip':
        po=p['po'];m=p['msg'];dstr=p['date'].isoformat()
        if RANK.get(po_status.get(po),0)>=RANK['shipped']: R('unresolved',f"{m['url']}: ETD slip for {po} after it shipped"); continue
        if po_etd.get(po)==dstr: continue
        conf='0.9' if p['named']=='po' else '0.8'
        po_etd[po]=dstr
        tx(m['hash'],m['url'],[F(['po/number',po],'po/etd',dstr)],conf)
        R('lowconf',f"{m['url']}: po/etd {po} = {dstr} @ {conf} (year-less date{'' if p['named']=='po' else ', PO identified by PI number'})")
    elif kind=='chat_deposit_ack':
        po=p['po'];m=p['msg']
        if not po: continue
        conf='0.9' if p['named'] else '0.8'
        f=status_fact(po,'in_production')
        if f:
            tx(m['hash'],m['url'],f,conf)
            R('lowconf',f"{m['url']}: {po} in_production @ {conf} (supplier acknowledged deposit{'' if p['named'] else '; PO inferred from the PI sent just before'})")
    elif kind=='chat_in_production':
        po=p['po'];m=p['msg']
        if not po: continue
        f=status_fact(po,'in_production')
        if f:
            tx(m['hash'],m['url'],f,'0.6')
            R('lowconf',f"{m['url']}: {po} in_production @ 0.6 ('大货生产中' with no PO named; PO = last PI in this chat)")
    elif kind=='chat_container':
        m=p['msg'];c=p['container'];sup=m['sup'];cn=m['ts'].astimezone(CN).date()
        cands=[pa for pa in prealerts.values() if pa['container']==c and any(po_sup.get(r[0])==sup for r in pa['rows']) and pa['atd']>=cn-dt.timedelta(days=3)]
        cands.sort(key=lambda x:x['atd'])
        if not cands: R('unresolved',f"{m['url']}: container {c} matches no pre-alert for {sup}"); continue
        pa=cands[0]; so=HBL2SO.get(pa['hbl'])
        if not so: R('unresolved',f"{m['url']}: container {c} -> {pa['hbl']} has no booking"); continue
        s=find_ship(so)
        if s is None: s=new_ship(so=so)
        ref=ship_ref(s)
        tx(m['hash'],m['url'],[F(ref,'shipment/container_no',c)],'0.8')
        s['container']=c; shipkey.setdefault(c+'@'+so,s['_k'])
        R('lowconf',f"{m['url']}: container {c} -> {so} @ 0.8 (no PO named; shipment found by container + supplier + date)")
    elif kind=='booking':
        b=p['b'];e=p['e']
        s=find_ship(b['so']) or new_ship(so=b['so'])
        s.update(pod=b['pod'],pol=b['pol'],status='booked')
        ref=['shipment/booking_no',b['so']]
        f=[F(ref,'shipment/mode',b['mode']),F(ref,'shipment/vessel',b['vessel']),F(ref,'shipment/origin',b['pol']),F(ref,'shipment/destination',b['pod']),
           F(ref,'shipment/etd',b['etd'].isoformat()),F(ref,'shipment/eta',b['eta'].isoformat())]
        if s.get('status_w') is None or SRANK['booked']>SRANK[s['status_w']]: f.append(F(ref,'shipment/status','booked')); s['status_w']='booked'
        tx(e['hash'],e['url'],f)
    elif kind=='rolled':
        e=p['e'];so=re.search(r'SO (\S+) -',e['subject']).group(1)
        m=re.search(r'New ETD (.+?), ETA (.+?)\.',e['body'])
        s=find_ship(so); b=bookings[so]
        if s is None or (s.get('status_w') and SRANK[s['status_w']]>=SRANK['departed']): R('unresolved',f"{e['url']}: rolled {so} after departure/unknown"); continue
        ref=ship_ref(s)
        tx(e['hash'],e['url'],[F(ref,'shipment/etd',at_port(mon(m.group(1)),b['pol']).isoformat()),F(ref,'shipment/eta',at_port(mon(m.group(2)),b['pod']).isoformat())])
    elif kind=='prealert':
        pa=p['p'];e=p['e'];hbl=pa['hbl'];so=HBL2SO.get(hbl)
        s=find_ship(hbl,so) if so else find_ship(hbl)
        if s is None: s=new_ship(so=so,hbl=hbl)
        first_link=not s['hbl']
        s['hbl']=hbl; link(s,hbl)
        ref=['shipment/booking_no',so] if (so and first_link) else ['shipment/hbl',hbl]
        pol=s['pol'] or ('CNYTN'); pod=s['pod']
        f=[]
        if first_link: f.append(F(ref,'shipment/hbl',hbl));
        if pa['container']: f.append(F(ref,'shipment/container_no',pa['container'])); s['container']=pa['container']
        f+=[F(ref,'shipment/etd',at_port(pa['atd'],pol).isoformat()),F(ref,'shipment/eta',at_port(pa['eta_d'],pod).isoformat()),F(ref,'shipment/status','departed')]
        s['status_w']='departed'; s['atd']=pa['atd']; s['hbl_written']=True
        S_=ref
        for (po,item,ctns,pcs) in pa['rows']:
            r=po_line_key(po,item)
            if not r: R('unresolved',f"{e['url']}: {po} item {item} not on a PI"); continue
            key,it=r
            if pcs!=it['qty']: R('note',f"{hbl} {po} {item}: shipped {pcs} vs ordered {it['qty']}")
            L=['shipment_line/key',f'{hbl}/{key}']
            f+=[F(L,'core/part_of',ref),F(L,'shipment_line/po_line',['po_line/key',key]),F(L,'shipment_line/quantity',str(pcs)),F(L,'shipment_line/cartons',str(ctns))]
            s['lines'][(po,item)]=(pcs,ctns)
        pos=sorted({r[0] for r in pa['rows']})
        for po in pos:
            complete,allpre=po_shipped_check(po)
            if complete!=allpre: R('note',f"{po}: shipped-by-lines={complete} shipped-by-bookings={allpre} at {hbl}")
            if complete or allpre:
                sf=status_fact(po,'shipped')
                if sf:
                    f+=sf; f.append(F(['po/number',po],'po/etd',pa['atd'].isoformat())); po_etd[po]=pa['atd'].isoformat()
        tx(e['hash'],e['url'],f)
    elif kind in ('eta_update','arrival'):
        e=p['e'];hbl=re.search(r'HBL (PBLHB\d+)',e['subject']).group(1)
        s=find_ship(hbl)
        if not s: R('unresolved',f"{e['url']}: unknown HBL {hbl}"); continue
        if kind=='eta_update': d=mon(re.search(r'revised ETA (.+?) for',e['body']).group(1)); f=[F(['shipment/hbl',hbl],'shipment/eta',at_port(d,s['pod']).isoformat())]
        else:
            d=mon(re.search(r' on (\d\d \w{3} \d{4})\.',e['body']).group(1))
            f=[F(['shipment/hbl',hbl],'shipment/status','arrived'),F(['shipment/hbl',hbl],'shipment/eta',at_port(d,s['pod']).isoformat())]
            s['status_w']='arrived'; s['arrived']=ts
        tx(e['hash'],e['url'],f)
    elif kind in ('receipt','entry'):
        e=p['e'];ident=re.search(r' - (\S+)$',e['subject']).group(1)
        if ident.startswith('PBLHB'): cand=[ships[k] for k in {shipkey[ident]}] if ident in shipkey else []
        else:
            cand=[s for s in ships.values() if s['container']==ident and s['status_w'] in ('departed','arrived','delivered')]
            cand=[s for s in cand if kind=='entry' or not s.get('delivered')]
            cand=[s for s in cand if (s.get('atd') and dt.datetime.combine(s['atd'],dt.time(),tzinfo=UTC)<=ts)]
            cand.sort(key=lambda s:s['atd'])
            if len(cand)>1: cand=[cand[-1]]
        if not cand: R('unresolved',f"{e['url']}: no shipment for {ident}"); continue
        s=cand[0]
        if kind=='receipt':
            ref=['shipment/hbl',s['hbl']]
            tx(e['hash'],e['url'],[F(ref,'shipment/status','delivered'),F(ref,'shipment/delivered_at',e['date'].isoformat())])
            s['delivered']=True;s['status_w']='delivered'
            disc=re.search(r'Discrepancies:\n((?:  .*\n)+)',e['body'])
            if disc: R('discrepancy',f"{e['url']} ({ident}): "+'; '.join(x.strip() for x in disc.group(1).strip().split('\n')))
            for po in sorted({k[0] for k in s['lines']}):
                sh=[x for x in ships.values() if any(k[0]==po for k in x['lines'])]
                if all(x['delivered'] for x in sh):
                    f=status_fact(po,'received')
                    if f: tx(e['hash'],e['url'],f)
        else:
            body=e['body'];g=lambda k:float(re.search(k+r': USD ([\d,.]+)',body).group(1).replace(',',''))
            en=re.search(r'Entry (\S+) filed',body).group(1)
            duty=g(r'Duty \(HTS\)')+g('Section 301')+g('Additional duties'); fees=g('MPF')+g('HMF')
            if abs(duty+fees-g('Total duties and fees'))>0.011: R('note',f"{en}: duty+fees != total")
            C=['customs/entry_no',en]
            tx(e['hash'],e['url'],[F(C,'customs/shipment',['shipment/hbl',s['hbl']]),F(C,'customs/filed_on',e['date'].date().isoformat()),
               F(C,'customs/entered_value',f"{g('Entered value'):.2f}"),F(C,'customs/duty',f'{duty:.2f}'),F(C,'customs/fees',f'{fees:.2f}'),F(C,'core/currency','USD')])

print('DRY' if DRY else 'APPLIED','tx',ntx,'facts',nfacts)
for k,v in report.items():
    print('==',k,len(v))
    for x in v[:400 if k not in('skipped_read','lowconf') else 6]: print('  ',x)
