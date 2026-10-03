import json,re,collections
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
import factstore
CN=ZoneInfo('Asia/Shanghai'); NY=ZoneInfo('America/New_York'); LA=ZoneInfo('America/Los_Angeles')
D=json.load(open('docs.json'))
RANK={s:i for i,s in enumerate(['draft','sent','confirmed','in_production','ready','shipped','received'])}
report=collections.defaultdict(list)
TX=[]
def tx(doc,conf,facts):
    if not facts: return
    TX.append(dict(doc=dict(hash=doc['hash'],url=doc['url'],issued=doc['issued']),conf=conf,facts=facts,kind=doc['kind']))
def L_(a,v): return [a,v]
def po_(p): return ['po/number',p]
def pol_(k): return ['po_line/key',k]
def sup_(c): return ['supplier/code',c]
def sku_(code,item): return ['factory/item_code',f'{code}:{item}']
def F(e,a,v): return dict(e=e,a=a,v=v)
def norm_po(s):
    s=s.strip()
    m=re.search(r'(\d{4})-(\d{4})$',s)
    if m: return f'PO-{m.group(1)}-{m.group(2)}'
    m=re.search(r'(\d+)$',s); n=int(m.group(1))
    return f'PO-2025-{n:04d}' if n>=100 else f'PO-2026-{n:04d}'
def tzport(code_or_name):
    return LA if ('USLAX' in code_or_name or 'Los Angeles' in code_or_name) else NY
def at_local(dstr,tz):
    d=datetime.strptime(dstr,'%d %b %Y'); return d.replace(tzinfo=tz).isoformat()
# ---------- static PI info
pis=[d for d in D if d['kind']=='pi']
po_lines={}   # po -> list of (n,item,qty,price)
pi2po={}; po_sup={}; po_total={}
for p in pis:
    d=p['d']; po_lines[d['po']]=[(i+1,r['item'],float(r['qty'])) for i,r in enumerate(d['rows'])]
    pi2po[d['pi_no']]=d['po']; po_sup[d['po']]=d['code']; po_total[d['po']]=sum(float(r['amt']) for r in d['rows'])
    po_pct={}
pct={}
for p in pis:
    m=re.search(r'(\d+)% deposit',p['d']['payment']); pct[p['d']['code']]=int(m.group(1)) if m else None
# existing SKU hs codes
hs_store={r[0]:r[1] for r in factstore.query('select i.v, h.v from "factory/item_code" i join "sku/hs_code" h using(e)').rows}
sku_codes=set(hs_store)
# ---------- state
po_status={}; po_etd_shipped={}
ships=[]   # dicts
def newship(**k):
    s=dict(booking=None,hbl=None,hbl_written=False,vessel=None,pos=set(),dest=None,origin=None,container=None,lines={},status=None,delivered=False,departed=False); s.update(k); ships.append(s); return s
def sref(s):
    return ['shipment/hbl',s['hbl']] if s['hbl_written'] else ['shipment/booking_no',s['booking']]
def find_ship(hbl=None,booking=None,vessel=None,pos=()):
    for s in ships:
        if hbl and s['hbl']==hbl: return s
    for s in ships:
        if booking and s['booking']==booking: return s
    c=[s for s in ships if vessel and s['vessel']==vessel and not s['hbl'] and (s['pos'] & set(pos))]
    if len(c)==1: return c[0]
    if len(c)>1: report['ambiguous_ship'].append((hbl,vessel,sorted(pos)))
    return None
def status_fact(po,new,facts):
    if RANK[new]>RANK.get(po_status.get(po),-1):
        po_status[po]=new; facts.append(F(po_(po),'po/status',new)); return True
    return False
def po_shipped_check(po,facts,doc,prealert_date=None):
    lines=po_lines.get(po)
    if not lines: return
    carrying=[s for s in ships if po in s['pos'] or any(k.startswith(po+'/') for k in s['lines'])]
    shipped_qty=collections.Counter()
    for s in ships:
        for k,q in s['lines'].items():
            if k.startswith(po+'/'): shipped_qty[k.rsplit('/',1)[0] if False else k[len(po)+1:]]+=0
    # per PO line quantity
    got=collections.Counter()
    for s in ships:
        for k,q in s['lines'].items():
            ph=k.split('|')[0]
            if ph.startswith(po+'/'): got[ph]+=q
    covered=all(got[f'{po}/{n}']>=q for n,_,q in lines)
    departed=bool(carrying) and all(s['departed'] for s in carrying)
    if covered or departed:
        status_fact(po,'shipped',facts)
        return True
    return False
