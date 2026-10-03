import re,glob,json,sys
from decimal import Decimal as D
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
import factstore
from parse_docs import pdf_docs,CST
from parse_mail import mail_docs
from chat import parse as chat_parse
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-r-fnyh54rx/ingest/work/exports/'
NY=ZoneInfo('America/New_York'); LA=ZoneInfo('America/Los_Angeles')
PORTTZ={'USNYC':NY,'USLAX':LA}
PORTCODE={'Ningbo':'CNNGB','Yantian':'CNYTN','Nansha':'CNNSA','Xiamen':'CNXMN','New York/Newark':'USNYC','Los Angeles':'USLAX'}
RANK=['draft','sent','confirmed','in_production','ready','shipped','received']
SRANK=['booked','departed','arrived','delivered']
def inst(d,tz): return datetime(d.year,d.month,d.day,tzinfo=tz).isoformat()
def origin_tz(code): return CST
def dest_tz(code): return PORTTZ[code]

# ---- catalogue from store
sku_hs={r[0]:r[1] for r in factstore.query('select c.v,h.v from "factory/item_code" c join "sku/hs_code" h using(e)').rows}
code_to_supplier={c:c for c in ['NBBW','SZHT','YWLX','DGRF','FSMJ','XMYD','NBQS','HZTY']}

pos={}   # po -> dict
def PO(n):
    return pos.setdefault(n,dict(n=n,status=None,sup=None,lines={},order=[],etd=None,pi=None,total=None,dep=None,cur=None,placed=None))
ships=[]  # list of dicts
reports=dict(mismatch=[],unresolved=[],notes=[],lowconf=[],hs=[],shortfalls=[],skipped=[])
txs=[]
def tx(doc,conf,facts,note=''):
    if facts: txs.append(dict(doc=doc,conf=conf,facts=facts,note=note))
def docinfo(d): return dict(hash=d['hash'],url=d['url'],issued=d['issued'].isoformat())
def pol_ref(po,n): return f"{po}/{n}"
def advance_po(po,new,facts):
    p=PO(po); cur=p['status']
    if cur is None or RANK.index(new)>RANK.index(cur):
        p['status']=new; facts.append({"e":["po/number",po],"a":"po/status","v":new}); return True
    return False
def sref(s):
    if s.get('booking'): return ["shipment/booking_no",s['booking']]
    return ["shipment/hbl",s['hbl']]
def advance_ship(s,new,facts):
    cur=s.get('status')
    if cur is None or SRANK.index(new)>SRANK.index(cur):
        s['status']=new; facts.append({"e":sref(s),"a":"shipment/status","v":new}); return True
    return False
def find_ship(hbl=None,container=None,vessel=None,posset=None,so=None):
    for s in ships:
        if hbl and s.get('hbl')==hbl: return s
        if so and s.get('booking')==so: return s
    if container:
        for s in ships:
            if s.get('container')==container: return s
    if vessel and posset:
        c=[s for s in ships if s.get('vessel')==vessel and not s.get('hbl') and s.get('pos') and (s['pos']&posset)]
        if len(c)==1: return c[0]
        if len(c)>1: reports['unresolved'].append(('ambiguous booking match',vessel,sorted(posset)))
    return None
suffix={}  # int -> po number (filled from PIs/chats)
def norm_po(tok):
    m=re.search(r'(\d{4})-(\d{4})',tok)
    if m: return f"PO-{m.group(1)}-{m.group(2)}"
    m=re.search(r'(\d+)$',tok.strip()); n=int(m.group(1))
    return suffix.get(n)

# ---- gather docs
pdfs=pdf_docs(); mails=mail_docs()
chat_msgs=[]
for f in sorted(glob.glob(W+'wechat/*.txt')):
    code=re.match(r'(\w+?)_',f.split('/')[-1]).group(1)
    for m in chat_parse(f): m['code']=code; m['issued']=m['dt']; chat_msgs.append(m)
for d in pdfs:
    if d['kind']=='pi': suffix[int(d['po'][-4:])]=d['po']
for m in chat_msgs:
    for x in re.findall(r'PO-\d{4}-\d{4}',m['text']): suffix[int(x[-4:])]=x
