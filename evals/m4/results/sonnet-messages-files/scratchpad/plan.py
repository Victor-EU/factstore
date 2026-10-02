import sys,re,collections,datetime as dt; sys.path.insert(0,'.')
from parse import *
from chatev import chat_events, q, PO, ST, ETD
from decimal import Decimal
MON={m:i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}
TZ={'CN':SH,'USNYC':NY,'USLAX':ZoneInfo('America/Los_Angeles')}
RANK={'draft':0,'sent':1,'confirmed':2,'in_production':3,'ready':4,'shipped':5,'received':6}
SRANK={'booked':1,'departed':2,'arrived':3,'delivered':4}
def pdate(s):
    d,m,y=s.split(); return dt.date(int(y),MON[m],int(d))
def inst(date,port):
    tz=SH if port.startswith('CN') else TZ[port]
    return dt.datetime(date.year,date.month,date.day,tzinfo=tz).isoformat()

# ---- store state
SH_BY_HBL={}; 
for e,h,v,c,o,d in q('''select s.e,h.v,v.v,c.v,o.v,d.v from "shipment/hbl" h join "shipment/vessel" v using(e) join "shipment/origin" o using(e) join "shipment/destination" d using(e) join (select e,e as _e from "shipment/hbl") s using(e) left join "shipment/container_no" c using(e)'''.replace('join (select e,e as _e from "shipment/hbl") s using(e)','join (select e from "shipment/hbl") s using(e)')):
    SH_BY_HBL[h]=dict(e=e,hbl=h,vessel=v,cont=c,origin=o,dest=d,pos=set(),status=None,lines={})
BYE={s['e']:s for s in SH_BY_HBL.values()}
for se,k,qty,ct,plk in q('''select sl.v,k.v,qq.v,cc.v,pk.v from "core/part_of" sl join "shipment_line/key" k on k.e=sl.e join "shipment_line/quantity" qq on qq.e=sl.e join "shipment_line/cartons" cc on cc.e=sl.e join "shipment_line/po_line" l on l.e=sl.e join "po_line/key" pk on pk.e=l.v'''):
    s=BYE[se]; s['pos'].add(plk.rsplit('/',1)[0]); s['lines'][k]=(qty,ct)
ITEM={}  # (po, item suffix) -> po_line key
for plk,code in q('''select pk.v, fc.v from "po_line/key" pk join "po_line/sku" ps on ps.e=pk.e join "factory/item_code" fc on fc.e=ps.v'''):
    ITEM[(plk.rsplit('/',1)[0],code.split(':',1)[1])]=plk
HS={}
SHIP_BY_PO=collections.defaultdict(set)
for s in BYE.values():
    for p in s['pos']: SHIP_BY_PO[p].add(s['hbl'])
anom=[]
def A(*a): anom.append(' '.join(str(x) for x in a))

TX=[]  # dict(time, doc, conf, facts, note)
def tx(time,doc,conf,facts,note=''):
    TX.append(dict(time=time,doc=doc,conf=conf,facts=facts,note=note))

# per-PO / shipment sim state
po_status=dict(ST); po_sailed={}; hbl_state={h:dict(status=None) for h in SH_BY_HBL}
booking2hbl={}
dep_date={}  # hbl -> ATD date
delivered=set()
def ship_ref(hbl): return ['shipment/hbl',hbl]

def find_shipment_for_booking(vessel,pos):
    c=[s for s in SH_BY_HBL.values() if s['vessel']==vessel and s['pos']&pos]
    return c
def po_status_fact(po,new,facts):
    if RANK[new]>RANK[po_status[po]]:
        facts.append({'e':['po/number',po],'a':'po/status','v':new}); po_status[po]=new