# ---------- collect sorted events
order={'pi':0,'qc':1,'ci':2,'chat':3,'mail':4}
evs=sorted(D,key=lambda d:(datetime.fromisoformat(d['issued']),order[d['kind']],d['url']))
# dedupe by hash
seen=set(); E=[]
for d in evs:
    if d['hash'] in seen: continue
    seen.add(d['hash']); E.append(d)
ci_cont={}
for d in D:
    if d['kind']=='ci' and d['d']['container']!='LCL': ci_cont[d['d']['po']]=d['d']['container']
pending={}   # chat code -> (po,amt,matched)
def doc_(e): return e
def nextdate(m,dd,base):
    y=base.year
    try: c=date(y,m,dd)
    except ValueError: c=None
    if c is None or c<base: c=date(y+1,m,dd)
    return c
def chat_event(e):
    d=e['d']; txt=d['text']; code=d['code']; fromMaya=d['sender'].startswith('Maya')
    ts=datetime.fromisoformat(d['ts'])
    facts=[]; low=[]
    if fromMaya:
        m=re.search(r"(?:new PO|here's|PO) (PO-\d{4}-\d{4})",txt)
        if m and re.search(r'attached|here\'s|for \d+ items',txt):
            po=m.group(1)
            tx(e,'1',[F(po_(po),'po/placed_on',ts.date().isoformat()),F(po_(po),'po/supplier',sup_(code))])
            if po_sup.get(po) and po_sup[po]!=code: report['placed_supplier_mismatch'].append((po,code,po_sup[po]))
        if re.search(r'[Dd]eposit',txt):
            m=re.search(r'(PO-\d{4}-\d{4})',txt); am=re.search(r'(?:USD|CNY) ([\d,]+\.\d\d)',txt)
            amt=float(am.group(1).replace(',','')) if am else None
            if m: pending[code]=(m.group(1),amt,'named')
            else:
                c=[po for po,s in po_sup.items() if s==code and pct[code] and abs(po_total[po]*pct[code]/100-(amt or -1))<0.015]
                pending[code]=(c[0],amt,'amount') if len(c)==1 else (None,amt,'unmatched')
                if len(c)!=1: report['deposit_unmatched'].append((e['url'],amt,c))
        return
    # supplier messages
    if re.search(r'^(Received, thank you|收到，谢谢|定金收到了，马上安排生产)$',txt):
        p=pending.pop(code,None)
        if p and p[0]:
            f=[]
            if status_fact(p[0],'in_production',f):
                tx(e,'0.9' if p[2]=='named' else '0.8',f)
        else: report['ack_unmatched'].append(e['url'])
        return
    m=re.search(r'([A-Z]{4}\d{7})',txt)
    if m and re.search(r'loaded|已装柜',txt):
        cont=m.group(1); sp={po for po,sc in po_sup.items() if sc==code}
        c=[x for x in ships if (x['pos']&sp) and any(ci_cont.get(po)==cont for po in x['pos']&sp)]
        if len(c)==1 and c[0]['booking']:
            x=c[0]; x['container']=cont
            tx(e,'0.9',[F(sref(x),'shipment/container_no',cont)])
        else: report['container_msg_unresolved'].append((e['url'],cont,len(c)))
        return
    if txt=='大货生产中':
        c=[po for po,sc in po_sup.items() if sc==code and po_status.get(po)=='confirmed']
        if len(c)==1:
            f=[]; status_fact(c[0],'in_production',f); tx(e,'0.7',f)
        else: report['production_msg_unresolved'].append((e['url'],c))
        return
    # ETD slips
    km=re.search(r'(PO-\d{4}-\d{4})',txt) or next((re.search(re.escape(k),txt) for k in pi2po if k in txt),None)
    dm=re.search(r'(?:will be (\d+)/(\d+)|推迟到(\d+)月(\d+)号|预计(\d+)/(\d+)出货)',txt)
    if km and dm and re.search(r'will be|推迟到|大货要晚一点',txt):
        key=km.group(0)
        mm,dd=[int(x) for x in dm.groups() if x][:2]
        po=key if key.startswith('PO-') else pi2po.get(key)
        if not po: report['slip_unresolved'].append((e['url'],txt)); return
        base=ts.astimezone(CN).date()
        etd=nextdate(mm,dd,base)
        if RANK.get(po_status.get(po),-1)>=RANK['shipped']:
            report['slip_after_shipped'].append((e['url'],po,etd)); return
        tx(e,'0.8',[F(po_(po),'po/etd',etd.isoformat())])
        report['slips'].append((e['url'],po,str(etd)))
        return
    # PI-confirm ETD messages: validate only
    m=re.match(r'^(?:ETD(?: around)? (\d+)/(\d+)|交期(\d+)月(\d+)号左右.*)$',txt,re.S)
    if m:
        report['pi_etd_msgs'].append((e['url'],txt)); return
