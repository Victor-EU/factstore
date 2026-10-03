import sys,json,re,glob,os,collections
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from parse import *
import factstore
names=sorted(os.path.basename(f)[:-4] for f in glob.glob(S+'/txt/*.txt'))
PI=[parse_pi(n) for n in names if not n.startswith(('CI-PL','LCI'))]
CI=[parse_ci(n) for n in names if n.startswith('CI-PL')]
QC=[parse_qc(n) for n in names if n.startswith('LCI')]
CH=parse_chats(); EM=parse_emails()
REPORT=collections.defaultdict(list)
def rep(k,m): REPORT[k].append(m)

# --- store snapshot
q=lambda s: factstore.query(s).rows
store_items=dict(q('select v,e from "factory/item_code"'))
sku_code={e:v for e,v in q('select e,v from "sku/code"')}
sku_hs={v:h for v,h in q('select i.v,h.v from "factory/item_code" i join "sku/hs_code" h using(e)')}
store_docs={h:(e,u) for e,h,u in q('select h.e,h.v,u.v from "document/hash" h join "document/url" u using(e)')}
store_pos={v for e,v in q('select e,v from "po/number"')}
for d in PI+CI+QC:
    if d['hash'] in store_docs and store_docs[d['hash']][1]!=d['url']: rep('hash-url-mismatch',d['name'])

# --- documents ordered by issue
ALL=[]
for d in PI+CI+QC+EM+CH: ALL.append(d)
KP={'pi':0,'qc':1,'ci':2,'email':3,'chat':4}
for d in ALL: d['_t']=datetime.fromisoformat(d['issued'])
ALL.sort(key=lambda d:(d['_t'],KP[d['kind']],d.get('n',0)))

TXS=[];CREATED=set()
def tx(docs,conf,facts,note=''):
    if not facts: return
    f=[]
    for d in docs:
        if d['hash'] not in CREATED:
            CREATED.add(d['hash'])
            f.append({'e':['document/hash',d['hash']],'a':'document/url','v':d['url']})
            f.append({'e':['document/hash',d['hash']],'a':'document/issued_at','v':d['issued']})
    for d in docs: f.append({'e':'tmp:tx','a':'core/evidence','v':['document/hash',d['hash']]})
    f.append({'e':'tmp:tx','a':'core/confidence','v':str(conf)})
    TXS.append({'docs':[d['url'] for d in docs],'conf':str(conf),'facts':f+facts,'note':note,'at':docs[0]['issued']})
def F(e,a,v): return {'e':e,'a':a,'v':v}

# --- state
RANK={'draft':0,'sent':1,'confirmed':2,'in_production':3,'ready':4,'shipped':5,'received':6}
po_status={};po_sup={};po_pi={};po_lines={};po_etd={};po_info={}
po_ref=lambda p:['po/number',p]
def status(p,s,facts):
    if RANK[s]>RANK.get(po_status.get(p),-1):
        po_status[p]=s; facts.append(F(po_ref(p),'po/status',s)); return True
    return False
SHIP=[]   # shipments
def norm_po(s):
    out=[]
    for m in re.finditer(r'(?i)\bpo[#\- ]*(?:(20\d\d)-)?0*(\d+)',s):
        y,n=m.groups(); n=int(n)
        y=y or ('2025' if n>=143 else '2026')
        out.append(('PO-%s-%04d'%(y,n),bool(m.group(1))))
    return out
def sref(s): return ['shipment/booking_no',s['so']] if s.get('so') else ['shipment/hbl',s['hbl']]
def find_ship(hbl=None,so=None,vessel=None,pos=()):
    for s in SHIP:
        if hbl and s.get('hbl')==hbl: return s
        if so and s.get('so')==so: return s
    if vessel:
        for s in SHIP:
            if s.get('vessel')==vessel and set(pos)&(s['pos']|set(po for (po,_) in s['lines_by_po'])) : 
                if hbl and s.get('hbl') and s['hbl']!=hbl: continue
                if so and s.get('so') and s['so']!=so: continue
                return s
    return None
