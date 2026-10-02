from build import *
TX=[]; REPORT=collections.defaultdict(list)
def T(docs,conf,facts,note=''):
    facts=[f for f in facts if f]
    if facts: TX.append(dict(docs=docs,conf=conf,facts=facts,note=note))
POREF=lambda po:['po/number',po]
status={}      # po -> status
etd={}         # po -> date
lines={}       # po -> [(n,item,qty)]
sup_of={}      # po -> supplier code
def st_fact(po,new):
    if RANK[new]>RANK.get(status.get(po),-1):
        status[po]=new; return (POREF(po),'po/status',new)
SH=[]; BY_HBL={}; BY_SO={}
SRANK={'booked':0,'departed':1,'arrived':2,'delivered':3}
def sref(s): return ['shipment/booking_no',s['so']] if s['so'] else ['shipment/hbl',s['hbl']]
def new_sh(**k):
    s=dict(so=None,hbl=None,container=None,vessel=None,origin=None,dest=None,pos=set(),bpos=set(),lines={},status=None,atd=None,departed_ts=None,arr_ts=None,entry=None,delivered=False,bts=None,mode=None); s.update(k); SH.append(s); return s
def find_sh(hbl,vessel,pos):
    if hbl in BY_HBL: return BY_HBL[hbl]
    cand=[s for s in SH if s['so'] and not s['hbl'] and s['vessel']==vessel and (s['bpos']&set(pos))]
    if not cand:
        cand=[s for s in SH if s['so'] and not s['hbl'] and (s['bpos']&set(pos)) and s['status']=='booked']
        if cand: REPORT['shipment matched on POs only'].append((hbl,vessel,[c['so'] for c in cand]))
    if len(cand)>1: REPORT['ambiguous shipment match'].append((hbl,[c['so'] for c in cand]))
    if cand:
        s=cand[0]; s['hbl']=hbl; BY_HBL[hbl]=s; return s
    s=new_sh(hbl=hbl,vessel=vessel); BY_HBL[hbl]=s
    REPORT['shipment without booking'].append(hbl); return s
def poline(po,item):
    for n,it,q in lines.get(po,[]):
        if it==item: return n
def shipped_check(s,doc):
    """returns facts for POs whose goods have all sailed"""
    out=[]
    for po in sorted({k[0] for k in s['lines']}):
        if RANK.get(status.get(po),-1)>=RANK['shipped']: continue
        # A: bookings carrying PO all have a shipment with hbl
        bk=[x for x in SH if po in x['bpos']]
        A=bool(bk) and all(x['hbl'] for x in bk)
        tot=collections.Counter()
        for x in SH:
            for (p,n),q in x['lines'].items():
                if p==po: tot[n]+=q
        B=all(tot[n]>=q for n,it,q in lines[po])
        if A or B:
            f=st_fact(po,'shipped'); out.append(f)
    return out
def po_actual_etd(s,docs_po=None):
    out=[]
    for po in sorted({k[0] for k in s['lines']}):
        if RANK.get(status.get(po),-1)>=RANK['shipped']:
            ds=[x['atd'] for x in SH if x['atd'] and any(k[0]==po for k in x['lines'])]
            if ds:
                v=max(ds).isoformat()
                if etd.get(po)!=v: etd[po]=v; out.append((POREF(po),'po/etd',v))
    return out
