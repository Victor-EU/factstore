import sys,pickle,collections,json
from parse import *
from events import parse_mail_events,dmy
EXEC = len(sys.argv)>1 and sys.argv[1]=='exec'
DRY = len(sys.argv)>1 and sys.argv[1]=='dry'
notes=collections.defaultdict(list)   # report items
txlog=[]                              # all transactions
STATUS_PO=['draft','sent','confirmed','in_production','ready','shipped','received']
STATUS_SH=['booked','departed','arrived','delivered']

pdfs=parse_pdfs(); chats=parse_chats(); mails_raw=parse_mail()
chat_pos=set()
for c in chats: chat_pos|=set(re.findall(r'PO-\d{4}-\d{4}',c['text']))
pos_universe=chat_pos|{d['po'] for d in pdfs if 'po' in d}
mails=parse_mail_events(mails_raw,pos_universe)

# ---------- store reference data
import factstore
def q(sql):
    r=factstore.query(sql); return r.rows if hasattr(r,'rows') else r['rows']
item2sku={r[0]:r[1] for r in q('select c.v, k.v from "factory/item_code" c join "sku/code" k using(e)')}
sku_hs={r[0]:r[1] for r in q('select k.v, h.v from "sku/code" k join "sku/hs_code" h using(e)')}
store_pos={r[0] for r in q('select v from "po/number"')}
pos_universe|=store_pos

# ---------- transaction helper
def T(doc,facts,conf='1'):
    for _s in shipments: _s._r=None
    if not facts: return
    f=[{"e":["document/hash",doc['hash']],"a":"document/url","v":doc['url']},
       {"e":"tmp:tx","a":"core/evidence","v":["document/hash",doc['hash']]},
       {"e":"tmp:tx","a":"core/confidence","v":conf}]+facts
    txlog.append((doc['url'],conf,f))
    if EXEC or DRY:
        r=factstore.transact(f,dry_run=DRY)
def F(e,a,v): return {"e":e,"a":a,"v":v}
POk=lambda po:["po/number",po]

# ---------- model
class Doc(dict): pass
po_sup={}          # po -> supplier code
po_pi_total={}
po_dep={}
po_lines={}        # po -> OrderedDict item_code -> dict(key,qty,idx)
po_status={}
po_etd={}          # po -> (ts, value)
po_state={}
sup_done={}
shipments=[]       # Shipment objects
class Shipment:
    def __init__(s): s.so=None; s.hbl=None; s.container=None; s.asserted=set(); s.status=None; s.dest=None; s.origin=None; s.lines={}; s.atd=None; s.pos=set(); s.has_prealert=False; s.has_ci=False; s.first_ts=None
    def ref(s,own=()):
        if getattr(s,'_r',None): return s._r
        if s.hbl and 'hbl' in s.asserted: return ["shipment/hbl",s.hbl]
        if s.so and 'so' in s.asserted: return ["shipment/booking_no",s.so]
        if 'hbl' in own and s.hbl: return ["shipment/hbl",s.hbl]
        if 'so' in own and s.so: return ["shipment/booking_no",s.so]
        raise Exception('no ref')
    def ids(s,own):
        out=[]
        s._r=None; s._r=s.ref(own)
        if 'hbl' in own and 'hbl' not in s.asserted:
            out.append(F(s.ref(own),'shipment/hbl',s.hbl)); s.asserted.add('hbl')
        if 'so' in own and 'so' not in s.asserted:
            out.append(F(s.ref(own),'shipment/booking_no',s.so)); s.asserted.add('so')
        return out
bk_by_so={}; sh_by_hbl={}
# offline resolution booking<->prealert
bookings=[e for e in mails if e['type']=='booking']; prealerts=[e for e in mails if e['type']=='prealert']
hbl2so={}
for p in prealerts:
    pp={l[0] for l in p['lines']}
    c=[b for b in bookings if b['vessel']==p['vessel'] and b['origin']==p['origin'] and set(b['pos'])&pp and b['ts']<=p['ts']]
    assert len(c)==1; hbl2so[p['hbl']]=c[0]['so']