def parse_mail(e):
    d=e['d']; sub=d['subject']; body=d['body']; dt=datetime.fromisoformat(d['date'])
    if sub.startswith('RE: Booking Confirmation'):
        so=re.search(r'SO (\S+)',sub).group(1)
        m=re.search(r'New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})',body)
        s=find_ship(booking=so)
        if not s: report['roll_no_booking'].append(so); return
        s['etd']=m.group(1)
        tx(e,'1',[F(sref(s),'shipment/etd',at_local(m.group(1),CN)),F(sref(s),'shipment/eta',at_local(m.group(2),tzport(s['dest'] or 'USNYC')))])
    elif sub.startswith('Booking Confirmation'):
        so=re.search(r'SO: (\S+)',body).group(1)
        eq=re.search(r'Equipment: (.+)',body).group(1)
        mode='LCL' if 'LCL' in eq else re.search(r'x(\w+)',eq).group(1)
        vessel=re.search(r'Vessel/Voyage: (.+)',body).group(1).strip()
        pol=re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)',body)
        etd=re.search(r'ETD: (.+)',body).group(1).strip(); eta=re.search(r'ETA: (.+)',body).group(1).strip()
        pos={norm_po(x) for x in re.search(r'POs: (.+)',body).group(1).split(',')}
        if find_ship(booking=so): report['dup_booking'].append(so)
        s=newship(booking=so,vessel=vessel,pos=pos,origin=pol.group(1),dest=pol.group(2))
        tz=tzport(pol.group(2))
        tx(e,'1',[F(['shipment/booking_no',so],'shipment/mode',mode),F(['shipment/booking_no',so],'shipment/vessel',vessel),
                  F(['shipment/booking_no',so],'shipment/origin',pol.group(1)),F(['shipment/booking_no',so],'shipment/destination',pol.group(2)),
                  F(['shipment/booking_no',so],'shipment/etd',at_local(etd,CN)),F(['shipment/booking_no',so],'shipment/eta',at_local(eta,tz)),
                  F(['shipment/booking_no',so],'shipment/status','booked')])
        # loose PO names are resolved locally only (no facts)
    elif sub.startswith('Shipping Advice'):
        hbl=re.search(r'HBL: (\S+)',body).group(1)
        cont=re.search(r'Container/Seal: (\S+) /',body).group(1)
        vessel=re.search(r'Vessel/Voyage: (.+)',body).group(1).strip()
        atd=re.search(r'ATD \w+: (.+)',body); eta=re.search(r'ETA (.+?): (\d+ \w+ \d{4})',body)
        rows=re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',body,re.M)
        pos={r[0] for r in rows}
        s=find_ship(hbl=hbl,vessel=vessel,pos=pos)
        facts=[]
        if s is None:
            s=newship(hbl=hbl,hbl_written=True,vessel=vessel,pos=pos); report['prealert_no_booking'].append(hbl)
            ref=['shipment/hbl',hbl]
        else:
            if s['hbl'] and s['hbl']!=hbl: report['hbl_conflict'].append((hbl,s['hbl']))
            ref=sref(s)
            if not s['hbl']:
                facts.append(F(ref,'shipment/hbl',hbl)); s['hbl']=hbl; s['hbl_written']=True
        s['pos']|=pos
        if cont!='LCL':
            facts.append(F(ref,'shipment/container_no',cont)); s['container']=cont
        facts.append(F(ref,'shipment/etd',at_local(atd.group(1).strip(),CN)))
        tz=tzport(eta.group(1)); s['dest']=s['dest'] or ('USLAX' if tz==LA else 'USNYC')
        facts.append(F(ref,'shipment/eta',at_local(eta.group(2),tz)))
        facts.append(F(ref,'shipment/status','departed')); s['departed']=True; s['atd']=atd.group(1).strip()
        for po,item,ctns,pcs in rows:
            n=[n for n,i,q in po_lines[po] if i==item]
            if len(n)!=1: report['prealert_item_unresolved'].append((hbl,po,item)); continue
            plk=f'{po}/{n[0]}'; key=f'{hbl}/{plk}'
            if key in s['lines'] and (s['lines'][key]!=float(pcs)): report['line_conflict'].append((key,s['lines'][key],pcs))
            s['lines'][key]=float(pcs)
            lr=['shipment_line/key',key]
            facts+= [F(lr,'core/part_of',ref),F(lr,'shipment_line/po_line',pol_(plk)),F(lr,'shipment_line/quantity',pcs),F(lr,'shipment_line/cartons',ctns)]
        for po in pos:
            fx=[]
            before=po_status.get(po)
            if po_shipped_check(po,fx,e):
                # actual departure date as PO ETD
                fx.append(F(po_(po),'po/etd',datetime.strptime(s['atd'],'%d %b %Y').date().isoformat()))
                po_etd_shipped[po]=s['atd']
            facts+=fx
        tx(e,'1',facts)
    elif sub.startswith('ETA update'):
        hbl=re.search(r'HBL (\S+)',sub).group(1); m=re.search(r'revised ETA (\d+ \w+ \d{4})',body)
        s=find_ship(hbl=hbl)
        if not s: report['eta_no_ship'].append(hbl); return
        tx(e,'1',[F(sref(s),'shipment/eta',at_local(m.group(1),tzport(s['dest'] or 'USNYC')))])
    elif sub.startswith('Arrival Notice'):
        hbl=re.search(r'HBL (\S+)',sub).group(1); m=re.search(r'arriving (.+?) on (\d+ \w+ \d{4})',body)
        s=find_ship(hbl=hbl)
        if not s: report['arrival_no_ship'].append(hbl); return
        s['arrived']=True
        tx(e,'1',[F(sref(s),'shipment/status','arrived'),F(sref(s),'shipment/eta',at_local(m.group(2),tzport(m.group(1))))])
    elif sub.startswith('Entry Summary'):
        ent=re.search(r'Entry Summary (\S+)',sub).group(1)
        ident=re.search(r'filed for (\S+)\.',body).group(1)
        s=find_ship(hbl=ident) or next((x for x in reversed(ships) if x['container']==ident),None)
        amt=lambda k:float(re.search(k+r': USD ([\d,]+\.\d\d)',body).group(1).replace(',',''))
        duty=amt(r'Duty \(HTS\)')+amt('Section 301')+amt('Additional duties'); fees=amt('MPF')+amt('HMF')
        tot=amt('Total duties and fees')
        if abs(duty+fees-tot)>0.015: report['customs_total_mismatch'].append((ent,duty+fees,tot))
        if not s: report['customs_no_ship'].append((ent,ident)); return
        ref=['customs/entry_no',ent]
        tx(e,'1',[F(ref,'customs/shipment',sref(s)),F(ref,'customs/filed_on',e['d']['date'][:10]),F(ref,'customs/entered_value',f"{amt('Entered value'):.2f}"),
                  F(ref,'customs/duty',f'{duty:.2f}'),F(ref,'customs/fees',f'{fees:.2f}'),F(ref,'core/currency','USD')])
    elif sub.startswith('Receipt complete'):
        ident=sub.split(' - ')[-1].strip()
        c=[x for x in ships if x['container']==ident or x['hbl']==ident]
        c=[x for x in c if not x['delivered']] or c
        if len(c)!=1:
            # choose latest departed before
            report['delivery_ship_candidates'].append((ident,len(c)))
            if not c: return
        s=c[-1] if len(c)>1 else c[0]
        s['delivered']=True
        if 'Receiving complete' not in body: report['delivery_not_complete'].append(e['url'])
        facts=[F(sref(s),'shipment/status','delivered'),F(sref(s),'shipment/delivered_at',e['d']['date'])]
        pos={k.split('/')[1]+'/'+k.split('/')[2] for k in s['lines']}
        pos={ '/'.join(k.split('/')[1:3]) for k in s['lines']}
        pos={x.split('/')[0] for x in pos}
        for po in pos:
            carrying=[x for x in ships if any(k.split('/')[1]==po for k in x['lines'])]
            if all(x['delivered'] for x in carrying): status_fact(po,'received',facts)
        tx(e,'1',facts)
        disc=re.findall(r'expected (\d+), received (\d+), damaged (\d+)',body)
        report['warehouse_discrepancies'].append((e['url'],ident,disc))