def ev_email(m):
    s=m['subject']; t=m['text']; d=m['date']; doc=(m['hash'],m['url'])
    f=[]
    kind=s.split(' - ')[0]
    if kind.startswith('Receipt complete'): kind='Receipt complete'
    if kind=='Booking Confirmation':
        g=lambda k: re.search(k+r': (.+)',t).group(1).strip()
        so=g('SO'); eq=g('Equipment'); mode='LCL' if eq.startswith('LCL') else re.search(r'(20GP|40HQ)',eq).group(1)
        vessel=g('Vessel/Voyage'); mm=re.search(r'POL: .*\((\w+)\)\s+POD: .*\((\w+)\)',t); pol,pod=mm.groups()
        etd=pdate(g('ETD')); eta=pdate(g('ETA')); pos=set(); loose=False
        for tok in re.findall(r'(?i)PO[#-]?\s*[\d-]+',g('POs')):
            full=re.fullmatch(r'PO[#-]?(\d{4})-(\d{4})',tok.replace(' ',''))
            if full and tok.startswith('PO-'): pos.add(tok.replace(' ',''))
            elif full: pos.add('PO-%s-%s'%full.groups())
            else:
                n=int(re.sub(r'\D','',tok)); c=[p for p in PO if int(p[-4:])==n]; loose=True
                if len(c)==1: pos.add(c[0])
                else: A('ambiguous loose PO',tok,c)
        cands=find_shipment_for_booking(vessel,pos)
        if not cands and pos and all(not SHIP_BY_PO[p] for p in pos):
            key='SO:'+so; SH_BY_HBL[key]=dict(e=None,hbl=key,vessel=vessel,cont=None,origin=pol,dest=pod,pos=set(),status=None,lines={},new=True)
            hbl_state[key]=dict(status=None); cands=[SH_BY_HBL[key]]; A('NEW shipment created from booking (no CI/PL/HBL yet)',so,pos)
        if len(cands)!=1: A('BOOKING no unique shipment',so,vessel,pos,[c['hbl'] for c in cands]); return
        sh=cands[0]
        if sh['origin']!=pol or sh['dest']!=pod: A('booking port mismatch',so,sh['hbl'],pol,pod,sh['origin'],sh['dest'])
        if not sh.get('new') and not sh['pos']>=pos: A('booking PO not in shipment lines',so,pos,sh['pos'])
        booking2hbl[so]=sh['hbl']; ref=['shipment/booking_no',so] if sh.get('new') else ship_ref(sh['hbl']); st=hbl_state[sh['hbl']]
        f+= [{'e':ref,'a':'shipment/booking_no','v':so},{'e':ref,'a':'shipment/mode','v':mode},
             {'e':ref,'a':'shipment/vessel','v':vessel},{'e':ref,'a':'shipment/origin','v':pol},{'e':ref,'a':'shipment/destination','v':pod},
             {'e':ref,'a':'shipment/etd','v':inst(etd,pol)},{'e':ref,'a':'shipment/eta','v':inst(eta,pod)}]
        if st['status'] is None: f.append({'e':ref,'a':'shipment/status','v':'booked'}); st['status']='booked'
        else: A('booking after status',st['status'],so,d)
        st['booked_at']=d
        tx(d,doc,'0.9' if loose else '1',f,'booking '+so+(' LOOSEPO '+g('POs') if loose else ''))
    elif kind=='RE: Booking Confirmation':
        so=re.search(r'SO (\w+)',s).group(1); mm=re.search(r'New ETD (\d+ \w+ \d+), ETA (\d+ \w+ \d+)',t)
        hbl=booking2hbl.get(so)
        if not hbl: A('rolled booking unknown',so); return
        sh=SH_BY_HBL[hbl]; ref=['shipment/booking_no',so]
        if hbl_state[hbl]['status'] not in ('booked',None): A('roll after',hbl_state[hbl]['status'],so)
        f+=[{'e':ref,'a':'shipment/etd','v':inst(pdate(mm.group(1)),sh['origin'])},{'e':ref,'a':'shipment/eta','v':inst(pdate(mm.group(2)),sh['dest'])}]
        tx(d,doc,'1',f,'roll '+so)
    elif kind=='Shipping Advice / Pre-alert':
        g=lambda k: re.search(k+r': (.+)',t).group(1).strip()
        hbl=g('HBL'); sh=SH_BY_HBL.get(hbl)
        if not sh: A('prealert unknown hbl',hbl); return
        cs=g('Container/Seal').split(' / ')[0]; vessel=g('Vessel/Voyage')
        atd=pdate(re.search(r'ATD \w+: (.+)',t).group(1)); eta=pdate(re.search(r'ETA [^:]+: (.+)',t).group(1))
        if vessel!=sh['vessel']: A('prealert vessel mismatch',hbl,vessel,sh['vessel'])
        if cs=='LCL':
            if sh['cont']: A('prealert LCL but store has container',hbl,sh['cont'])
        elif sh['cont'] and sh['cont']!=cs: A('prealert container mismatch',hbl,cs,sh['cont'])
        ref=ship_ref(hbl); st=hbl_state[hbl]
        f=[]
        if cs!='LCL': f.append({'e':ref,'a':'shipment/container_no','v':cs})
        f+=[{'e':ref,'a':'shipment/etd','v':inst(atd,sh['origin'])},{'e':ref,'a':'shipment/eta','v':inst(eta,sh['dest'])}]
        if SRANK.get(st['status'],0)<SRANK['departed']: f.append({'e':ref,'a':'shipment/status','v':'departed'}); st['status']='departed'
        else: A('prealert after',st['status'],hbl)
        # lines
        for mm in re.finditer(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',t,re.M):
            po,item,ct,pc=mm.groups(); plk=ITEM.get((po,item))
            if not plk: A('prealert line no po_line',hbl,po,item); continue
            key=f'{hbl}/{plk}'; old=sh['lines'].get(key)
            if old is None:
                A('prealert line NOT in store (would create)',key,pc,ct)
                f+=[{'e':['shipment_line/key',key],'a':'core/part_of','v':ref},{'e':['shipment_line/key',key],'a':'shipment_line/po_line','v':['po_line/key',plk]},
                    {'e':['shipment_line/key',key],'a':'shipment_line/quantity','v':pc},{'e':['shipment_line/key',key],'a':'shipment_line/cartons','v':ct}]
            elif (old[0],old[1])!=(Decimal(pc),Decimal(ct)): A('prealert line DIFF',key,'store',old,'pre-alert',pc,ct)
            sh['_seen']=sh.get('_seen',set())|{key}
        missing=set(sh['lines'])-sh.get('_seen',set())
        if missing: A('store lines not in prealert',hbl,missing)
        dep_date[hbl]=(atd,d)
        tx(d,doc,'1',f,'prealert '+hbl)
        # PO shipped?
        for po in sorted(sh['pos']):
            if all(h in dep_date for h in SHIP_BY_PO[po]):
                last=max(dep_date[h][0] for h in SHIP_BY_PO[po])
                ff=[{'e':['po/number',po],'a':'po/etd','v':last.isoformat()}]
                po_status_fact(po,'shipped',ff); po_sailed[po]=last
                tx(d,doc,'1',ff,'po shipped '+po)
    elif kind in('ETA update','Arrival Notice'):
        hbl=re.search(r'HBL (\w+)',s).group(1); sh=SH_BY_HBL.get(hbl)
        if not sh: A('unknown hbl',s); return
        ref=ship_ref(hbl); st=hbl_state[hbl]
        if kind=='ETA update':
            dte=pdate(re.search(r'ETA (\d+ \w+ \d+)',t).group(1)); f=[{'e':ref,'a':'shipment/eta','v':inst(dte,sh['dest'])}]
        else:
            mm=re.search(r'arriving (.+?) on (\d+ \w+ \d+)',t); dte=pdate(mm.group(2))
            if ('Los Angeles' in mm.group(1))!=(sh['dest']=='USLAX'): A('arrival port differs',hbl,mm.group(1),sh['dest'])
            f=[{'e':ref,'a':'shipment/eta','v':inst(dte,sh['dest'])}]
            if SRANK.get(st['status'],0)<SRANK['arrived']: f.append({'e':ref,'a':'shipment/status','v':'arrived'}); st['status']='arrived'
            else: A('arrival after',st['status'],hbl)
        if st['status'] is None: A('eta/arrival before any booking/prealert',hbl)
        tx(d,doc,'1',f,kind+' '+hbl)
    elif kind=='Receipt complete':
        key=s.split(' - ')[1]; sh=SH_BY_HBL.get(key) or next((x for x in SH_BY_HBL.values() if x['cont']==key),None)
        if not sh: A('receipt unknown',s); return
        hbl=sh['hbl']; st=hbl_state[hbl]
        if re.search(r'\d{1,2}:\d\d',t): A('receipt body has time?',s)
        f=[{'e':ship_ref(hbl),'a':'shipment/delivered_at','v':d.isoformat()}]
        if SRANK.get(st['status'],0)<SRANK['delivered']: f.append({'e':ship_ref(hbl),'a':'shipment/status','v':'delivered'}); st['status']='delivered'
        delivered.add(hbl)
        for ln in re.findall(r'expected (\d+), received (\d+), damaged (\d+)',t):
            if ln[0]!=ln[1] or ln[2]!='0': pass
        disc=re.findall(r'^\s+(\S+) \((\S+)\): expected (\d+), received (\d+), damaged (\d+)',t,re.M)
        DISC.append((hbl,m['url'],[x for x in disc if x[2]!=x[3] or x[4]!='0']))
        tx(d,doc,'1',f,'receipt '+hbl)
        for po in sorted(sh['pos']):
            if all(h in delivered for h in SHIP_BY_PO[po]):
                ff=[]; po_status_fact(po,'received',ff)
                if ff: tx(d,doc,'1',ff,'po received '+po)
    elif kind.startswith('Entry Summary'):
        en=s.split()[2]; ident=s.split(' - ')[1]
        sh=SH_BY_HBL.get(ident) or next((x for x in SH_BY_HBL.values() if x['cont']==ident),None)
        if not sh: A('entry unknown shipment',s); return
        v=lambda k: Decimal(re.search(k+r': USD ([\d,]+\.\d\d)',t).group(1).replace(',',''))
        val=v('Entered value'); duty=v(r'Duty \(HTS\)')+v('Section 301')+v('Additional duties'); fees=v('MPF')+v('HMF')
        tot=v('Total duties and fees')
        if duty+fees!=tot: A('entry total mismatch',en,duty,fees,tot)
        if re.search(r'Entry (\S+) filed for (\S+)\.',t).group(1)!=en: A('entry no mismatch',en)
        r=['customs/entry_no',en]
        f=[{'e':r,'a':'customs/shipment','v':ship_ref(sh['hbl'])},{'e':r,'a':'customs/filed_on','v':d.date().isoformat()},
           {'e':r,'a':'customs/entered_value','v':str(val)},{'e':r,'a':'customs/duty','v':str(duty)},{'e':r,'a':'customs/fees','v':str(fees)},{'e':r,'a':'core/currency','v':'USD'}]
        tx(d,doc,'1',f,'entry '+en)
    else: A('UNHANDLED',s)
DISC=[]

def build():
    items=[]
    for m in emails(): items.append((m['date'],0,m))
    for c,k,po,v,how in chat_events(): items.append((c['date'],1,(c,k,po,v,how)))
    items.sort(key=lambda x:(x[0].astimezone(dt.timezone.utc),x[1]))
    for d,kind,x in items:
        if kind==0: ev_email(x)
        else:
            c,k,po,v,how=x; doc=(c['hash'],c['url'])
            if k=='etd':
                if po is None: A('chat etd no PO',c['url']); continue
                if po in po_sailed: A('chat slip after sailed — skipped',c['url'],po,v); continue
                if ETD.get(po)==v: continue
                ETD[po]=v
                tx(d,doc,'0.9',[{'e':['po/number',po],'a':'po/etd','v':v.isoformat()}],'slip '+po+' '+how)
            elif k in('ack','prod'):
                if po and po_status.get(po) in('draft','sent','confirmed'):
                    ff=[]; po_status_fact(po,'in_production',ff); tx(d,doc,'0.8',ff,'in_production '+po+' '+c['text'])
            elif k=='cont':
                if v not in {s['cont'] for s in SH_BY_HBL.values()}: A('chat container not in store',c['url'],v)
    return TX
if __name__=='__main__':
    T=build()
    for t in T: print(t['time'].strftime('%Y-%m-%d %H:%M'),t['conf'],t['note'],'|',len(t['facts']))
    print('\nANOMALIES'); [print(a) for a in anom]
    print(len(T)); print([d for d in DISC if d[2]][:50])