so2hbl={v:k for k,v in hbl2so.items()}
def get_shipment(hbl=None,so=None,container=None,ts=None):
    if hbl and hbl in hbl2so and not so: so=hbl2so[hbl]
    if so and so in so2hbl and not hbl: hbl=so2hbl[so]
    for s in shipments:
        if (hbl and s.hbl==hbl) or (so and s.so==so): 
            return s
    s=Shipment(); s.hbl=hbl; s.so=so; shipments.append(s); return s

def instant(date,locode): return iso(port_instant(date,locode))
def fwd(cur,new,order): 
    return cur is None or order.index(new)>order.index(cur)

def po_status_facts(po,new,facts):
    cur=po_status.get(po)
    if fwd(cur,new,STATUS_PO):
        po_status[po]=new; facts.append(F(POk(po),'po/status',new))
def set_etd(po,ts,val,facts):
    cur=po_etd.get(po)
    if cur and cur[0]>ts:
        notes['stale ETD skipped'].append((po,val,str(ts))); return
    po_etd[po]=(ts,val); facts.append(F(POk(po),'po/etd',val))
def PDF_TS(d): return dt.datetime(d.year,d.month,d.day,tzinfo=CN)

# ---------- PDF handlers
def do_pi(d):
    po=d['po']; sc=d['supcode']; f=[]
    po_sup[po]=sc; po_pi_total[po]=float(d['total'])
    mm=re.search(r'(\d+)% deposit',d['payment']); po_dep[po]=int(mm.group(1))/100 if mm else None
    f+= [F(POk(po),'po/pi_number',d['pi_no']),F(POk(po),'po/supplier',["supplier/code",sc]),
         F(POk(po),'core/currency',d['currency'])]
    set_etd(po,PDF_TS(d['date']),d['etd'].isoformat(),f)
    po_status_facts(po,'confirmed',f)
    lines=po_lines.setdefault(po,collections.OrderedDict())
    for r in d['rows']:
        code=f"{sc}:{r['item']}"
        if code not in item2sku: notes['unresolved item code'].append((d['name'],code)); continue
        if code in lines: ln=lines[code]
        else:
            ln=dict(key=f"{po}/{len(lines)+1}",qty=r['qty'],sku=item2sku[code]); lines[code]=ln
        ln['qty']=r['qty']
        k=["po_line/key",ln['key']]
        f+=[F(k,'core/part_of',POk(po)),F(k,'po_line/sku',["factory/item_code",code]),
            F(k,'po_line/quantity',str(r['qty'])),F(k,'po_line/unit_price',r['price'])]
    sup=["supplier/code",sc]
    f+=[F(sup,'supplier/name',d['legal']),F(sup,'supplier/name_cn',d['name_cn']),F(sup,'supplier/address',d['address']),
        F(sup,'supplier/incoterm',d['incoterm']),F(sup,'supplier/payment_terms',re.sub(r'^T/T ','T/T ',d['payment'])),
        F(sup,'supplier/currency',d['currency']),F(sup,'supplier/port',PORTS[d['port_name']])]
    T(d,f)
def do_qc(d):
    po=d['po']; r=["qc/report_no",d['report']]
    f=[F(r,'qc/po',POk(po)),F(r,'qc/inspected_on',d['date'].isoformat()),F(r,'qc/result',d['result']),
       F(r,'qc/inspector',d['inspector']),F(r,'qc/sample_size',str(d['sample']))]
    if d['result']=='PASS': po_status_facts(po,'ready',f)
    T(d,f)

def eval_shipped(po,ts,facts,atd=None):
    lines=po_lines.get(po)
    if not lines: return
    done=all(sum(s.lines.get(ln['key'],(0,0))[0] for s in shipments)>=ln['qty'] for ln in lines.values())
    if done:
        po_status_facts(po,'shipped',facts)
    if po_status.get(po) in ('shipped','received') and atd:
        set_etd(po,ts,atd.isoformat(),facts)
    return done