def ci_event(e):
    d=e['d']; po=d['po']; hbl=d['hbl']
    s=find_ship(hbl=hbl,vessel=d['vessel'],pos={po})
    facts=[]
    if s is None:
        s=newship(hbl=hbl,hbl_written=True,vessel=d['vessel'],pos={po}); ref=['shipment/hbl',hbl]
    else:
        ref=sref(s)
        if not s['hbl']: facts.append(F(ref,'shipment/hbl',hbl)); s['hbl']=hbl; s['hbl_written']=True
    s['pos'].add(po)
    if d['container']!='LCL':
        if s['container'] and s['container']!=d['container']: report['container_conflict'].append((hbl,s['container'],d['container']))
        facts.append(F(ref,'shipment/container_no',d['container'])); s['container']=d['container']
    facts+=[F(ref,'shipment/vessel',d['vessel']),F(ref,'shipment/origin',d['origin']),F(ref,'shipment/destination',d['dest'])]
    if s['dest'] and s['dest']!=d['dest']: report['dest_conflict'].append((hbl,s['dest'],d['dest']))
    s['dest']=d['dest']; s['origin']=d['origin']
    s['departed']=True
    for r in d['rows']:
        n=[n for n,i,q in po_lines[po] if i==r['item']]
        assert len(n)==1,(e['url'],r)
        plk=f'{po}/{n[0]}'; key=f'{hbl}/{plk}'
        if key in s['lines'] and s['lines'][key]!=float(r['qty']): report['line_conflict'].append((key,s['lines'][key],r['qty']))
        s['lines'][key]=float(r['qty'])
        lr=['shipment_line/key',key]
        facts+=[F(lr,'core/part_of',ref),F(lr,'shipment_line/po_line',pol_(plk)),F(lr,'shipment_line/quantity',r['qty']),F(lr,'shipment_line/cartons',r['ctns'])]
        sk=f"{po_sup[po]}:{r['item']}"
        if hs_store.get(sk)!=r['hs']: report['hs_mismatch'].append((sk,hs_store.get(sk),r['hs'],e['url']))
    fx=[]
    po_shipped_check(po,fx,e)
    tx(e,'1',facts+fx)