for r in factstore.query('select v from "po/number"').rows: suffix[int(r[0][-4:])]=r[0]
pi_to_po={d['pi']:d['po'] for d in pdfs if d['kind']=='pi'}
# container -> po by supplier from CIs
ci_cont={}
for d in pdfs:
    if d['kind']=='ci' and d['container']!='LCL': ci_cont[(d['code'],d['container'])]=d['po']

events=[]
for d in pdfs: events.append((d['issued'],0,d['kind'],d))
for d in mails: events.append((d['issued'],1,d['kind'],d))
# chat events
pending={}  # code -> list of deposits
placed_re=re.compile(r"(new PO (PO-\d{4}-\d{4}) attached|here's (PO-\d{4}-\d{4})\.|PO (PO-\d{4}-\d{4}) for \d+ items)")
def mdate(s,ref_dt):
    m=re.search(r'(\d+)/(\d+)',s) or None
    if m: mo,dd=int(m.group(1)),int(m.group(2))
    else:
        m=re.search(r'(\d+)月(\d+)号',s); mo,dd=int(m.group(1)),int(m.group(2))
    ref=ref_dt.astimezone(CST).date()
    for y in (ref.year,ref.year+1):
        c=date(y,mo,dd)
        if c>=ref: return c
chat_events=[]
for m in chat_msgs:
    t=m['text']
    if m['us']:
        mm=placed_re.search(t)
        if mm:
            po=[g for g in mm.groups()[1:] if g][0]; chat_events.append((m,'placed',dict(po=po)))
        elif re.search(r'[Dd]eposit',t):
            am=re.search(r'(USD|CNY) ([\d,]+\.\d\d)',t); po=re.search(r'PO-\d{4}-\d{4}',t)
            chat_events.append((m,'deposit',dict(cur=am.group(1),amt=D(am.group(2).replace(',','')),po=po.group(0) if po else None)))
    else:
        mm=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+/\d+)',t)
        if mm: chat_events.append((m,'etd',dict(po=mm.group(1),date=mdate(mm.group(2),m['dt']),conf='0.9',how='PO named')));continue
        mm=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+月\d+号)',t)
        if mm: chat_events.append((m,'etd',dict(po=mm.group(1),date=mdate(mm.group(2),m['dt']),conf='0.9',how='PO named')));continue
        mm=re.search(r'(\S+) 大货要晚一点.*预计(\d+/\d+)出货',t)
        if mm: chat_events.append((m,'etd',dict(pi=mm.group(1),date=mdate(mm.group(2),m['dt']),conf='0.85',how='PI number')));continue
        if re.search(r'已装柜 container loaded: ([A-Z]{4}\d{7})|Container ([A-Z]{4}\d{7}) loaded today',t):
            c=re.search(r'[A-Z]{4}\d{7}',t).group(0); chat_events.append((m,'container',dict(container=c)));continue
        if re.search(r'收到|Received, thank',t): chat_events.append((m,'ack',{}));continue
        if '大货生产中' in t: chat_events.append((m,'prodstart',{}))
for m,k,x in chat_events: events.append((m['issued'],2,'chat_'+k,dict(m=m,x=x,hash=m['hash'],url=m['url'],issued=m['issued'])))
events.sort(key=lambda e:(e[0],e[1],e[3].get('url','')))

def pdfdoc_facts(d): return d
def sup_of(po): return PO(po)['sup']
def line_for(po,item):
    p=PO(po); code=f"{p['sup']}:{item}"
    for k,l in p['lines'].items():
        if l['code']==code: return k,l
    return None,None

def check_ship_status(po,d,facts_out,atd=None):
    """evaluate shipped / etd for a PO; returns facts"""
    p=PO(po)
    if not p['lines']: return
    tot={}
    for s in ships:
        for k,q in s['lines'].items():
            if k.split('/',1)[1].rsplit('/',1)[0]==po: tot[k.split('/',1)[1]]=tot.get(k.split('/',1)[1],0)+q
    done=all(tot.get(k,0)>=l['qty'] for k,l in p['lines'].items())
    carrying=[s for s in ships if any(k.split('/',1)[1].rsplit('/',1)[0]==po for k in s['lines'])]
    if done:
        advance_po(po,'shipped',facts_out)
    if p['status'] and RANK.index(p['status'])>=RANK.index('shipped'):
        atds=[s['atd'] for s in carrying if s.get('atd')]
        if atds:
            a=max(atds).date().isoformat()
            if p['etd']!=a:
                p['etd']=a; facts_out.append({"e":["po/number",po],"a":"po/etd","v":a})