def add_ship_line(s,hbl,po,code,qty,cartons,facts,own):
    if code not in po_lines.get(po,{}): notes['unresolved shipment row'].append((hbl,po,code)); return
    ln=po_lines[po][code]
    k=["shipment_line/key",f"{hbl}/{ln['key']}"]
    old=s.lines.get(ln['key'])
    if old and (old[0],old[1])!=(qty,cartons): notes['line conflict (later doc wins)'].append((hbl,ln['key'],old,(qty,cartons)))
    s.lines[ln['key']]=(qty,cartons); s.pos.add(po)
    facts+=[F(k,'core/part_of',s.ref(own)),F(k,'shipment_line/po_line',["po_line/key",ln['key']]),
            F(k,'shipment_line/quantity',str(qty)),F(k,'shipment_line/cartons',str(cartons))]

def do_ci(d):
    sc=d['supcode']; po=d['po']; hbl=d['hbl']; f=[]
    s=get_shipment(hbl=hbl)
    own={'hbl'}
    f+=s.ids(own)
    if s.so and 'so' in s.asserted: pass
    if d['container']!='LCL':
        f.append(F(s.ref(own),'shipment/container_no',d['container'])); s.container=d['container']
    f+=[F(s.ref(own),'shipment/vessel',d['vessel']),F(s.ref(own),'shipment/origin',d['origin']),F(s.ref(own),'shipment/destination',d['dest'])]
    s.dest=d['dest']; s.origin=d['origin']
    s.has_ci=True
    for r in d['rows']:
        code=f"{sc}:{r['item']}"
        sku=item2sku.get(code)
        if sku and sku_hs.get(sku)!=r['hs']: notes['HS code differs from SKU (not overwritten)'].append((d['name'],code,sku,sku_hs.get(sku),r['hs']))
        add_ship_line(s,hbl,po,code,r['qty'],d['pl'][r['item']],f,own)
    T(d,f)
    f2=[]
    eval_shipped(po,PDF_TS(d['date']),f2)
    T(d,f2)