def qc_event(e):
    d=e['d']; ref=['qc/report_no',d['no']]; po=d['po']
    f=[F(ref,'qc/po',po_(po)),F(ref,'qc/inspected_on',d['date']),F(ref,'qc/result',d['result']),F(ref,'qc/inspector',d['inspector']),F(ref,'qc/sample_size',d['sample'])]
    if d['result']=='PASS': status_fact(po,'ready',f)
    tx(e,'1',f)
def pi_event(e):
    d=e['d']; po=d['po']; f=[]
    f+=[F(po_(po),'po/pi_number',d['pi_no']),F(po_(po),'po/supplier',sup_(d['code'])),F(po_(po),'po/etd',d['etd']),F(po_(po),'core/currency',d['cur'])]
    status_fact(po,'confirmed',f)
    s=sup_(d['code'])
    f+=[F(s,'supplier/name_cn',d['name_cn']),F(s,'supplier/name',d['name']),F(s,'supplier/address',d['address']),F(s,'supplier/incoterm',d['incoterm']),
        F(s,'supplier/payment_terms',d['payment']),F(s,'supplier/currency',d['cur']),F(s,'supplier/port',d['port'])]
    for i,r in enumerate(d['rows'],1):
        k=pol_(f'{po}/{i}')
        sk=f"{d['code']}:{r['item']}"
        assert sk in sku_codes,(e['url'],sk)
        f+=[F(k,'core/part_of',po_(po)),F(k,'po_line/sku',sku_(d['code'],r['item'])),F(k,'po_line/quantity',r['qty']),F(k,'po_line/unit_price',r['price'])]
    tx(e,'1',f)
for e in E:
    {'pi':pi_event,'ci':ci_event,'qc':qc_event,'chat':chat_event,'mail':parse_mail}[e['kind']](e)
json.dump(TX,open('tx.json','w'),ensure_ascii=False)
json.dump({k:v for k,v in report.items()},open('report.json','w'),ensure_ascii=False,indent=1,default=str)
print(len(TX),collections.Counter(t['kind'] for t in TX))
for k,v in report.items(): print(k,len(v))

json.dump(dict(ships=[{k:(sorted(v) if isinstance(v,set) else v) for k,v in x.items() if k!='lines'} for x in ships],po_status=po_status,po_etd_shipped=po_etd_shipped,pos=sorted(po_lines)),open('state.json','w'),indent=0,default=str)