def check_received(po,facts_out):
    p=PO(po)
    if not p['status'] or RANK.index(p['status'])<RANK.index('shipped'): return
    carrying=[s for s in ships if any(k.split('/',1)[1].rsplit('/',1)[0]==po for k in s['lines'])]
    if carrying and all(s.get('status')=='delivered' for s in carrying): advance_po(po,'received',facts_out)

def do_ship_lines(s,hbl,items,d,facts):
    """items: list of (po, item, qty, ctns)"""
    for po,item,qty,ctns in items:
        k,l=line_for(po,item)
        if k is None:
            reports['unresolved'].append(('no PO line',d['url'],po,item)); continue
        key=f"{hbl}/{k}"
        if key in s['lines'] and s['lines'][key]!=D(qty):
            reports['mismatch'].append(('shipment line qty differs',key,s['lines'][key],qty,d['url']))
        s['lines'][key]=D(qty)
        e=["shipment_line/key",key]
        facts+= [{"e":e,"a":"core/part_of","v":sref(s)},{"e":e,"a":"shipment_line/po_line","v":["po_line/key",k]},
                 {"e":e,"a":"shipment_line/quantity","v":str(qty)}]
        if ctns is not None: facts.append({"e":e,"a":"shipment_line/cartons","v":str(ctns)})