# ---------- mail handlers
def do_mail(e):
    ty=e['type']; f=[]
    if ty=='booking':
        s=get_shipment(so=e['so']); own={'so'}
        f+=s.ids(own); r=s.ref(own)
        s.dest=e['dest']; s.origin=e['origin']; s.status='booked'; s.first_ts=e['ts']
        f+=[F(r,'shipment/mode',e['mode']),F(r,'shipment/vessel',e['vessel']),F(r,'shipment/origin',e['origin']),
            F(r,'shipment/destination',e['dest']),F(r,'shipment/etd',instant(e['etd'],e['origin'])),
            F(r,'shipment/eta',instant(e['eta'],e['dest'])),F(r,'shipment/status','booked')]
        s.pos|=set(e['pos'])
        T(e,f)
    elif ty=='rolled':
        s=get_shipment(so=e['so']); 
        r=s.ref({'so'})
        T(e,[F(r,'shipment/etd',instant(e['etd'],s.origin)),F(r,'shipment/eta',instant(e['eta'],s.dest))])
    elif ty=='prealert':
        s=get_shipment(hbl=e['hbl']); own={'hbl'}
        f+=s.ids(own); r=s.ref(own)
        s.has_prealert=True; s.atd=e['atd']; s.dest=e['dest']; s.origin=e['origin']
        if e['container']: f.append(F(r,'shipment/container_no',e['container'])); s.container=e['container']
        f+=[F(r,'shipment/vessel',e['vessel']),F(r,'shipment/origin',e['origin']),F(r,'shipment/destination',e['dest']),
            F(r,'shipment/etd',instant(e['atd'],e['origin'])),F(r,'shipment/eta',instant(e['eta'],e['dest']))]
        if fwd(s.status,'departed',STATUS_SH): s.status='departed'; f.append(F(r,'shipment/status','departed'))
        for po,item,ct,pcs in e['lines']:
            sc=po_sup[po]
            add_ship_line(s,e['hbl'],po,f"{sc}:{item}" if ':' not in item else item,pcs,ct,f,own)
        T(e,f)
        f2=[]
        for po in sorted({l[0] for l in e['lines']}): eval_shipped(po,e['ts'],f2,atd=e['atd'])
        T(e,f2)
    elif ty=='eta':
        s=get_shipment(hbl=e['hbl']); T(e,[F(s.ref({'hbl'}),'shipment/eta',instant(e['eta'],s.dest))])
    elif ty=='arrival':
        s=get_shipment(hbl=e['hbl'])
        if s.container!=(None if e['container']=='LCL' else e['container']): notes['arrival container mismatch'].append((e['hbl'],e['container'],s.container))
        r=s.ref({'hbl'}); fa=[F(r,'shipment/eta',instant(e['eta'],e['dest']))]
        if fwd(s.status,'arrived',STATUS_SH): s.status='arrived'; fa.append(F(r,'shipment/status','arrived'))
        T(e,fa)
    elif ty=='entry':
        ref=e['ref']
        cands=[s for s in shipments if s.hbl==ref or (s.container==ref)]
        if not cands: notes['customs: shipment not found'].append((e['entry'],ref)); return
        s=cands[-1]
        k=["customs/entry_no",e['entry']]
        duty=float(e['hts'])+float(e['s301'])+float(e['add']); fees=float(e['mpf'])+float(e['hmf'])
        fl=[F(k,'customs/shipment',s.ref({'hbl'})),
            F(k,'customs/filed_on',e['ts'].date().isoformat()),F(k,'customs/entered_value',e['value']),
            F(k,'customs/duty',f"{duty:.2f}"),F(k,'customs/fees',f"{fees:.2f}"),F(k,'core/currency','USD')]
        if abs(duty+fees-float(e['total']))>0.015: notes['customs total mismatch'].append((e['entry'],duty+fees,e['total']))
        T(e,fl)
    elif ty=='receipt':
        ref=e['ref']
        cands=[s for s in shipments if (s.hbl==ref or s.container==ref) and s.has_prealert]
        if not cands: notes['receipt: shipment not found'].append((e['rcv'],ref)); return
        s=cands[-1]; r=s.ref({'hbl'})
        fl=[F(r,'shipment/delivered_at',iso(e['ts']))]
        if fwd(s.status,'delivered',STATUS_SH): s.status='delivered'; fl.append(F(r,'shipment/status','delivered'))
        for sku,desc,exp,rec,dam in e['disc']:
            if exp!=rec or int(dam)>0: notes['warehouse discrepancies'].append((e['rcv'],ref,sku,desc,exp,rec,dam))
        T(e,fl)
        f2=[]
        for po in sorted(s.pos):
            carrying=[x for x in shipments if po in x.pos]
            if all(x.status=='delivered' for x in carrying): po_status_facts(po,'received',f2)
        T(e,f2)

# ---------- chat handlers
chat_state=collections.defaultdict(dict)
def lastpi(code,ts): return chat_state[code].get('pi')
def zh_date(m,d,ts):
    msgd=ts.astimezone(CN).date()
    y=msgd.year; c=dt.date(y,m,d)
    if c<msgd: c=dt.date(y+1,m,d)
    return c