def new_ship(**k):
    s=dict(so=None,hbl=None,vessel=None,pos=set(),lines={},lines_by_po=set(),docs=False,cont=None,status=None,dest=None,origin=None,atd=None,delivered=False); s.update(k); SHIP.append(s); return s
def pl_for(po,item):
    code=po_sup.get(po)
    for l in po_lines.get(po,[]):
        if l['item']==item: return l
    return None
def inst(date_,code): return iso(day_at(date_,portz(code)))

def update_shipped(po,facts,etd_doc=None,atd=None):
    """assert shipped when all goods have sailed"""
    carrying=[s for s in SHIP if po in s['pos'] or any(p==po for p,_ in s['lines_by_po'])]
    qty_ok=bool(po_lines.get(po)) and all(
        sum(q for s in SHIP for (k,q) in s['lines'].items() if k==l['key'])>=int(l['qty']) for l in po_lines[po])
    book_ok=bool(carrying) and all(s['docs'] for s in carrying)
    if qty_ok!=book_ok: rep('shipped-rule-disagree',f'{po} qty_ok={qty_ok} booking_ok={book_ok}')
    return qty_ok or book_ok

def do_pi(d):
    po=d['po'];facts=[];s=['supplier/code',d['sup']]
    po_sup[po]=d['sup'];po_pi[d['pi']]=po;po_etd[po]=d['etd'];po_info[po]=d
    facts+= [F(po_ref(po),'po/pi_number',d['pi']),F(po_ref(po),'po/supplier',s),F(po_ref(po),'po/etd',d['etd']),F(po_ref(po),'core/currency',d['cur'])]
    status(po,'confirmed',facts)
    lines=[]
    for i,it in enumerate(d['items'],1):
        key=f'{po}/{i}'; code=f"{d['sup']}:{it['item']}"
        if code not in store_items: rep('unresolved-item',f'{d["name"]} {code}'); continue
        lines.append(dict(key=key,item=it['item'],qty=it['qty'],code=code))
        lk=['po_line/key',key]
        facts+=[F(lk,'core/part_of',po_ref(po)),F(lk,'po_line/sku',['factory/item_code',code]),F(lk,'po_line/quantity',it['qty']),F(lk,'po_line/unit_price',it['price'])]
    po_lines[po]=lines
    facts+=[F(s,'supplier/name_cn',d['name_cn']),F(s,'supplier/address',d['address']),F(s,'supplier/name',d['bene']),F(s,'supplier/incoterm',d['incoterm']),
            F(s,'supplier/payment_terms',d['terms']),F(s,'supplier/currency',d['cur']),F(s,'supplier/port',d['port'])]
    tx([d],1,facts)

def lines_for(d_po_rows,hbl_ref,po,item,cartons,qty,facts,docname):
    pl=pl_for(po,item)
    if not pl: rep('unresolved-shipline',f'{docname} {po} {item}'); return None
    k=f'{hbl_ref}/{pl["key"]}'
    lk=['shipment_line/key',k]
    facts+=[F(lk,'core/part_of',None),F(lk,'shipment_line/po_line',['po_line/key',pl['key']]),F(lk,'shipment_line/quantity',str(qty)),F(lk,'shipment_line/cartons',str(cartons))]
    return pl,lk