for issued,_,kind,d in events:
    di=docinfo(d)
    if kind=='pi':
        po=d['po']; p=PO(po); f=[]
        p['sup']=d['code']; p['pi']=d['pi']; p['total']=D(d['total']); p['dep']=d['dep']; p['cur']=d['cur']
        e=["po/number",po]; sup=["supplier/code",d['code']]
        f+= [{"e":e,"a":"po/pi_number","v":d['pi']},{"e":e,"a":"po/supplier","v":sup},{"e":e,"a":"core/currency","v":d['cur']}]
        if not (p['status'] and RANK.index(p['status'])>=RANK.index('shipped')):
            p['etd']=d['etd']; f.append({"e":e,"a":"po/etd","v":d['etd']})
        advance_po(po,'confirmed',f)
        for i,it in enumerate(d['items'],1):
            code=f"{d['code']}:{it['item']}"
            ex=[k for k,l in p['lines'].items() if l['code']==code]
            k=ex[0] if ex else f"{po}/{len(p['lines'])+1}"
            p['lines'][k]=dict(code=code,qty=D(it['qty']),price=it['price'])
            le=["po_line/key",k]
            f+= [{"e":le,"a":"core/part_of","v":e},{"e":le,"a":"po_line/sku","v":["factory/item_code",code]},
                 {"e":le,"a":"po_line/quantity","v":it['qty']},{"e":le,"a":"po_line/unit_price","v":it['price']}]
        port=PORTCODE[d['incoterm'].split()[-1]]
        f+= [{"e":sup,"a":"supplier/name_cn","v":d['name_cn']},{"e":sup,"a":"supplier/name","v":d['legal']},{"e":sup,"a":"supplier/address","v":d['addr']},
             {"e":sup,"a":"supplier/incoterm","v":d['incoterm']},{"e":sup,"a":"supplier/payment_terms","v":d['payment']},
             {"e":sup,"a":"supplier/currency","v":d['cur']},{"e":sup,"a":"supplier/port","v":port}]
        tx(di,'1',f,'PI '+d['pi'])
    elif kind=='ci':
        po=d['po']; p=PO(po); f=[]
        if p['sup']!=d['code']: reports['unresolved'].append(('CI supplier != PO supplier',d['url'])); 
        hbl=d['hbl']; posset={po}
        s=find_ship(hbl=hbl,container=None if d['container']=='LCL' else d['container'],vessel=d['vessel'],posset=posset)
        if s is None:
            s=dict(hbl=hbl,booking=None,pos={po},lines={},status=None,vessel=None,container=None,dest=None,origin=None)
            ships.append(s)
        elif not s.get('hbl'):
            s['hbl']=hbl; f.append({"e":sref(s),"a":"shipment/hbl","v":hbl})
        s.setdefault('pos',set()).add(po)
        r=sref(s)
        if d['container']!='LCL':
            s['container']=d['container']; f.append({"e":r,"a":"shipment/container_no","v":d['container']})
        s['vessel']=d['vessel']; s['origin']=d['origin']; s['dest']=d['dest']
        f+= [{"e":r,"a":"shipment/vessel","v":d['vessel']},{"e":r,"a":"shipment/origin","v":d['origin']},{"e":r,"a":"shipment/destination","v":d['dest']}]
        items=[(po,i['item'],i['qty'],d['pl'][i['item']]['ctns']) for i in d['items']]
        do_ship_lines(s,hbl,items,d,f)
        for i in d['items']:
            k,l=line_for(po,i['item'])
            if k and l:
                h=sku_hs.get(l['code'])
                if h and h!=i['hs']: reports['hs'].append((l['code'],h,i['hs'],d['url']))
                if not h: f.append({"e":["factory/item_code",l['code']],"a":"sku/hs_code","v":i['hs']})
        check_ship_status(po,d,f)
        tx(di,'1',f,'CI '+d['inv'])
    elif kind=='qc':
        po=d['po']; f=[]; e=["qc/report_no",d['report']]
        f+= [{"e":e,"a":"qc/po","v":["po/number",po]},{"e":e,"a":"qc/inspected_on","v":d['date']},{"e":e,"a":"qc/result","v":d['result']},
             {"e":e,"a":"qc/inspector","v":d['agency']},{"e":e,"a":"qc/sample_size","v":d['sample']}]
        if d['result']=='PASS': advance_po(po,'ready',f)
        tx(di,'1',f,'QC '+d['report'])
    elif kind=='booking':
        f=[]; pset={norm_po(t) for t in re.findall(r'PO[#\- ]?\s?[\d-]+|po \d+',d['pos_raw'])}
        if None in pset: reports['unresolved'].append(('booking PO unresolved',d['pos_raw']))
        pset.discard(None)
        s=find_ship(so=d['so'])
        if s is None:
            s=dict(booking=d['so'],hbl=None,pos=pset,lines={},status=None); ships.append(s)
        s.update(vessel=d['vessel'],origin=d['pol'],dest=d['pod'],etd=d['etd'],eta=d['eta'],pos=pset)
        r=["shipment/booking_no",d['so']]
        mode='LCL' if d['equip'].startswith('LCL') else re.search(r'1x(\w+)',d['equip']).group(1)
        f+= [{"e":r,"a":"shipment/mode","v":mode},{"e":r,"a":"shipment/vessel","v":d['vessel']},{"e":r,"a":"shipment/origin","v":d['pol']},
             {"e":r,"a":"shipment/destination","v":d['pod']},{"e":r,"a":"shipment/etd","v":inst(d['etd'],CST)},
             {"e":r,"a":"shipment/eta","v":inst(d['eta'],dest_tz(d['pod']))}]
        advance_ship(s,'booked',f)
        tx(di,'1',f,'Booking '+d['so']+' '+d['pos_raw'])
    elif kind=='rolled':
        s=find_ship(so=d['so']); f=[]
        if not s: reports['unresolved'].append(('rolled booking unknown',d['so'])); continue
        r=["shipment/booking_no",d['so']]
        f+= [{"e":r,"a":"shipment/etd","v":inst(d['etd'],CST)},{"e":r,"a":"shipment/eta","v":inst(d['eta'],dest_tz(s['dest']))}]
        tx(di,'1',f,'Rolled '+d['so'])
    elif kind=='prealert':
        f=[]; posset={l['po'] for l in d['lines']}
        s=find_ship(hbl=d['hbl'],container=d['container'],vessel=d['vessel'],posset=posset)
        newship=False
        if s is None:
            s=dict(hbl=d['hbl'],booking=None,pos=set(posset),lines={},status=None); ships.append(s); newship=True
            reports['notes'].append(('pre-alert without booking: shipment created from HBL',d['hbl']))
        elif not s.get('hbl'):
            s['hbl']=d['hbl']; f.append({"e":sref(s),"a":"shipment/hbl","v":d['hbl']})
        s['pos']|=posset
        r=sref(s)
        if d['container']: s['container']=d['container']; f.append({"e":r,"a":"shipment/container_no","v":d['container']})
        elif newship: f.append({"e":r,"a":"shipment/mode","v":"LCL"})
        if s.get('vessel')!=d['vessel']: f.append({"e":r,"a":"shipment/vessel","v":d['vessel']}); s['vessel']=d['vessel']
        oc=PORTCODE[d['origin_name']]
        dc='USLAX' if 'ETA Los Angeles' in d['body'] else 'USNYC'
        if not s.get('origin'): s['origin']=oc; f.append({"e":r,"a":"shipment/origin","v":oc})
        if not s.get('dest'): s['dest']=dc; f.append({"e":r,"a":"shipment/destination","v":dc})
        if s['origin']!=oc or s['dest']!=dc: reports['mismatch'].append(('prealert ports differ from booking',d['hbl'],s['origin'],oc,s['dest'],dc))
        atd=datetime(d['atd'].year,d['atd'].month,d['atd'].day,tzinfo=CST); s['atd']=atd
        f+= [{"e":r,"a":"shipment/etd","v":atd.isoformat()},{"e":r,"a":"shipment/eta","v":inst(d['eta'],dest_tz(s['dest']))}]
        s['etd']=d['atd']
        advance_ship(s,'departed',f)
        items=[(l['po'],l['item'],l['qty'],l['ctns']) for l in d['lines']]
        do_ship_lines(s,d['hbl'],items,d,f)
        for po in sorted(posset): check_ship_status(po,d,f)
        tx(di,'1',f,'Prealert '+d['hbl'])
    elif kind=='eta':
        s=find_ship(hbl=d['hbl']); 
        if not s: reports['unresolved'].append(('eta update unknown hbl',d['hbl'])); continue
        tx(di,'1',[{"e":sref(s),"a":"shipment/eta","v":inst(d['eta'],dest_tz(s['dest']))}],'ETA '+d['hbl'])
    elif kind=='arrival':
        s=find_ship(hbl=d['hbl']); f=[]
        if not s: reports['unresolved'].append(('arrival unknown hbl',d['hbl'])); continue
        dc=PORTCODE[d['port']]
        if dc!=s.get('dest'): reports['mismatch'].append(('arrival port differs',d['hbl'],s.get('dest'),dc))
        f.append({"e":sref(s),"a":"shipment/eta","v":inst(d['date'],dest_tz(dc))})
        advance_ship(s,'arrived',f)
        tx(di,'1',f,'Arrival '+d['hbl'])
    elif kind=='receipt':
        ref=d['ref']; s=find_ship(hbl=ref,container=ref); f=[]
        if not s: reports['unresolved'].append(('receipt unknown shipment',ref)); continue
        f.append({"e":sref(s),"a":"shipment/delivered_at","v":d['issued'].isoformat()})
        advance_ship(s,'delivered',f)
        for po in sorted({k.split('/',1)[1].rsplit('/',1)[0] for k in s['lines']}): check_received(po,f)
        for it in d['disc']:
            if it[2]!=it[3]: reports['shortfalls'].append((ref,d['rcv'],it))
        tx(di,'1',f,'Receipt '+ref)
    elif kind=='entry':
        s=find_ship(hbl=d['ref'],container=d['ref']); f=[]
        if not s: reports['unresolved'].append(('entry unknown shipment',d['entry'],d['ref'])); continue
        e=["customs/entry_no",d['entry']]
        duty=D(d['hts'])+D(d['s301'])+D(d['add']); fees=D(d['mpf'])+D(d['hmf'])
        f+= [{"e":e,"a":"customs/shipment","v":sref(s)},{"e":e,"a":"customs/filed_on","v":d['issued'].date().isoformat()},
             {"e":e,"a":"customs/entered_value","v":d['value']},{"e":e,"a":"customs/duty","v":str(duty)},{"e":e,"a":"customs/fees","v":str(fees)},
             {"e":e,"a":"core/currency","v":"USD"}]
        tx(di,'1',f,'Entry '+d['entry'])
    # ---- chats
    elif kind=='chat_placed':
        m=d['m']; po=d['x']['po']; p=PO(po); p['sup']=p['sup'] or m['code']
        if p['sup']!=m['code']: reports['mismatch'].append(('PO supplier differs from chat',po,p['sup'],m['code']))
        p['placed']=m['dt'].date().isoformat()
        tx(di,'1',[{"e":["po/number",po],"a":"po/placed_on","v":p['placed']},{"e":["po/number",po],"a":"po/supplier","v":["supplier/code",m['code']]}],'placed '+po)
    elif kind=='chat_deposit':
        m=d['m']; x=d['x']; code=m['code']; po=x['po']
        if not po:
            c=[q for q,p in pos.items() if p['sup']==code and p['dep'] and p['cur']==x['cur'] and (p['total']*p['dep']/100).quantize(D('0.01'))==x['amt']]
            if len(c)==1: po=c[0]
            else: reports['unresolved'].append(('deposit PO unmatched',m['url'],x['amt'],c)); 
        else:
            p=pos.get(po)
            if p and p['dep'] and (p['total']*p['dep']/100).quantize(D('0.01'))!=x['amt']: reports['mismatch'].append(('deposit amount != PI share',m['url'],po,x['amt']))
        pending.setdefault(code,[]).append(dict(po=po,m=m,named=bool(x['po'])))
    elif kind=='chat_ack':
        m=d['m']; q=pending.get(m['code'],[])
        q2=[z for z in q if z['m']['dt']<m['dt']]
        if not q2: continue
        z=q2[0]; q.remove(z)
        if not z['po']: reports['unresolved'].append(('ack for unmatched deposit',m['url'])); continue
        # intervening non-image messages from us?
        inter=[y for y in chat_msgs if y['code']==m['code'] and y['us'] and z['m']['dt']<y['dt']<m['dt'] and y['text']!='[图片]' ]
        conf='0.9' if not inter else '0.8'
        f=[]
        if advance_po(z['po'],'in_production',f):
            tx(di,conf,f,f"ack deposit {z['po']} ({'named' if z['named'] else 'by amount'}; deposit msg {z['m']['url']})")
            if inter: reports['lowconf'].append(('ack separated from deposit by other messages',m['url'],z['po']))
        else: reports['notes'].append(('ack did not advance status',m['url'],z['po'],PO(z['po'])['status']))
    elif kind=='chat_prodstart':
        m=d['m']; c=[q for q,p in pos.items() if p['sup']==m['code'] and p['status']=='confirmed' and any(z['po']==q for z in [])]
        reports['notes'].append(('production-started message, no status change needed',m['url']))
    elif kind=='chat_etd':
        m=d['m']; x=d['x']; po=x.get('po') or pi_to_po.get(x['pi'])
        p=PO(po)
        if p['status'] and RANK.index(p['status'])>=RANK.index('shipped'):
            reports['notes'].append(('ETD message after shipped; ignored',m['url'],po)); continue
        p['etd']=x['date'].isoformat()
        tx(di,x['conf'],[{"e":["po/number",po],"a":"po/etd","v":x['date'].isoformat()}],f"etd {po} via {x['how']}")
    elif kind=='chat_container':
        m=d['m']; c=d['x']['container']; po=ci_cont.get((m['code'],c))
        if not po: reports['unresolved'].append(('container message: no PO',m['url'],c)); continue
        s=find_ship(container=c)
        if not s:
            cands=[s for s in ships if po in s.get('pos',()) and not s.get('container') and not s.get('hbl')]
            if len(cands)==1: s=cands[0]
        if not s: reports['unresolved'].append(('container message: no shipment yet',m['url'],c,po)); continue
        if s.get('container')==c: continue
        s['container']=c
        tx(di,'0.9',[{"e":sref(s),"a":"shipment/container_no","v":c}],f"container {c} for {po}")
json.dump(dict(txs=txs,reports=reports),open('plan.json','w'),default=str,indent=1)
print(len(txs),'txs')
for k,v in reports.items(): print(k,len(v))
