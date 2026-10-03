import csv,json,re,glob,os,hashlib,collections as C,sys
EX='exports'
SCR='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-h-ev4813q6-catalogue-work/7100dcc2-9ffa-4ba1-af6d-381f07752e5c/scratchpad'
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def doc(p): return ['document/hash',sha(p)]
def num(gid): return gid.rsplit('/',1)[1]

# ---- load
prod={};var={}
for l in open(f'{EX}/shopify/products.jsonl'):
    d=json.loads(l)
    (var if 'sku' in d else prod)[d['id']]=d
inv=list(csv.DictReader(open(f'{EX}/3pl/inventory_snapshot.csv')))
fi=list(csv.DictReader(open(f'{EX}/amazon/fba_inventory.txt'),delimiter='\t'))
upc2var={v['barcode']:v for v in var.values()}
tpl_by_upc={r['UPC']:r for r in inv}
assert set(upc2var)==set(tpl_by_upc) and len(upc2var)==49

# ---- hub canonical code
WF=re.compile(r'^AH-[A-Z]{3}-\d{4}-[A-Z]{3}$')
spell=C.defaultdict(set)
for u,v in upc2var.items(): spell[u].add(v['sku'])
for u,r in tpl_by_upc.items():
    if r['Client SKU']: spell[u].add(r['Client SKU'])
def amz_key(s): return s.upper().replace('-FBA','')
def canon_form(s):
    m=re.match(r'^AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})$',s.upper())
    return (m.group(1),int(m.group(2)),m.group(3)) if m else None
def key_sw(a,b):
    return a[:2]==b[:2] and (a[2]==b[2] or (sorted(a[2])==sorted(b[2]) and sum(x!=y for x,y in zip(a[2],b[2]))==2))
colour_freq=C.Counter()
for u,s in spell.items():
    for x in s:
        if WF.match(x): colour_freq[x[-3:]]+=1
votes=C.defaultdict(C.Counter)
for u,v in upc2var.items(): votes[u][v['sku']]+=1
for u,r in tpl_by_upc.items():
    if r['Client SKU']: votes[u][r['Client SKU']]+=1
shop_forms={canon_form(v['sku']):u for u,v in upc2var.items()}
for r in fi:
    f=canon_form(amz_key(r['sku']))
    u=shop_forms.get(f) or [uu for ff,uu in shop_forms.items() if key_sw(ff,f)][0]
    votes[u][amz_key(r['sku'])]+=1
hub={}
for u,s in spell.items():
    wf=[x for x in votes[u] if WF.match(x)] or list(votes[u])
    hub[u]=max(wf,key=lambda x:(votes[u][x],colour_freq[x[-3:]],x))
assert len(set(hub.values()))==49
code_by_form={canon_form(c):u for u,c in hub.items()}
amz2hub={}
for r in fi:
    f=canon_form(amz_key(r['sku']))
    u=code_by_form.get(f)
    if u is None:
        cands=[uu for ff,uu in code_by_form.items() if key_sw(ff,f)]
        assert len(cands)==1,(r['sku'],cands); u=cands[0]
    amz2hub[r['sku']]=u
assert len(set(amz2hub.values()))==25
var2hub={v['id']:u for u,v in upc2var.items()}