def do_ci(d):
    po=d['po']
    if po_pi.get(d['order_ref'].replace('CI-',''))!=po and po_pi.get(d['order_ref'])!=po: rep('ci-po-vs-pi',f'{d["name"]} order {po} inv {d["order_ref"]}')
    s=find_ship(hbl=d['hbl'],vessel=d['vessel'],pos=[po])
    created=False
    facts=[]
    if not s:
        s=new_ship(hbl=d['hbl'],vessel=d['vessel']); created=True
    elif not s.get('hbl'):
        s['hbl']=d['hbl']; facts.append(F(sref(s),'shipment/hbl',d['hbl']))
        rep('ci-merged-into-booking',f"{d['name']} -> {s['so']}")
    r=sref(s)
    s['vessel']=d['vessel'];s['origin']=d['origin'];s['dest']=d['dest'];s['docs']=True
    facts+=[F(r,'shipment/vessel',d['vessel']),F(r,'shipment/origin',d['origin']),F(r,'shipment/destination',d['dest'])]
    if d['cont']!='LCL': s['cont']=d['cont']; facts.append(F(r,'shipment/container_no',d['cont']))
    for row in d['rows']:
        got=lines_for(None,d['hbl'],po,row['item'],d['pl'][row['item']]['ctns'],row['qty'],facts,d['name'])
        if not got: continue
        pl,lk=got
        facts[[i for i,f in enumerate(facts) if f['e']==lk and f['a']=='core/part_of'][0]]['v']=r
        s['lines'][pl['key']]=int(row['qty']); s['lines_by_po'].add((po,pl['key']))
        code=f"{d['sup']}:{row['item']}"
        if sku_hs.get(code)!=row['hs']: rep('hs-differs',f"{d['name']} {code} CI {row['hs']} store {sku_hs.get(code)}")
        if pl['qty']!=row['qty']: rep('ci-qty-vs-po',f"{d['name']} {pl['key']} PO {pl['qty']} CI {row['qty']}")
    # lines keyed by HBL
    for f in facts:
        pass
    if update_shipped(po,facts) : status(po,'shipped',facts)
    tx([d],1,facts)

def do_qc(d):
    po=d['po'];facts=[]
    q_=['qc/report_no',d['report']]
    facts+=[F(q_,'qc/po',po_ref(po)),F(q_,'qc/inspected_on',d['date']),F(q_,'qc/result',d['result']),F(q_,'qc/inspector',d['inspector']),F(q_,'qc/sample_size',d['n'])]
    if d['result']=='PASS': status(po,'ready',facts)
    tx([d],1,facts)

def g(t,pat,flags=0):
    m=re.search(pat,t,flags); return m
def codeof(txt_,name):
    m=re.search(r'\((\w{5})\)',txt_.split(name)[0][-0:]) if False else None
