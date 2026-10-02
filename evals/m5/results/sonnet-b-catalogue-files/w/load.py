import sys,json,csv,re,hashlib,glob,collections as C
sys.path.insert(0,'../w')
import factstore
from build_hubs import *   # hubs, fmap, canon2, vs, T
SHOP='shopify/orders.jsonl'
def H(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def ev(p): return ["document/hash",H(p)]
def tx(facts,evid=(),conf=None,chunk=3000):
  """write facts in chunks; each chunk is a tx stamped with evidence/confidence"""
  for i in range(0,len(facts),chunk):
    f=list(facts[i:i+chunk])
    for e in evid: f.append({"e":"tmp:tx","a":"core/evidence","v":e})
    if conf is not None: f.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
    r=factstore.transact(f); print(len(f),r if not isinstance(r,dict) else {k:r[k] for k in list(r)[:3]})
def fa(e,a,v): return {"e":e,"a":a,"v":v}
step=sys.argv[1]
files=['shopify/products.jsonl',SHOP,'amazon/all_orders.txt','amazon/fba_inventory.txt','amazon/fba_inbound_shipments.csv','3pl/inventory_snapshot.csv','3pl/receipts.csv','3pl/outbound.csv','quickbooks/vendors.csv']+['supplier_docs/'+f for f in sorted(T) if f.startswith('CI-PL')]
if step=='docs':
  F=[]
  for p in files: F+= [fa(ev(p),"document/url",p)]
  tx(F)
  sys.exit()
sku=lambda c:["sku/code",c]
if step=='hubs':
  tx([fa(sku(h),"sku/code",h) for h in sorted(hubs)],[ev('shopify/products.jsonl')],1)
  sup=sorted(set(p for p,_ in fmap))
  tx([fa(["supplier/code",s],"supplier/code",s) for s in sup],[ev('supplier_docs/'+f) for f in sorted(T) if f.startswith('CI-PL')][:1],1)
if step=='crosswalk':
  inv=list(csv.DictReader(open('3pl/inventory_snapshot.csv')))
  upc2h={}
  for h,d in hubs.items(): upc2h[d['shop']['barcode']]=h
  tpl={}
  for r in inv: tpl[upc2h[r['UPC']]]=r
  # amazon
  fi=list(csv.DictReader(open('amazon/fba_inventory.txt'),delimiter='\t'))
  amz={}
  for r in fi:
    h=canon2(r['sku']); assert h in hubs and h not in amz; amz[h]=r
  ex=[];no=[]
  for h,d in hubs.items():
    s=d['shop']; vid=s['id'].split('/')[-1]
    (ex if s['sku']==h else no).append(fa(sku(h),"shopify/variant_id",vid))
  ex+= [fa(sku(h),"sku/upc",d['shop']['barcode']) for h,d in hubs.items()]
  ex+= [fa(sku(h),"tpl/item_code",r['Item Code']) for h,r in tpl.items()]
  for h,r in amz.items():
    t=ex if r['sku']==h else no
    t+= [fa(sku(h),"amazon/seller_sku",r['sku']),fa(sku(h),"amazon/asin",r['asin']),fa(sku(h),"amazon/fnsku",r['fnsku'])]
  print(len(ex),len(no))
  evs=[ev('shopify/products.jsonl'),ev('3pl/inventory_snapshot.csv'),ev('amazon/fba_inventory.txt')]
  tx(ex,evs,1); tx(no,evs,0.9)
  # tpl spelling check for 3pl differing client sku -> already via UPC
  fo=[]
  for (p,item),(h,desc,hs) in sorted(fmap.items()):
    fo+=[fa(sku(h),"factory/item_code",f"{p}:{item}"),fa(sku(h),"sku/supplier",["supplier/code",p]),fa(sku(h),"sku/hs_code",hs)]
  tx(fo,[ev('supplier_docs/'+f) for f in sorted(T) if f.startswith('CI-PL')],0.7)
  # quickbooks vendors
  vend=list(csv.DictReader(open('quickbooks/vendors.csv')))
  pm={}
  for v in vend:
    m=re.match(r'.*@(\w+)\.example',v['Email'])
    code=m.group(1).upper() if m else None
    if code and any(p==code for p,_ in fmap): pm[v['Vendor']]=code
  print(pm)
  tx([fa(["supplier/code",c],"quickbooks/vendor_name",n) for n,c in pm.items()],[ev('quickbooks/vendors.csv')],0.9)
  tx([fa(["quickbooks/vendor_name",v['Vendor']],"quickbooks/vendor_name",v['Vendor']) for v in vend if v['Vendor'] not in pm],[ev('quickbooks/vendors.csv')])
  fs=lambda a,s:fa(["fs/ident",a],"core/authoritative_source",s)
  tx([fs(a,'shopify') for a in ["shopify/variant_id","shopify/order_id","shopify/order_name","shopify/customer_id","shopify/line_item_id"]]+
     [fs(a,'amazon') for a in ["amazon/asin","amazon/fnsku","amazon/seller_sku","amazon/order_id","amazon/order_line_key","amazon/inbound_shipment_id"]]+
     [fs(a,'3pl') for a in ["tpl/item_code","tpl/receipt_no","tpl/receipt_line_key"]]+[fs("quickbooks/vendor_name",'quickbooks')])
def nid(g): return g.split('/')[-1]
if step in('orders','dups'):
  O=[];Ls=[]
  for l in open(SHOP):
    d=json.loads(l); (Ls if d['id'].startswith('gid://shopify/LineItem') else O).append(d)
if step=='orders':
  e=[ev(SHOP)]
  cust=sorted({nid(o['customer']['id']) for o in O})
  tx([fa(["shopify/customer_id",c],"shopify/customer_id",c) for c in cust],e,chunk=5000)
  F=[]
  for o in O:
    k=["shopify/order_id",nid(o['id'])]
    F+=[fa(k,"shopify/order_id",nid(o['id'])),fa(k,"shopify/order_name",o['name']),fa(k,"order/customer",["shopify/customer_id",nid(o['customer']['id'])])]
  tx(F,e,chunk=5000)
  F=[]
  for l in Ls:
    k=["shopify/line_item_id",nid(l['id'])]
    F+=[fa(k,"shopify/line_item_id",nid(l['id'])),fa(k,"core/part_of",["shopify/order_id",nid(l['__parentId'])]),fa(k,"line/sku",sku(canon2(l['sku'])))]
  tx(F,e,chunk=5000)
if step=='amazon':
  A=list(csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'))
  e=[ev('amazon/all_orders.txt')]
  oids=sorted({r['amazon-order-id'] for r in A})
  tx([fa(["amazon/order_id",o],"amazon/order_id",o) for o in oids],e,chunk=5000)
  F=[]
  for r in A:
    k=["amazon/order_line_key",r['amazon-order-id']+'/'+r['sku']]
    F+=[fa(k,"amazon/order_line_key",k[1]),fa(k,"core/part_of",["amazon/order_id",r['amazon-order-id']]),fa(k,"line/sku",sku(canon2(r['sku'])))]
  tx(F,e,chunk=5000)
  fb=list(csv.DictReader(open('amazon/fba_inbound_shipments.csv')))
  tx([fa(["amazon/inbound_shipment_id",r['Shipment ID']],"amazon/inbound_shipment_id",r['Shipment ID']) for r in fb],[ev('amazon/fba_inbound_shipments.csv')])
if step=='receipts':
  rc=list(csv.DictReader(open('3pl/receipts.csv')))
  e=[ev('3pl/receipts.csv')]
  upc2h={d['shop']['barcode']:h for h,d in hubs.items()}
  inv={r['Item Code']:upc2h[r['UPC']] for r in csv.DictReader(open('3pl/inventory_snapshot.csv'))}
  F=[];seen={}
  for r in rc:
    k=["tpl/receipt_no",r['Receipt #']]
    F.append(fa(k,"tpl/receipt_no",r['Receipt #']))
    if r['Reference']:
      assert seen.setdefault(r['Receipt #'],r['Reference'])==r['Reference']
      F.append(fa(k,"receipt/po",["po/number",r['Reference']]))
    lk=["tpl/receipt_line_key",r['Receipt #']+'/'+r['Item Code']]
    F+=[fa(lk,"tpl/receipt_line_key",lk[1]),fa(lk,"core/part_of",k),fa(lk,"line/sku",sku(inv[r['Item Code']]))]
  tx(F,e)
if step=='dups':
  def ne(e):
    e=e.lower(); u,d=e.split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
  first={};info={}
  for o in sorted(O,key=lambda o:o['createdAt']):
    c=o['customer'];i=nid(c['id']);first.setdefault(i,o['createdAt'])
    sa=o.get('shippingAddress') or {}
    info.setdefault(i,{'em':set(),'na':set()})
    info[i]['em'].add(ne(c['email']))
    info[i]['na'].add((c['firstName'].lower(),c['lastName'].lower(),sa.get('address1','').lower(),sa.get('zip')))
  par={i:i for i in info}
  def f(x):
    while par[x]!=x: par[x]=par[par[x]]; x=par[x]
    return x
  by=C.defaultdict(list)
  for i,d in info.items():
    for em in d['em']: by[('e',em)].append(i)
    for na in d['na']:
      if na[2] and na[3]: by[('n',na)].append(i)
  for k,v in by.items():
    for x in v[1:]: par[f(x)]=f(v[0])
  cl=C.defaultdict(list)
  for i in info: cl[f(i)].append(i)
  out={0.9:[],0.7:[]}; sizes=C.Counter()
  for m in cl.values():
    if len(m)<2: continue
    sizes[len(m)]+=1
    m.sort(key=lambda i:(first[i],i)); root=m[0]
    for d in m[1:]:
      conf=0.9 if info[d]['em']&info[root]['em'] else 0.7
      out[conf].append(fa(["shopify/customer_id",d],"core/same_as",["shopify/customer_id",root]))
  print(sizes,{k:len(v) for k,v in out.items()})
  if len(sys.argv)>2:
    for c,fl in out.items(): tx(fl,[ev(SHOP)],c)
