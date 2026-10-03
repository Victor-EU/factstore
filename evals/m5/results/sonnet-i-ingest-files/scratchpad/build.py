from parse import *
import factstore, collections, json, sys
from decimal import Decimal
from datetime import date

R=collections.defaultdict(list)   # report notes
def note(k,msg): R[k].append(msg)

# ---- reference data from store
q=factstore.query('select c.v code, h.v hs from "factory/item_code" c join "sku/hs_code" h using(e)')
SKU_HS={r[0]:r[1] for r in q.rows} if hasattr(q,'rows') else {}
SUP_OF_FILE={'HT':'SZHT','LX':'YWLX','MJ':'FSMJ','MT':'NBBW','QS':'NBQS','RF':'DGRF','TY':'HZTY','YD':'XMYD'}
SUP_OF_CHAT={'SZHT':'SZHT','YWLX':'YWLX','FSMJ':'FSMJ','NBBW':'NBBW','NBQS':'NBQS','DGRF':'DGRF','HZTY':'HZTY','XMYD':'XMYD'}
PORT={'Yantian':'CNYTN','Ningbo':'CNNGB','Xiamen':'CNXMN','Nansha':'CNNSA'}
PORT_TZ={'CNYTN':CN,'CNNGB':CN,'CNXMN':CN,'CNNSA':CN,'USNYC':ZoneInfo('America/New_York'),'USLAX':ZoneInfo('America/Los_Angeles')}
PORT_NAME={'New York/Newark':'USNYC','Los Angeles':'USLAX','Yantian':'CNYTN','Ningbo':'CNNGB','Xiamen':'CNXMN','Nansha':'CNNSA'}
PO_RANK={s:i for i,s in enumerate(['draft','sent','confirmed','in_production','ready','shipped','received'])}
SH_RANK={s:i for i,s in enumerate(['booked','departed','arrived','delivered'])}
CUR={'USD':'USD','RMB':'CNY'}

def iso(dt): return dt.isoformat()
def at_port(d,port):  # date -> instant 00:00 local at port
    return datetime(d.year,d.month,d.day,tzinfo=PORT_TZ[port]).isoformat()
def pdate(s): return datetime.strptime(s.strip(),'%d %b %Y').date()
def loose_po(s):
    s=s.strip()
    m=re.match(r'(?i)^PO[#\- ]*(\d{4})-(\d{4})$',s)
    if m: return f'PO-{m.group(1)}-{m.group(2)}',False
    m=re.match(r'(?i)^PO[#\- ]*(\d{1,4})$',s)
    if m:
        n=int(m.group(1)); return (f'PO-2025-{n:04d}' if n>=143 else f'PO-2026-{n:04d}'),True
    raise ValueError(s)

PO={}; SH=[]; TX=[]
SUPLAST={}   # supplier code -> last PI po
def po_(n):
    return PO.setdefault(n,dict(num=n,status=None,etd=None,lines={},sup=None,pi=None,placed=None,cur=None))
def polook(n): return ['po/number',n]
def stat_up(po,new):
    cur=po['status']
    if cur is None or PO_RANK[new]>PO_RANK[cur]:
        po['status']=new; return True
    return False
def shlook(s): return ['shipment/booking_no',s['booking']] if s['booking'] else ['shipment/hbl',s['hbl']]
def new_sh(**kw):
    s=dict(booking=None,hbl=None,container=None,vessel=None,pos=set(),departed=False,atd=None,status=None,lines={},delivered=False,mode=None)
    s.update(kw); SH.append(s); return s
def find_sh(hbl=None,booking=None,vessel=None,pos=()):
    for s in SH:
        if hbl and s['hbl']==hbl: return s
        if booking and s['booking']==booking: return s
    if vessel:
        c=[s for s in SH if s['hbl'] is None and s['vessel']==vessel and s['pos']&set(pos)]
        if len(c)==1: return c[0]
        if len(c)>1: note('ambiguous','vessel match >1 for %s %s'%(vessel,pos))
    return None
def tx(d,conf,facts,why=''):
    if not facts: return
    TX.append(dict(url=d['url'],hash=d['hash'],issued=iso(d['issued']),conf=conf,facts=facts,why=why,kind=d['kind']))