ctx={}  # per chat supplier: po of last PI file
pending=collections.defaultdict(list) # sup -> [(po,msg,conf)]
dep_seen=set()
for ts,_,kind,p in events:
    if kind=='pi':
        d=p['doc']; po=p['po']; sc=p['sup']; sup=['supplier/code',sc]
        sup_of[po]=sc
        f=[(POREF(po),'po/pi_number',p['pi_no']),(POREF(po),'po/supplier',sup),(POREF(po),'po/etd',p['date'] and p['etd']),
           (POREF(po),'core/currency','CNY' if p['cur']=='RMB' else p['cur'])]
        etd[po]=p['etd']
        f.append(st_fact(po,'confirmed'))
        lines[po]=[]
        for i,r in enumerate(p['rows'],1):
            key=f'{po}/{i}'; code=f'{sc}:{r["item"]}'
            if code not in SKU: REPORT['unknown item code'].append((p['pi_no'],code)); continue
            lines[po].append((i,r['item'],r['qty']))
            f+= [(['po_line/key',key],'core/part_of',POREF(po)),(['po_line/key',key],'po_line/sku',['factory/item_code',code]),
                 (['po_line/key',key],'po_line/quantity',str(r['qty'])),(['po_line/key',key],'po_line/unit_price',r['price'])]
        port=PORT[p['incoterm'].split()[-1]]
        f+= [(sup,'supplier/name',p['beneficiary']),(sup,'supplier/name_cn',p['name_cn']),(sup,'supplier/address',p['address']),
             (sup,'supplier/incoterm',p['incoterm']),(sup,'supplier/payment_terms',p['payment']),
             (sup,'supplier/currency','CNY' if p['cur']=='RMB' else p['cur']),(sup,'supplier/port',port)]
        T([d],'1',f,'PI '+p['pi_no'])
    elif kind=='qc':
        d=p['doc']; po=p['po']; q=['qc/report_no',p['report']]
        f=[(q,'qc/po',POREF(po)),(q,'qc/inspected_on',p['date']),(q,'qc/result',p['result']),
           (q,'qc/inspector',p['agency'].title()),(q,'qc/sample_size',str(p['sample']))]
        if p['result']=='PASS': f.append(st_fact(po,'ready'))
        T([d],'1',f,'QC '+p['report'])
    elif kind=='ci':
        d=p['doc']; po=p['po']; sc=sup_of.get(po)
        if sc is None: REPORT['CI for PO without PI'].append(p['n']); continue
        s=find_sh(p['hbl'],p['vessel'],[po])
        s['container']=None if p['container']=='LCL' else p['container']; s['vessel']=p['vessel']; s['origin']=p['origin']; s['dest']=p['dest']
        s['mode']=s['mode'] or ('LCL' if p['container']=='LCL' else None)
        r_=sref(s)
        f=[(r_,'shipment/hbl',p['hbl'])]
        if p['container']!='LCL': f.append((r_,'shipment/container_no',p['container']))
        f+=[(r_,'shipment/vessel',p['vessel']),(r_,'shipment/origin',p['origin']),(r_,'shipment/destination',p['dest'])]
        for r in p['rows']:
            n=poline(po,r['item']); code=f'{sc}:{r["item"]}'
            if n is None: REPORT['CI row without PO line'].append((p['n'],r['item'])); continue
            lk=f'{p["hbl"]}/{po}/{n}'; L=['shipment_line/key',lk]
            q=r['qty']; ctn=p['pack'][r['item']][0]['ctns']
            if p['pack'][r['item']][0]['pcs']!=q: REPORT['CI pcs vs PL pcs'].append((p['n'],r['item']))
            s['lines'][(po,n)]=q; s['pos'].add(po)
            f+=[(L,'core/part_of',r_),(L,'shipment_line/po_line',['po_line/key',f'{po}/{n}']),(L,'shipment_line/quantity',str(q)),(L,'shipment_line/cartons',str(ctn))]
            if SKU[code]!=r['hs']: REPORT['HS code differs from SKU'].append((p['n'],code,SKU[code],r['hs']))
        f.append(None)
        sf=shipped_check(s,d)
        T([d],'1',f+sf,'CI '+p['n'])
    elif kind=='mail':
        k=p['kind']; d=p['doc']
        if k=='booking':
            s=new_sh(so=p['so'],vessel=p['vessel'],origin=p['pol'],dest=p['pod'],status='booked',mode=p['mode'],
                     bpos={x[0] for x in p['pos']})
            for po,exact in p['pos']:
                if not exact: REPORT['PO named loosely in booking'].append((p['so'],po))
            r_=sref(s)
            T([d],'1',[(r_,'shipment/mode',p['mode']),(r_,'shipment/vessel',p['vessel']),(r_,'shipment/origin',p['pol']),
                (r_,'shipment/destination',p['pod']),(r_,'shipment/etd',inst(p['etd'],p['pol'])),(r_,'shipment/eta',inst(p['eta'],p['pod'])),
                (r_,'shipment/status','booked')],'booking '+p['so'])
        elif k=='roll':
            s=next(x for x in SH if x['so']==p['so'])
            r_=sref(s)
            T([d],'1',[(r_,'shipment/etd',inst(p['etd'],s['origin'])),(r_,'shipment/eta',inst(p['eta'],s['dest']))],'roll '+p['so'])
        elif k=='prealert':
            pos=[l[0] for l in p['lines']]
            s=find_sh(p['hbl'],p['vessel'],pos)
            s['container']=None if p['container']=='LCL' else p['container']
            if s['vessel']!=p['vessel']: REPORT['vessel differs booking vs prealert'].append((p['hbl'],s['vessel'],p['vessel']))
            s['vessel']=p['vessel']
            s['origin']=s['origin'] or PORT[p['pol_name']]
            s['dest']=s['dest'] or 'USNYC'
            s['atd']=p['atd']; s['status']='departed'
            r_=sref(s)
            f=[(r_,'shipment/hbl',p['hbl'])]
            if s['container']: f.append((r_,'shipment/container_no',s['container']))
            f+=[(r_,'shipment/vessel',p['vessel']),(r_,'shipment/etd',inst(p['atd'],s['origin'])),(r_,'shipment/eta',inst(p['eta'],s['dest'])),(r_,'shipment/status','departed')]
            for po,item,ctn,pcs in p['lines']:
                sc=sup_of.get(po); n=poline(po,item)
                if n is None: REPORT['prealert row without PO line'].append((p['hbl'],po,item)); continue
                lk=f'{p["hbl"]}/{po}/{n}'; L=['shipment_line/key',lk]
                if (po,n) in s['lines'] and s['lines'][(po,n)]!=pcs: REPORT['prealert qty differs from CI'].append((p['hbl'],po,item))
                s['lines'][(po,n)]=pcs; s['pos'].add(po)
                f+=[(L,'core/part_of',r_),(L,'shipment_line/po_line',['po_line/key',f'{po}/{n}']),(L,'shipment_line/quantity',str(pcs)),(L,'shipment_line/cartons',str(ctn))]
            sf=shipped_check(s,d); f+=sf
            f+=po_actual_etd(s)
            T([d],'1',f,'prealert '+p['hbl'])
        elif k=='eta':
            s=BY_HBL[p['hbl']]; T([d],'1',[(sref(s),'shipment/eta',inst(p['eta'],s['dest']))],'eta '+p['hbl'])
        elif k=='arrival':
            s=BY_HBL[p['hbl']]; s['status']='arrived'
            T([d],'1',[(sref(s),'shipment/status','arrived'),(sref(s),'shipment/eta',inst(p['arr'],s['dest']))],'arrival '+p['hbl'])
        elif k in('entry','receipt'):
            ref=p['ref']
            if ref.startswith('PBLHB'): s=BY_HBL.get(ref)
            else:
                c=[x for x in SH if x['container']==ref and x['hbl'] and x['status'] in ('departed','arrived','delivered')]
                if k=='receipt': c=[x for x in c if x['status']=='arrived' and not x['delivered']]
                else: c=[x for x in c if not x['entry']]
                c.sort(key=lambda x:x['atd'])
                if len(c)>1: REPORT['container ref matched several shipments'].append((p['subj'],[x['hbl'] for x in c]))
                s=c[0] if c else None
            if not s: REPORT['unresolved ref'].append(p['subj']); continue
            if k=='entry':
                s['entry']=p['entry']; e=['customs/entry_no',p['entry']]
                duty=sum(map(__import__('decimal').Decimal,[p['hts'],p['s301'],p['add']])); fees=sum(map(__import__('decimal').Decimal,[p['mpf'],p['hmf']]))
                if duty+fees!=__import__('decimal').Decimal(p['total']): REPORT['entry total != duty+fees'].append(p['entry'])
                T([d],'1',[(e,'customs/shipment',sref(s)),(e,'customs/filed_on',p['ts'].date().isoformat()),(e,'customs/entered_value',p['value']),
                    (e,'customs/duty',str(duty)),(e,'customs/fees',str(fees)),(e,'core/currency','USD')],'entry '+p['entry'])
            else:
                s['delivered']=True; s['status']='delivered'
                f=[(sref(s),'shipment/status','delivered'),(sref(s),'shipment/delivered_at',p['ts'].isoformat())]
                for po in sorted(s['pos']):
                    if RANK.get(status.get(po),-1)>=RANK['shipped'] and all(x['delivered'] for x in SH if po in x['pos']):
                        f.append(st_fact(po,'received'))
                T([d],'1',f,'receipt '+p['rcv'])
                disc=[l.strip() for l in p['body'].split('\n') if 'expected' in l and re.search(r'received (\d+), damaged (\d+)',l)]
                for l in disc:
                    m=re.search(r'expected (\d+), received (\d+), damaged (\d+)',l)
                    if m[1]!=m[2] or m[3]!='0': REPORT['warehouse discrepancies'].append((p['rcv'],l))
    elif kind=='chat':
        m=p; sup=m['sup']; t=m['text']
        if m['ours']:
            r=re.search(r'new PO (PO-\d{4}-\d{4}) attached|here\'s (PO-\d{4}-\d{4})\.|PO (PO-\d{4}-\d{4}) for \d+ items',t)
            if r:
                po=[x for x in r.groups() if x][0]
                dd=m['ts'].date().isoformat()
                f=[(POREF(po),'po/placed_on',dd),(POREF(po),'po/supplier',['supplier/code',sup]),st_fact(po,'sent')]
                T([dict(hash=m['hash'],url=m['url'])],'1',f,'PO sent '+po)
                ctx[sup]=po
                continue
            r=re.search(r'we sent the deposit for (PO-\d{4}-\d{4}) \((\w+) ([\d,.]+)\)',t)
            if r:
                pending[sup].append((r[1],m,'0.9')); continue
            r=re.search(r'Deposit paid today, (\w+) ([\d,]+\.\d\d)',t)
            if r:
                amt=float(r[2].replace(',',''))
                best=None
                for po,pi in PI.items():
                    if sup_of.get(po)!=sup or status.get(po) is None: continue
                    pct=int(re.search(r'(\d+)% deposit',pi['payment'])[1]) if '% deposit' in pi['payment'] else None
                    if pct and abs(float(pi['total'])*pct/100-amt)<0.011 and RANK[status[po]]<=RANK['confirmed']:
                        best=po
                if best: pending[sup].append((best,m,'0.8'))
                else: REPORT['deposit unmatched'].append((m['url'],t))
                continue
        else:
            if re.search(r'Received, thank you|收到，谢谢|定金收到了|大货生产中',t):
                if pending[sup]:
                    po,dm,conf=pending[sup].pop(0)
                    f=[st_fact(po,'in_production')]
                    T([dict(hash=m['hash'],url=m['url']),dict(hash=dm['hash'],url=dm['url'])],conf,f,'in_production '+po)
                continue
            r=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)|(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号|(\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',t)
            if r:
                g=r.groups()
                if g[0]: po=g[0]; mo,da=int(g[1]),int(g[2]); conf='0.9'
                elif g[3]: po=g[3]; mo,da=int(g[4]),int(g[5]); conf='0.9'
                else:
                    po=PIBYNO[g[6]]['po']; mo,da=int(g[7]),int(g[8]); conf='0.8'
                v=chats.next_date(mo,da,m['ts'].astimezone(chats.CN).date()).isoformat()
                if RANK.get(status.get(po),-1)>=RANK['shipped']:
                    REPORT['slip after shipped, not applied'].append((m['url'],po,v)); continue
                etd[po]=v
                T([dict(hash=m['hash'],url=m['url'])],conf,[(POREF(po),'po/etd',v)],'slip '+po)
                continue
            r=re.search(r'\[文件\] (\S+)\.pdf',t)
            if r and r[1] in PIBYNO: ctx[sup]=PIBYNO[r[1]]['po']; continue
            r=re.search(r'^(?:ETD(?: around)? (\d+)/(\d+)|交期(\d+)月(\d+)号左右(?:，ETD around (\d+)/(\d+))?)$',t)
            if r:
                g=r.groups(); mo,da=(int(g[0]),int(g[1])) if g[0] else (int(g[2]),int(g[3]))
                po=ctx.get(sup); v=chats.next_date(mo,da,m['ts'].astimezone(chats.CN).date()).isoformat()
                pi_etd=PI[po]['etd'] if po in PI else None
                if v!=pi_etd: REPORT['chat ETD differs from PI'].append((m['url'],po,v,pi_etd))
                continue
            r=re.search(r'(?:container loaded: |Container )([A-Z]{4}\d{7})',t)
            if r:
                REPORT['chat container (not written; no PO named)'].append((m['url'],r[1])); continue
if __name__=='__main__':
    for k,v in REPORT.items():
        print('##',k,len(v))
        for x in v[:40]: print('  ',x)
    print(len(TX),'transactions',sum(len(t['facts']) for t in TX),'facts')
    print(collections.Counter(t['note'].split()[0] for t in TX))
    print('status',collections.Counter(status.values()))