# ---- factory crosswalk (from commercial invoices: item no, description, HS)
PRE={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
fac={}
fdocs=set()
def words(s): return set(re.findall(r'[a-z0-9]+',s.lower()))
hubw={u:words(prod[upc2var[u]['__parentId']]['title']+' '+upc2var[u]['title']) for u in upc2var}
for f in sorted(glob.glob(f'{SCR}/txt/CI-PL_*.txt')):
    t=open(f).read().split('\n'); base=os.path.basename(f)[6:-4]
    pre=re.match(r'[A-Z]+',base).group()
    for i,l in enumerate(t):
        m=re.match(r'^([A-Z]{2}-?\d{3,5}|\d{3}) (.+)$',l)
        if m and i+2<len(t):
            hs=re.search(r'(\d{4}\.\d{2}\.\d{4})',t[i+2])
            if hs:
                fac.setdefault((PRE[pre],m.group(1)),set()).add((m.group(2).strip(),hs.group(1)))
                fdocs.add(os.path.basename(f)[:-4]+'.pdf')
fx={}
for (sup,it),s in fac.items():
    assert len(s)==1,(sup,it,s)
    (d,hs),=s; w=words(d)
    sc=sorted(((len(w&h)/len(w|h),u) for u,h in hubw.items()),reverse=True)
    assert sc[0][0]==1.0 and sc[1][0]<0.8
    fx[(sup,it)]=(sc[0][1],hs)
assert len({u for u,_ in fx.values()})==len(fx)==49, len(fx)

def docfacts(path):
    return [{'e':['document/hash',sha(path)],'a':'document/url','v':path.replace(EX+'/','')}]
batches=[]
def add(label,facts,evidence=(),conf=None):
    f=list(facts)
    for p in evidence:
        f+=docfacts(p)
        f.append({'e':'tmp:tx','a':'core/evidence','v':doc(p)})
    if conf is not None: f.append({'e':'tmp:tx','a':'core/confidence','v':str(conf)})
    batches.append((label,f))

SHOP=f'{EX}/shopify/products.jsonl'; INVP=f'{EX}/3pl/inventory_snapshot.csv'; FBAI=f'{EX}/amazon/fba_inventory.txt'
t1=[];t09=[];t07=[]
def H(u): return ['sku/code',hub[u]]
for u,v in upc2var.items():
    tgt=t1 if v['sku']==hub[u] else t09
    tgt+=[{'e':H(u),'a':'sku/code','v':hub[u]},{'e':H(u),'a':'shopify/variant_id','v':num(v['id'])}]
    t1+=[{'e':H(u),'a':'sku/upc','v':u},{'e':H(u),'a':'tpl/item_code','v':tpl_by_upc[u]['Item Code']}]
for r in fi:
    u=amz2hub[r['sku']]; tgt=t1 if r['sku']==hub[u] else t09
    tgt+=[{'e':H(u),'a':'sku/code','v':hub[u]},{'e':H(u),'a':'amazon/seller_sku','v':r['sku']},{'e':H(u),'a':'amazon/asin','v':r['asin']},{'e':H(u),'a':'amazon/fnsku','v':r['fnsku']}]
for (sup,it),(u,hs) in fx.items():
    t07+=[{'e':H(u),'a':'sku/code','v':hub[u]},{'e':H(u),'a':'factory/item_code','v':f'{sup}:{it}'},{'e':H(u),'a':'sku/supplier','v':['supplier/code',sup]},{'e':H(u),'a':'sku/hs_code','v':hs}]
FDOC=[f'{EX}/supplier_docs/{p}' for p in sorted(fdocs)]
add('hubs tier1',t1,[SHOP,INVP,FBAI],1)
add('hubs tier0.9',t09,[SHOP,FBAI],0.9)
add('hubs factory tier0.7',t07,FDOC,0.7)

# ---- suppliers <-> quickbooks vendors
QBV=f'{EX}/quickbooks/vendors.csv'
qb=list(csv.DictReader(open(QBV)))
sup=[]; qbonly=[]
for r in qb:
    m=re.match(r'sales@([a-z]+)\.example',r['Email'])
    if m and m.group(1).upper() in PRE.values():
        sup.append({'e':['supplier/code',m.group(1).upper()],'a':'quickbooks/vendor','v':r['Vendor']})
    else: qbonly.append({'e':['quickbooks/vendor',r['Vendor']],'a':'quickbooks/vendor','v':r['Vendor']})
assert len(sup)==8 and len(qbonly)==3
add('suppliers',[{'e':['supplier/code',x['e'][1]],'a':'supplier/code','v':x['e'][1]} for x in sup]+sup,[QBV],0.9)
add('qb other vendors',qbonly,[QBV])

# ---- shopify
ORD=f'{EX}/shopify/orders.jsonl'
orders={};lines=[]
for l in open(ORD):
    d=json.loads(l)
    if '__parentId' in d: lines.append(d)
    else: orders[d['id']]=d
cust={}
for o in orders.values():
    c=o['customer']; a=o['shippingAddress'] or {}
    r=cust.setdefault(c['id'],{'email':c['email'],'name':((c['firstName'] or '').strip().lower(),(c['lastName'] or '').strip().lower()),'addr':set(),'first':o['createdAt']})
    r['addr'].add(((a.get('address1') or '').strip().lower(),(a.get('zip') or '').strip()))
    r['first']=min(r['first'],o['createdAt'])
def ne(e):
    u,d=e.lower().strip().split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
order_list=sorted(cust,key=lambda k:(cust[k]['first'],k))
byemail=C.defaultdict(list);byna=C.defaultdict(list)
same=[]
for k in order_list:
    r=cust[k]; cand=[]
    for o in byemail[ne(r['email'])]: cand.append((o,0.9,'email'))
    for a in r['addr']:
        if a[0] and a[1] and all(r['name']):
            for o in byna[(r['name'],a)]: cand.append((o,0.7,'name+address'))
    if cand:
        o,cfd,rule=min(cand,key=lambda x:(cust[x[0]]['first'],-x[1],x[0]))
        same.append((k,o,cfd,rule))
    byemail[ne(r['email'])].append(k)
    for a in r['addr']:
        if a[0] and a[1] and all(r['name']): byna[(r['name'],a)].append(k)
print('same_as',C.Counter(s[3] for s in same),file=sys.stderr)
add('shopify customers',[{'e':['shopify/customer_id',num(k)],'a':'shopify/customer_id','v':num(k)} for k in cust],[ORD])
for cfd in (0.9,0.7):
    add(f'customer same_as {cfd}',[{'e':['shopify/customer_id',num(a)],'a':'core/same_as','v':['shopify/customer_id',num(b)]} for a,b,c,r in same if c==cfd],[ORD],cfd)
of=[]
for o in orders.values():
    n=num(o['id'])
    of+=[{'e':['shopify/order_id',n],'a':'shopify/order_id','v':n},{'e':['shopify/order_id',n],'a':'shopify/order_name','v':o['name']},{'e':['shopify/order_id',n],'a':'order/customer','v':['shopify/customer_id',num(o['customer']['id'])]}]
lf=[]
for d in lines:
    n=num(d['id']);k=['shopify/line_item_id',n]
    assert d['variant']['id'] in var2hub
    lf+=[{'e':k,'a':'shopify/line_item_id','v':n},{'e':k,'a':'core/part_of','v':['shopify/order_id',num(d['__parentId'])]},{'e':k,'a':'line/sku','v':['shopify/variant_id',num(d['variant']['id'])]}]
# ---- 3PL
RC=f'{EX}/3pl/receipts.csv';OB=f'{EX}/3pl/outbound.csv'
rc=list(csv.DictReader(open(RC)))
rf=[];seen=set()
po_re=re.compile(r'^PO-\d{4}-\d{4}$')
for r in rc:
    k=['tpl/receipt_no',r['Receipt #']]
    if r['Receipt #'] not in seen:
        seen.add(r['Receipt #']); rf.append({'e':k,'a':'tpl/receipt_no','v':r['Receipt #']})
        for p in [x.strip() for x in r['Reference'].split('/') if x.strip()]:
            assert po_re.match(p),p
            rf.append({'e':k,'a':'receipt/po','v':['po/number',p]})
    lk=f"{r['Receipt #']}/{r['Item Code']}"
    rf+=[{'e':['tpl/receipt_line',lk],'a':'tpl/receipt_line','v':lk},{'e':['tpl/receipt_line',lk],'a':'core/part_of','v':k},{'e':['tpl/receipt_line',lk],'a':'line/sku','v':['tpl/item_code',r['Item Code']]}]
ob=list(csv.DictReader(open(OB)))
fba_ids={r['Shipment ID'] for r in csv.DictReader(open(f'{EX}/amazon/fba_inbound_shipments.csv'))}
of3=[]
for r in ob:
    ref=r['Order Reference']; lk=f"{ref}/{r['Item Code']}"
    whole=['amazon/fba_shipment_id',ref] if ref.startswith('FBA') else ['shopify/order_name',ref]
    if ref.startswith('FBA'): assert ref in fba_ids
    of3+=[{'e':['tpl/outbound_line',lk],'a':'tpl/outbound_line','v':lk},{'e':['tpl/outbound_line',lk],'a':'core/part_of','v':whole},{'e':['tpl/outbound_line',lk],'a':'line/sku','v':['tpl/item_code',r['Item Code']]}]
# ---- amazon
AO=f'{EX}/amazon/all_orders.txt';FBS=f'{EX}/amazon/fba_inbound_shipments.csv'
ao=list(csv.DictReader(open(AO),delimiter='\t'))
af=[];seen=set()
for r in ao:
    oid=r['amazon-order-id']
    assert re.match(r'^\d{3}-\d{7}-\d{7}$',oid) and r['sku'] in amz2hub
    if oid not in seen: seen.add(oid); af.append({'e':['amazon/order_id',oid],'a':'amazon/order_id','v':oid})
    lk=f"{oid}/{r['sku']}"
    af+=[{'e':['amazon/order_line',lk],'a':'amazon/order_line','v':lk},{'e':['amazon/order_line',lk],'a':'core/part_of','v':['amazon/order_id',oid]},{'e':['amazon/order_line',lk],'a':'line/sku','v':['amazon/seller_sku',r['sku']]}]
add('amazon fba shipments',[{'e':['amazon/fba_shipment_id',x],'a':'amazon/fba_shipment_id','v':x} for x in sorted(fba_ids)],[FBS])
add('shopify orders',of,[ORD]); add('shopify lines',lf,[ORD])
add('3pl receipts+lines',rf,[RC]); add('3pl outbound',of3,[OB]); add('amazon orders+lines',af,[AO])

AUTH={'shopify':['shopify/customer_id','shopify/order_id','shopify/order_name','shopify/line_item_id','shopify/variant_id','order/customer'],
 'amazon':['amazon/order_id','amazon/order_line','amazon/seller_sku','amazon/asin','amazon/fnsku','amazon/fba_shipment_id'],
 '3pl':['tpl/item_code','tpl/receipt_no','tpl/receipt_line','tpl/outbound_line','receipt/po'],
 'quickbooks':['quickbooks/vendor']}
add('authority',[{'e':['fs/ident',a],'a':'core/authoritative_source','v':s} for s,l in AUTH.items() for a in l])

if __name__=='__main__':
    for lab,f in batches: print(lab,len(f))
    json.dump({'hub':hub,'same':same,'amz2hub':amz2hub,'fx':{f'{a}:{b}':v for (a,b),v in fx.items()}},open('catalogue_work/plan.json','w'),indent=1)