def do_email(d):
    t=d['text'];sj=d['subj'];facts=[]
    if sj.startswith('Booking Confirmation'):
        so=g(t,r'SO: (\S+)').group(1);vessel=g(t,r'Vessel/Voyage: (.*)').group(1).strip()
        eq=g(t,r'Equipment: (.*)').group(1)
        mode='LCL' if eq.startswith('LCL') else re.search(r'1x(\w+)',eq).group(1)
        pol=g(t,r'POL: .*?\((\w{5})\)\s+POD: .*?\((\w{5})\)'); o,de=pol.groups()
        etd=dmy(g(t,r'ETD: (.*)').group(1).strip()); eta=dmy(g(t,r'ETA: (.*)').group(1).strip())
        pos=set(p for p,_ in norm_po(g(t,r'POs: (.*)').group(1)))
        s=find_ship(so=so,vessel=vessel,pos=pos)
        if s and s.get('so') and s['so']!=so: s=None
        if not s: s=new_ship(so=so,vessel=vessel,pos=pos)
        else:
            if not s.get('so'):
                s['so']=so; facts.append(F(['shipment/hbl',s['hbl']],'shipment/booking_no',so)); rep('booking-merged-into-ci-shipment',f'{so} -> {s["hbl"]}')
            s['pos']|=pos
        r=sref(s); s['dest']=de; s['origin']=o; s['vessel']=vessel
        facts+=[F(r,'shipment/mode',mode),F(r,'shipment/vessel',vessel),F(r,'shipment/origin',o),F(r,'shipment/destination',de),
                F(r,'shipment/etd',inst(etd,o)),F(r,'shipment/eta',inst(eta,de))]
        if s['status'] is None: s['status']='booked'; facts.append(F(r,'shipment/status','booked'))
        s['mode']=mode
        tx([d],1,facts)
    elif sj.startswith('RE: Booking Confirmation'):
        so=g(t,r'SO (\S+) due').group(1) if g(t,r'SO (\S+) due') else g(t,r'SO (PBL\w+)').group(1)
        etd=dmy(g(t,r'New ETD (\d+ \w+ \d{4})').group(1)); eta=dmy(g(t,r'ETA (\d+ \w+ \d{4})').group(1))
        s=find_ship(so=so)
        if not s: rep('unresolved','rolled booking '+so); return
        r=sref(s)
        tx([d],1,[F(r,'shipment/etd',inst(etd,s['origin'])),F(r,'shipment/eta',inst(eta,s['dest']))])
    elif sj.startswith('Shipping Advice'):
        hbl=g(t,r'HBL: (\S+)').group(1);cont=g(t,r'Container/Seal: (\S+)').group(1)
        vessel=g(t,r'Vessel/Voyage: (.*)').group(1).strip()
        m=g(t,r'ATD (\w+): (\d+ \w+ \d{4})'); atd=dmy(m.group(2))
        eta=dmy(g(t,r'ETA [^:]*: (\d+ \w+ \d{4})').group(1))
        rows=re.findall(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',t)
        pos={p for p,_,_,_ in rows}
        s=find_ship(hbl=hbl,vessel=vessel,pos=pos)
        if not s: s=new_ship(hbl=hbl,vessel=vessel); rep('prealert-no-booking',hbl)
        elif not s.get('hbl'): s['hbl']=hbl; facts.append(F(sref(s),'shipment/hbl',hbl)); rep('prealert-merged-into-booking',f'{hbl} -> {s["so"]}')
        r=sref(s)
        s['atd']=atd;s['docs']=True;s['status']='departed'
        o=s.get('origin') or 'CNYTN'; de=s.get('dest') or 'USNYC'
        facts+=[]
        if cont!='LCL': s['cont']=cont; facts.append(F(r,'shipment/container_no',cont))
        facts+=[F(r,'shipment/etd',inst(atd,o)),F(r,'shipment/eta',inst(eta,de)),F(r,'shipment/status','departed')]
        for po,item,ctns,pcs in rows:
            pl=pl_for(po,item)
            if not pl: rep('unresolved-shipline',f'{hbl} {po} {item}'); continue
            lk=['shipment_line/key',f'{hbl}/{pl["key"]}']
            facts+=[F(lk,'core/part_of',r),F(lk,'shipment_line/po_line',['po_line/key',pl['key']]),F(lk,'shipment_line/quantity',pcs),F(lk,'shipment_line/cartons',ctns)]
            old=s['lines'].get(pl['key'])
            if old is not None and old!=int(pcs): rep('ci-vs-prealert-qty',f'{hbl} {pl["key"]} CI {old} pre-alert {pcs}')
            if pl['qty']!=pcs and old is None: pass
            s['lines'][pl['key']]=int(pcs); s['lines_by_po'].add((po,pl['key']))
        for po in sorted(pos):
            if update_shipped(po,facts):
                status(po,'shipped',facts)
                latest=max(x['atd'] for x in SHIP if x['atd'] and any(p==po for p,_ in x['lines_by_po']))
                facts.append(F(po_ref(po),'po/etd',latest.isoformat())); po_etd[po]=latest.isoformat()
        tx([d],1,facts)
    elif sj.startswith('ETA update'):
        hbl=g(t,r'HBL (\S+)').group(1); eta=dmy(g(t,r'revised ETA (\d+ \w+ \d{4})').group(1))
        s=find_ship(hbl=hbl)
        if not s: rep('unresolved','eta update '+hbl); return
        tx([d],1,[F(sref(s),'shipment/eta',inst(eta,s['dest']))])
    elif sj.startswith('Arrival Notice'):
        hbl=g(t,r'HBL (\S+)').group(1); dd=dmy(g(t,r'arriving .*? on (\d+ \w+ \d{4})').group(1))
        s=find_ship(hbl=hbl)
        if not s: rep('unresolved','arrival '+hbl); return
        s['status']='arrived'
        tx([d],1,[F(sref(s),'shipment/status','arrived'),F(sref(s),'shipment/eta',inst(dd,s['dest']))])
    elif sj.startswith('Receipt complete'):
        key=g(t,r'Receiving complete for (\S+) under (\S+)'); k=key.group(1)
        cands=[s for s in SHIP if (s.get('cont')==k or s.get('hbl')==k) and not s['delivered']]
        cands=[s for s in cands if s['status'] in('arrived','departed')]
        if len(cands)!=1: rep('unresolved',f'receipt {k} candidates {[ (c.get("hbl"),c["status"]) for c in cands]}'); 
        if not cands: return
        s=cands[0]; s['delivered']=True; s['status']='delivered'
        facts=[F(sref(s),'shipment/status','delivered'),F(sref(s),'shipment/delivered_at',d['issued'])]
        dis=re.findall(r'(?m)^\s+(ACMH-\d+) .*expected (\d+), received (\d+), damaged (\d+)',t)
        for x in dis:
            if x[1]!=x[2] or x[3]!='0': rep('receipt-discrepancy',f'{key.group(2)} {k} {x[0]} expected {x[1]} received {x[2]} damaged {x[3]}')
        for po in sorted({p for p,_ in s['lines_by_po']}|s['pos']):
            carrying=[x for x in SHIP if po in x['pos'] or any(p==po for p,_ in x['lines_by_po'])]
            if all(x['delivered'] for x in carrying) and po_status.get(po)=='shipped': status(po,'received',facts)
        tx([d],1,facts)
    elif sj.startswith('Entry Summary'):
        en=g(t,r'Entry Summary (\S+) - (\S+)'); no,ref=en.groups()
        s=find_ship(hbl=ref) or next((x for x in SHIP if x.get('cont')==ref),None)
        if not s: rep('unresolved','entry '+no+' '+ref); return
        v=lambda lab: num(g(t,lab+r': USD ([\d,.]+)').group(1))
        duty=v(r'Duty \(HTS\)')+v('Section 301')+v('Additional duties'); fees=v('MPF')+v('HMF')
        tot=v('Total duties and fees')
        if duty+fees!=tot: rep('entry-total-mismatch',f'{no} {duty}+{fees} != {tot}')
        e_=['customs/entry_no',no]
        filed=datetime.fromisoformat(d['issued']).date().isoformat()
        tx([d],1,[F(e_,'customs/shipment',sref(s)),F(e_,'customs/filed_on',filed),F(e_,'customs/entered_value',str(v('Entered value'))),F(e_,'customs/duty',str(duty)),F(e_,'customs/fees',str(fees)),F(e_,'core/currency','USD')])
    else: rep('unhandled-email',sj)

ACKS={'Received, thank you','收到，谢谢','定金收到了，马上安排生产'}
pending={}; last_pay={}; last_maya={}; loaded=[]; chat_unhandled=collections.Counter()
def md_next(dt,mo,dd):
    base=dt.astimezone(SH).date()
    for y in (base.year,base.year+1):
        try: c=date(y,mo,dd)
        except ValueError: continue
        if c>=base: return c
def do_chat(d):
    t=d['text'];sup=d['sup']
    if t.startswith('[') and t.endswith(']'): return
    if d['maya']:
        m=g(t,r"(?:new PO|! PO|here's) (PO-\d{4}-\d{4})")
        if m and not re.search(r'QC failed|Balance|deposit',t):
            po=m.group(1); po_sup.setdefault(po,sup)
            tx([d],1,[F(po_ref(po),'po/placed_on',d['dt'].date().isoformat()),F(po_ref(po),'po/supplier',['supplier/code',sup])])
            last_maya[sup]=('po',d); return
        if re.search(r'[Dd]eposit',t):
            amt=num(g(t,r'(?:USD|CNY) ([\d,]+\.\d\d)').group(1)); named=g(t,r'(PO-\d{4}-\d{4})')
            cands=[p for p,s in po_sup.items() if s==sup and p in po_info and po_info[p]['dep'] and po_status.get(p) in('confirmed',)]
            hit=[p for p in cands if (po_info[p]['total']*po_info[p]['dep']/100).quantize(Decimal('0.01'))==amt]
            if named:
                po=named.group(1); how='named'
                pi=po_info.get(po)
                if not pi or (pi['total']*pi['dep']/100).quantize(Decimal('0.01'))!=amt: rep('deposit-amount-mismatch',f'{d["url"]} {po} {amt}')
            elif len(hit)==1: po=hit[0]; how='amount'
            else: rep('deposit-unresolved',f'{d["url"]} {amt} cands {cands} hit {hit}'); po=None; how=None
            pending[sup]=(d,po,how); last_pay[sup]='dep'; last_maya[sup]=('dep',d); return
        if re.search(r'Balance',t): last_pay[sup]='bal'
        if re.search(r'Balance|QC failed|Inspection passed|quote|catalogue|samples|Understood|Ok noted|Again|Sorry can you type|Ok noted|DHL',t): chat_unhandled['maya-other']+=1; last_maya[sup]=('other',d); return
        chat_unhandled['maya-misc:'+t[:30]]+=1; last_maya[sup]=('other',d); return
    # supplier
    m=g(t,r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)'); mode=None
    if m: po,mo,dd=m.group(1),int(m.group(2)),int(m.group(3)); conf=0.9
    else:
        m=g(t,r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号')
        if m: po,mo,dd=m.group(1),int(m.group(2)),int(m.group(3)); conf=0.9
        else:
            m=g(t,r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货')
            if m:
                po=po_pi.get(m.group(1)); mo,dd=int(m.group(2)),int(m.group(3)); conf=0.8
                if not po: rep('unresolved','slip PI '+m.group(1)); return
            else: po=None
    if po:
        if RANK.get(po_status.get(po),0)>=RANK['shipped']: rep('slip-after-shipped',f'{d["url"]} {po}'); return
        e=md_next(d['dt'],mo,dd).isoformat(); po_etd[po]=e
        tx([d],conf,[F(po_ref(po),'po/etd',e)],note=t); return
    if t in ACKS:
        p=pending.get(sup); lm=last_maya.get(sup)
        if p and last_pay.get(sup)=='dep' and p[1] and (d['_t']-p[0]['_t']).days<=10:
            dd_,po,how=p; facts=[]
            if status(po,'in_production',facts): tx([d,dd_],0.9 if how=='named' else 0.8,facts)
            pending.pop(sup)
        else: chat_unhandled['ack-no-deposit']+=1
        return
    m=g(t,r'container loaded: (\w+)')
    if m: loaded.append((sup,m.group(1),d['url'])); return
    chat_unhandled[re.sub(r'\d+','N',t)[:40]]+=1

for d in ALL:
    {'pi':do_pi,'ci':do_ci,'qc':do_qc,'email':do_email,'chat':do_chat}[d['kind']](d)

# post checks
conts={s['cont'] for s in SHIP if s.get('cont')}
for sup,c,u in loaded:
    if c not in conts: rep('chat-container-unknown',f'{u} {c}')
rep('chat-container-msgs-skipped',len(loaded))
json.dump(TXS,open(S+'/txs.json','w'),ensure_ascii=False,indent=0)
print('txs',len(TXS)); 
for k,v in REPORT.items(): print(k,len(v),v[:12])
print(chat_unhandled.most_common(40))
print(collections.Counter(po_status.values()))