def shipped_check(po):
    ss=[s for s in SH if po['num'] in s['pos']]
    if ss and all(s['departed'] for s in ss): return True
    if po['lines']:
        tot=collections.Counter()
        for s in ss:
            for k,(pn,q,c) in s['lines'].items():
                if pn==po['num']: tot[k]+=q
        if all(tot[k[0]]>=k[1] for k in [(l['key'],l['qty']) for l in po['lines'].values()]): return True
    return False

def sh_status(s,new):
    cur=s['status']
    if cur is None or SH_RANK[new]>SH_RANK[cur]:
        s['status']=new; return True
    return False

docs.sort(key=lambda d:d['issued'])
CH=collections.defaultdict(lambda:dict(placed=[],dep_wait=None,loaded=set(),ready=[],deposited=[],prod=set()))
for d in docs:
    k=d['kind']
    base=lambda conf='1':[{'e':['document/hash',d['hash']],'a':'document/url','v':d['url']},
        {'e':['document/hash',d['hash']],'a':'document/issued_at','v':iso(d['issued'])}]
    # ======================= PI
    if k=='pi':
        sup=SUP_OF_FILE[re.match(r'[A-Z]+',d['file']).group(0)]
        po=po_(d['po']); po['sup']=sup; po['pi']=d['pi_no']
        cur=CUR[d['rows'][0]['cur']]; po['cur']=cur
        f=[]
        f+=[{'e':polook(po['num']),'a':'po/pi_number','v':d['pi_no']},
            {'e':polook(po['num']),'a':'po/supplier','v':['supplier/code',sup]},
            {'e':polook(po['num']),'a':'core/currency','v':cur}]
        etd=datetime.strptime(d['delivery'],'%b %d, %Y').date(); po['etd']=etd
        f.append({'e':polook(po['num']),'a':'po/etd','v':etd.isoformat()})
        if stat_up(po,'confirmed'): f.append({'e':polook(po['num']),'a':'po/status','v':'confirmed'})
        for i,r in enumerate(d['rows'],1):
            key=f"{po['num']}/{i}"; code=f"{sup}:{r['code']}"
            if code not in SKU_HS: note('unresolved',f"{d['file']}: item {code} has no SKU")
            po['lines'][r['code']]=dict(key=key,qty=r['qty'],price=r['price'])
            f+=[{'e':['po_line/key',key],'a':'core/part_of','v':polook(po['num'])},
                {'e':['po_line/key',key],'a':'po_line/sku','v':['factory/item_code',code]},
                {'e':['po_line/key',key],'a':'po_line/quantity','v':str(r['qty'])},
                {'e':['po_line/key',key],'a':'po_line/unit_price','v':r['price']}]
        S=['supplier/code',sup]
        port=PORT[re.search(r'FOB (\w+)',d['price_term']).group(1)]
        f+=[{'e':S,'a':'supplier/name','v':d['beneficiary']},{'e':S,'a':'supplier/name_cn','v':d['name_cn']},
            {'e':S,'a':'supplier/address','v':d['address']},{'e':S,'a':'supplier/incoterm','v':d['price_term']},
            {'e':S,'a':'supplier/payment_terms','v':d['payment']},{'e':S,'a':'supplier/currency','v':cur},
            {'e':S,'a':'supplier/port','v':port}]
        SUPLAST[sup]=po['num']
        tx(d,'1',base()+f,'PI')
    # ======================= QC
    elif k=='qc':
        po=po_(d['po']); f=[]
        Q=['qc/report_no',d['report_no']]
        f+=[{'e':Q,'a':'qc/po','v':polook(po['num'])},{'e':Q,'a':'qc/inspected_on','v':d['date']},
            {'e':Q,'a':'qc/result','v':d['result']},{'e':Q,'a':'qc/inspector','v':d['inspector'].title()},
            {'e':Q,'a':'qc/sample_size','v':str(d['sample'])}]
        if d['result']=='PASS' and stat_up(po,'ready'): f.append({'e':polook(po['num']),'a':'po/status','v':'ready'})
        tx(d,'1',base()+f,'QC')
    # ======================= CI
    elif k=='ci':
        po=po_(d['po']); f=[]
        s=find_sh(hbl=d['hbl'],vessel=d['vessel'],pos=[po['num']])
        if s is None:
            s=new_sh(hbl=d['hbl']); note('created_shipment',f"from CI {d['file']} hbl {d['hbl']}")
        s['hbl']=d['hbl']; s['pos'].add(po['num']); s['vessel']=d['vessel']
        L=shlook(s)
        f.append({'e':L,'a':'shipment/hbl','v':d['hbl']})
        if d['container']!='LCL':
            if s['container'] and s['container']!=d['container']: note('conflict',f"container {s['container']} (chat) vs {d['container']} (CI {d['file']})")
            s['container']=d['container']; f.append({'e':L,'a':'shipment/container_no','v':d['container']})
        elif s['container']: note('conflict',f"chat container {s['container']} but CI says LCL {d['file']}")
        f+=[{'e':L,'a':'shipment/vessel','v':d['vessel']},{'e':L,'a':'shipment/origin','v':d['origin']},{'e':L,'a':'shipment/destination','v':d['dest']}]
        sup=po['sup']
        for r in d['rows']:
            pl=po['lines'].get(r['code'])
            if not pl: note('unresolved',f"CI {d['file']}: item {r['code']} not on {po['num']}"); continue
            lk=f"{d['hbl']}/{pl['key']}"
            if r['qty']!=pl['qty']: note('qty_diff',f"CI {d['file']} {pl['key']} shipped {r['qty']} vs ordered {pl['qty']}")
            if r['price']!=pl['price']: note('price_diff',f"CI {d['file']} {pl['key']} {r['price']} vs PI {pl['price']}")
            s['lines'][lk]=(po['num'],r['qty'],r['ctns'])
            SL=['shipment_line/key',lk]
            f+=[{'e':SL,'a':'core/part_of','v':L},{'e':SL,'a':'shipment_line/po_line','v':['po_line/key',pl['key']]},
                {'e':SL,'a':'shipment_line/quantity','v':str(r['qty'])}]
            if r['ctns'] is not None: f.append({'e':SL,'a':'shipment_line/cartons','v':str(r['ctns'])})
            hs=SKU_HS.get(f"{sup}:{r['code']}")
            if hs and hs!=r['hs']: note('hs_diff',f"CI {d['file']} {sup}:{r['code']} invoice HS {r['hs']} vs SKU {hs}")
        s['departed']=True
        if shipped_check(po) and stat_up(po,'shipped'): f.append({'e':polook(po['num']),'a':'po/status','v':'shipped'})
        tx(d,'1',base()+f,'CI')
    # ======================= email
    elif k=='email':
        subj=d['subject']; b=d['body']
        if subj.startswith('Booking Confirmation') and 'ROLLED' not in subj:
            so=re.search(r'SO: (\S+)',b).group(1)
            eq=re.search(r'Equipment: (.*)',b).group(1)
            mode='LCL' if eq.startswith('LCL') else re.search(r'x(\d+(?:HQ|GP))',eq).group(1)
            ves=re.search(r'Vessel/Voyage: (.*)',b).group(1).strip()
            pol=re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)',b); o,dst=pol.groups()
            etd=pdate(re.search(r'ETD: (.*)',b).group(1)); eta=pdate(re.search(r'ETA: (.*)',b).group(1))
            pos=[]
            for t in re.search(r'POs: (.*)',b).group(1).split(','):
                n,lo=loose_po(t); pos.append(n)
                if lo: note('loose_po',f"booking {so}: '{t.strip()}' read as {n}")
            s=find_sh(booking=so)
            if s is None: s=new_sh(booking=so)
            s['pos']|=set(pos); s['vessel']=ves; s['mode']=mode
            L=shlook(s); f=[{'e':L,'a':'shipment/mode','v':mode},{'e':L,'a':'shipment/vessel','v':ves},
              {'e':L,'a':'shipment/origin','v':o},{'e':L,'a':'shipment/destination','v':dst},
              {'e':L,'a':'shipment/etd','v':at_port(etd,o)},{'e':L,'a':'shipment/eta','v':at_port(eta,dst)}]
            s['origin']=o; s['dest']=dst
            if sh_status(s,'booked'): f.append({'e':L,'a':'shipment/status','v':'booked'})
            tx(d,'1',base()+f,'booking')
        elif 'ROLLED' in subj:
            so=re.search(r'SO (\S+)',subj).group(1)
            m=re.search(r'New ETD (.*?), ETA (.*?)\.',b)
            s=find_sh(booking=so)
            if not s: note('unresolved',f'rolled booking {so} unknown'); continue
            if s['status'] in ('departed','arrived','delivered'): note('stale',f'rolled email {so} after departure')
            L=shlook(s)
            tx(d,'1',base()+[{'e':L,'a':'shipment/etd','v':at_port(pdate(m.group(1)),s['origin'])},
                             {'e':L,'a':'shipment/eta','v':at_port(pdate(m.group(2)),s['dest'])}],'rolled')
        elif subj.startswith('Shipping Advice'):
            hbl=re.search(r'HBL: (\S+)',b).group(1)
            cont=re.search(r'Container/Seal: (\S+)',b).group(1)
            ves=re.search(r'Vessel/Voyage: (.*)',b).group(1).strip()
            m=re.search(r'ATD (.+?): (.*)',b); ob=PORT_NAME[m.group(1)]; atd=pdate(m.group(2))
            m=re.search(r'ETA (.+?): (.*)',b); db=PORT_NAME[m.group(1)]; eta=pdate(m.group(2))
            rows=re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',b,re.M)
            pos={r[0] for r in rows}
            s=find_sh(hbl=hbl,vessel=ves,pos=pos)
            if s is None: s=new_sh(hbl=hbl); note('created_shipment',f'from pre-alert hbl {hbl}')
            if s['booking'] and s['hbl'] is None: note('merged',f"pre-alert {hbl} -> booking {s['booking']}")
            s['hbl']=hbl; s['pos']|=pos; s['vessel']=ves; s['departed']=True; s['atd']=atd; s['origin']=ob; s['dest']=db
            L=shlook(s)
            f=[{'e':L,'a':'shipment/hbl','v':hbl}]
            if cont!='LCL':
                if s['container'] and s['container']!=cont: note('conflict',f"container {s['container']} vs pre-alert {cont} {hbl}")
                s['container']=cont; f.append({'e':L,'a':'shipment/container_no','v':cont})
            f+=[{'e':L,'a':'shipment/vessel','v':ves},{'e':L,'a':'shipment/etd','v':at_port(atd,ob)},{'e':L,'a':'shipment/eta','v':at_port(eta,db)}]
            if sh_status(s,'departed'): f.append({'e':L,'a':'shipment/status','v':'departed'})
            for pn,code,ctns,pcs in rows:
                po=po_(pn); pl=po['lines'].get(code)
                if not pl: note('unresolved',f'pre-alert {hbl}: {pn} item {code} not on PO'); continue
                lk=f"{hbl}/{pl['key']}"
                prev=s['lines'].get(lk)
                if prev and (prev[1]!=int(pcs) or prev[2]!=int(ctns)): note('conflict',f'{lk}: CI {prev[1:]} vs pre-alert {(int(pcs),int(ctns))}')
                s['lines'][lk]=(pn,int(pcs),int(ctns))
                SL=['shipment_line/key',lk]
                f+=[{'e':SL,'a':'core/part_of','v':L},{'e':SL,'a':'shipment_line/po_line','v':['po_line/key',pl['key']]},
                    {'e':SL,'a':'shipment_line/quantity','v':pcs},{'e':SL,'a':'shipment_line/cartons','v':ctns}]
            for pn in sorted(pos):
                po=po_(pn)
                if shipped_check(po):
                    if stat_up(po,'shipped'): f.append({'e':polook(pn),'a':'po/status','v':'shipped'})
                    if po['status']=='shipped':
                        last=max(x['atd'] for x in SH if pn in x['pos'] and x['atd'])
                        if po['etd']!=last: po['etd']=last; f.append({'e':polook(pn),'a':'po/etd','v':last.isoformat()})
            tx(d,'1',base()+f,'prealert')
        elif subj.startswith('ETA update'):
            hbl=re.search(r'HBL (\S+)',subj).group(1)
            eta=pdate(re.search(r'revised ETA (\d+ \w+ \d{4})',b).group(1))
            s=find_sh(hbl=hbl)
            if not s: note('unresolved',f'ETA update for unknown {hbl}'); continue
            tx(d,'1',base()+[{'e':shlook(s),'a':'shipment/eta','v':at_port(eta,s['dest'])}],'eta')
        elif subj.startswith('Arrival Notice'):
            hbl=re.search(r'HBL (\S+)',subj).group(1)
            m=re.search(r'arriving (.+?) on (\d+ \w+ \d{4})',b)
            s=find_sh(hbl=hbl)
            if not s: note('unresolved',f'arrival for unknown {hbl}'); continue
            dst=PORT_NAME[m.group(1)]
            if dst!=s['dest']: note('conflict',f'arrival port {dst} vs {s["dest"]} {hbl}')
            L=shlook(s); f=[]
            if sh_status(s,'arrived'): f.append({'e':L,'a':'shipment/status','v':'arrived'})
            f.append({'e':L,'a':'shipment/eta','v':at_port(pdate(m.group(2)),dst)})
            tx(d,'1',base()+f,'arrival')
        elif subj.startswith('Receipt complete'):
            tokm=re.match(r'Receipt complete (\S+) - (\S+)',subj); rc,tok=tokm.groups()
            if tok.startswith('PBLHB'): c=[s for s in SH if s['hbl']==tok]
            else: c=[s for s in SH if s['container']==tok]
            if len(c)!=1: note('unresolved',f'receipt {rc} {tok}: {len(c)} shipments'); 
            if not c: continue
            if len(c)>1:
                c=[s for s in c if s['status']=='arrived'] or c
                c=c[-1:]
            s=c[0]; L=shlook(s); f=[]
            if sh_status(s,'delivered'): f.append({'e':L,'a':'shipment/status','v':'delivered'})
            s['delivered']=True
            f.append({'e':L,'a':'shipment/delivered_at','v':iso(d['issued'])})
            for pn in sorted(s['pos']):
                po=po_(pn)
                if all(x['delivered'] for x in SH if pn in x['pos']):
                    if stat_up(po,'received'): f.append({'e':polook(pn),'a':'po/status','v':'received'})
            if 'No discrepancies' not in b: note('discrepancy',f"{rc} {tok}: "+'; '.join(l.strip() for l in b.split('\n') if 'expected' in l))
            tx(d,'1',base()+f,'receipt')
        elif subj.startswith('Entry Summary'):
            m=re.match(r'Entry Summary (\S+) - (\S+)',subj); en,tok=m.groups()
            if tok.startswith('PBLHB'): c=[s for s in SH if s['hbl']==tok]
            else: c=[s for s in SH if s['container']==tok]
            if len(c)!=1: note('unresolved',f'entry {en} {tok}: {len(c)} shipments')
            if not c: continue
            s=c[-1]
            g=lambda lab:Decimal(num(re.search(lab+r': USD ([\d,.]+)',b).group(1)))
            ev=g('Entered value'); duty=g(r'Duty \(HTS\)')+g('Section 301')+g('Additional duties'); fees=g('MPF')+g('HMF')
            tot=g('Total duties and fees')
            if duty+fees!=tot: note('conflict',f'entry {en}: duty+fees {duty+fees} vs total {tot}')
            C=['customs/entry_no',en]
            tx(d,'1',base()+[{'e':C,'a':'customs/shipment','v':shlook(s)},{'e':C,'a':'customs/filed_on','v':d['issued'].date().isoformat()},
              {'e':C,'a':'customs/entered_value','v':str(ev)},{'e':C,'a':'customs/duty','v':str(duty)},{'e':C,'a':'customs/fees','v':str(fees)},
              {'e':C,'a':'core/currency','v':'USD'}],'customs')
        else: note('unhandled_email',subj)
    # ======================= chat
    elif k=='chat':
        sup=SUP_OF_CHAT[d['sup'][:4]]; st=CH[sup]; t=d['text'].strip(); mine=d['sender'].startswith('Maya')
        cn=d['issued'].astimezone(CN).date()
        def md(mm,dd):
            y=cn.year; dt=date(y,mm,dd)
            return dt if dt>=cn else date(y+1,mm,dd)
        m=(re.search(r'new PO (PO-\d{4}-\d{4}) attached',t) or re.search(r'PO (PO-\d{4}-\d{4}) for \d+ items',t) or re.search(r"here's (PO-\d{4}-\d{4})",t)) if mine else None
        if m:
            pn=m.group(1); po=po_(pn); po['sup']=sup; po['placed']=d['issued'].date()
            st['placed'].append(pn)
            tx(d,'1',base()+[{'e':polook(pn),'a':'po/placed_on','v':d['issued'].date().isoformat()},
                             {'e':polook(pn),'a':'po/supplier','v':['supplier/code',sup]}],'po placed'); continue
        if mine and 'deposit' in t.lower():
            m=re.search(r'deposit for (PO-\d{4}-\d{4})',t)
            if m: pn=m.group(1)
            else:
                c=[p for p in st['placed'] if p not in st['deposited']]
                pn=c[0] if c else None
                if len(c)!=1: note('ambiguous',f"{d['url']} deposit PO inferred from {c}")
            if pn: st['deposited'].append(pn); st['dep_wait']=pn
            continue
        if not mine and re.search(r'定金收到了|^Received, thank you|^收到，谢谢',t) and st['dep_wait']:
            pn=st['dep_wait']; st['dep_wait']=None; po=po_(pn)
            if stat_up(po,'in_production'): tx(d,'0.9',base()+[{'e':polook(pn),'a':'po/status','v':'in_production'}],'deposit ack, PO inferred from preceding deposit message')
            continue
        if not mine and t=='大货生产中':
            c=[p for p in st['deposited'] if po_(p)['status'] in ('confirmed','in_production')]
            if len(c)==1:
                po=po_(c[0])
                if stat_up(po,'in_production'): tx(d,'0.8',base()+[{'e':polook(c[0]),'a':'po/status','v':'in_production'}],'production started, PO inferred')
            else: note('ambiguous',f"{d['url']} 大货生产中 candidates {c}")
            continue
        m=re.search(r'(?:QC passed for|Balance paid for) (PO-\d{4}-\d{4})',t) if mine else None
        if m: st['ready'].append(m.group(1)); continue
        # ETD change
        pn=None; conf='0.9'; dd=None
        m=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',t)
        if m: pn=m.group(1); dd=md(int(m.group(2)),int(m.group(3)))
        m2=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',t)
        if m2: pn=m2.group(1); dd=md(int(m2.group(2)),int(m2.group(3)))
        m3=re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',t)
        if m3:
            c=[p for p in PO.values() if p['pi']==m3.group(1)]
            if len(c)==1: pn=c[0]['num']; dd=md(int(m3.group(2)),int(m3.group(3))); conf='0.85'
            else: note('unresolved',f"{d['url']} PI {m3.group(1)} not matched to a PO")
        if pn and dd:
            po=po_(pn)
            if po['status'] in ('shipped','received'): note('stale',f"{d['url']} ETD change after PO shipped"); continue
            po['etd']=dd
            tx(d,conf,base()+[{'e':polook(pn),'a':'po/etd','v':dd.isoformat()}],'ETD change from chat'); continue
        # reply to PI with ETD (should equal PI)
        m=re.match(r'^(?:ETD(?: around)? (\d+)/(\d+)|ETD (\d+)/(\d+)|交期(\d+)月(\d+)号左右)',t)
        if m and not mine:
            nums=[int(x) for x in m.groups() if x]
            pn=SUPLAST.get(sup)
            if pn:
                dd=md(nums[0],nums[1])
                if po_(pn)['etd']!=dd: note('pi_chat_diff',f"{d['url']} {pn}: chat {dd} vs PI {po_(pn)['etd']}")
            continue
        if not mine and re.search(r'loaded',t):
            m=re.search(r'\b([A-Z]{4}\d{7})\b',t); cont=m.group(1)
            c=[p for p in st['ready'] if p not in st['loaded']]
            pn=c[-1] if c else None
            if not pn: note('unresolved',f"{d['url']} container {cont}: no PO candidate"); continue
            ss=[s for s in SH if pn in s['pos']]
            st['loaded'].add(pn)
            if len(ss)!=1: note('unresolved',f"{d['url']} container {cont} for {pn}: {len(ss)} shipments"); continue
            s=ss[0]
            if s['mode']=='LCL': note('conflict',f"{d['url']} container {cont} but booking {s['booking']} is LCL"); continue
            s['container']=cont
            tx(d,'0.9',base()+[{'e':shlook(s),'a':'shipment/container_no','v':cont}],f'container, PO {pn} named by context'); continue
        # everything else: no facts
        if re.search(r'rebate|涨价|降价|上调|price|Price|quote|放假|DHL|catalogue',t): note('gap',f"{d['url']}: {t[:80]}")
if __name__=='__main__':
    json.dump(TX,open('tx.json','w'),ensure_ascii=False)
    print(len(TX), collections.Counter(t['kind'] for t in TX))
    for k,v in R.items():
        print('==',k,len(v))
        for x in v[:40]: print('  ',x)
    print(collections.Counter(p['status'] for p in PO.values()))