def do_chat(c):
    code=c['code']; t=c['text']; st=chat_state[code]; ts=c['ts']; sup=code
    maya=c['sender'].startswith('Maya')
    # new PO
    if maya and re.search(r"new PO PO-|here's PO-|! PO PO-",t) and 'deposit' not in t:
        po=re.search(r'PO-\d{4}-\d{4}',t).group(0)
        po_sup.setdefault(po,sup)
        T(c,[F(POk(po),'po/placed_on',ts.date().isoformat()),F(POk(po),'po/supplier',["supplier/code",sup])])
        st['lastpo']=po; return
    if not maya:
        m=re.match(r'\[文件\] ((?!PO-)\S+)\.pdf',t)
        if m and not m.group(1).startswith(('CI-PL','LCI')):
            st['pi']=m.group(1); st['pits']=ts; return
        # ETD with PO named
        po=None; conf=None
        m=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',t)
        if m: po=m.group(1); mo,dd=int(m.group(2)),int(m.group(3)); conf='0.9'
        m2=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',t)
        if m2: po=m2.group(1); mo,dd=int(m2.group(2)),int(m2.group(3)); conf='0.9'
        m3=re.match(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',t)
        if m3:
            pi=m3.group(1); po=pi2po.get(pi); mo,dd=int(m3.group(2)),int(m3.group(3)); conf='0.8'
            if not po: notes['unresolved ETD msg'].append((c['url'],t)); return
        m4=re.match(r'(?:交期(\d+)月(\d+)号左右)?(?:，)?(?:ETD(?: around)? (\d+)/(\d+))?$',t)
        if not po and m4 and t.strip() and (m4.group(1) or m4.group(3)):
            pi=st.get('pi'); po=pi2po.get(pi) if pi else None
            if not po: notes['unresolved ETD msg'].append((c['url'],t)); return
            if m4.group(1): mo,dd=int(m4.group(1)),int(m4.group(2))
            else: mo,dd=int(m4.group(3)),int(m4.group(4))
            conf='0.8'
            val=zh_date(mo,dd,ts)
            # compare with PI
            pe=po_etd.get(po)
            if pe and pe[1]!=val.isoformat(): notes['chat ETD differs from PI ETD'].append((c['url'],po,pe[1],val.isoformat()))
        if po:
            val=zh_date(mo,dd,ts)
            f=[]; set_etd(po,ts,val.isoformat(),f); T(c,f,conf); return
        # supplier acknowledgements
        if t in ('Received, thank you','收到，谢谢','定金收到了，马上安排生产'):
            po=st.pop('pending',None)
            if po:
                f=[]; po_status_facts(po,'in_production',f); T(c,f,'0.8')
            return
        if t=='大货生产中':
            cand=[p for p in st.get('deposited',[]) if STATUS_PO.index(po_status.get(p,'draft'))<STATUS_PO.index('ready')]
            if len(cand)==1:
                f=[]; po_status_facts(cand[0],'in_production',f); T(c,f,'0.7')
            else: notes['production-started msg, PO ambiguous (not recorded)'].append((c['url'],cand))
            return
        m=re.search(r'(?:loaded: |Container )([A-Z]{4}\d{7})',t)
        if m: st.setdefault('containers',[]).append((m.group(1),c['url'])); return
        return
    # Maya: deposit
    if maya and 'deposit' in t.lower():
        m=re.search(r'(PO-\d{4}-\d{4})',t)
        amt=float(re.search(r'(?:USD|CNY) (\d[\d,]*\.\d\d)',t).group(1).replace(',',''))
        if m: po=m.group(1)
        else:
            cand=[p for p,tot in po_pi_total.items() if po_sup.get(p)==sup and po_dep.get(p) and abs(round(tot*po_dep[p],2)-amt)<0.015]
            if len(cand)!=1: notes['deposit msg, PO unresolved'].append((c['url'],amt,cand)); return
            po=cand[0]
        st['pending']=po; st.setdefault('deposited',[]).append(po)

pi2po={d['pi_no']:d['po'] for d in pdfs if d['kind']=='pi'}
evs=[]
for d in pdfs: evs.append((PDF_TS(d['date']),{'pi':0,'qc':1,'ci':2}[d['kind']],'pdf',d))
for c in chats: evs.append((c['ts'],5,'chat',c))
for e in mails: evs.append((e['ts'],6,'mail',e))
evs.sort(key=lambda x:(x[0].astimezone(dt.timezone.utc),x[1]))
for ts,_,k,d in evs:
    if k=='pdf': {'pi':do_pi,'qc':do_qc,'ci':do_ci}[d['kind']](d)
    elif k=='chat': do_chat(d)
    else: do_mail(d)
# container chat messages vs documents
ci_conts={d['container'] for d in pdfs if d['kind']=='ci'}
for code,st in chat_state.items():
    for cont,url in st.get('containers',[]):
        if cont not in ci_conts: notes['chat container not in any CI'].append((url,cont))
print(len(txlog),'transactions')
print(collections.Counter(c for _,c,_ in txlog))
for k,v in notes.items():
    print('##',k,len(v))
    for x in v[:12]: print('   ',x)
pickle.dump((txlog,dict(notes)),open('plan.pkl','wb'))
