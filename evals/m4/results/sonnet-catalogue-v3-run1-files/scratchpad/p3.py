from common import *
import sys
live = len(sys.argv)>1 and sys.argv[1]=='live'
hubs=json.load(open(S+'/hubs.json'))
var2sku={h['var']:c for c,h in hubs.items()}
item2sku={h['item']:c for c,h in hubs.items()}
amz2sku={}
for r in csv.DictReader(open(X+'/amazon/fba_inventory.txt'),delimiter='\t'): amz2sku[r['sku']]=re.sub(r'-FBA$','',r['sku'])
SK=lambda c:["sku/code",c]
# ---- shopify
orders={};lines=[];cust={}
for l in open(X+'/shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: lines.append(d)
    else: orders[d['id']]=d
cfacts=[];ofacts=[];lfacts=[]
first={}
for o in orders.values():
    c=o['customer']; cid=num(c['id'])
    first[cid]=min(first.get(cid,(o['createdAt'],int(cid))),(o['createdAt'],int(cid)))
for cid in first: cfacts.append({"e":["shopify/customer_id",cid],"a":"shopify/customer_id","v":cid})
for o in orders.values():
    e=["shopify/order_id",num(o['id'])]
    ofacts+=[{"e":e,"a":"shopify/order_id","v":num(o['id'])},{"e":e,"a":"shopify/order_name","v":o['name']},
             {"e":e,"a":"order/customer","v":["shopify/customer_id",num(o['customer']['id'])]}]
for l in lines:
    e=["shopify/line_item_id",num(l['id'])]
    lfacts+=[{"e":e,"a":"shopify/line_item_id","v":num(l['id'])},{"e":e,"a":"core/part_of","v":["shopify/order_id",num(l['__parentId'])]},
             {"e":e,"a":"line/sku","v":SK(var2sku[num(l['variant']['id'])])}]
# duplicates
def norm(e):
    u,d=e.lower().strip().split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
rawmail=collections.defaultdict(set); nm=collections.defaultdict(set); na=collections.defaultdict(set)
for o in orders.values():
    c=o['customer']; cid=num(c['id'])
    if c['email']:
        rawmail[c['email'].lower()].add(cid); nm[norm(c['email'])].add(cid)
    a=o['shippingAddress']
    if a: na[(a['name'].lower().strip(),a['address1'].lower().strip(),a['zip'])].add(cid)
edges={}  # (a,b)->conf
def add(ids,conf):
    ids=sorted(ids,key=lambda i:first[i])
    for x in ids[1:]:
        k=x; edges[k]=max(edges.get(k,(0,))+ (),(conf,ids[0])) if False else edges.get(k)
    return
# union-find by components, survivor = oldest
par={i:i for i in first}
def find(x):
    while par[x]!=x: par[x]=par[par[x]]; x=par[x]
    return x
ev=collections.defaultdict(list)  # cid -> list of conf
for grp,conf in [(rawmail,1),(nm,0.9),(na,0.7)]:
    for ids in grp.values():
        if len(ids)>1:
            for i in ids:
                ev[i].append(conf)
            r=[find(i) for i in ids]
            for x in r: par[x]=par[r[0]]
comp=collections.defaultdict(list)
for i in first: comp[find(i)].append(i)
dups=[]  # (dup, survivor, conf)
tiercount=collections.Counter()
for ids in comp.values():
    if len(ids)<2: continue
    ids.sort(key=lambda i:first[i]); s=ids[0]
    for d in ids[1:]:
        # conf: strongest direct evidence of this dup; if linked only to dups via chain, same evidence applies
        dups.append((d,s,max(ev[d])))
for d,s,c in dups: tiercount[c]+=1
print('orders',len(orders),'lines',len(lines),'customers',len(first),'dups',len(dups),dict(tiercount),'comps',sum(1 for i in comp.values() if len(i)>1))
sd=[X+'/shopify/orders.jsonl']
if live:
    write(cfacts,sd,label='shopify customers')
    write(ofacts,sd,label='shopify orders')
    write(lfacts,sd+[X+'/shopify/products.jsonl'],label='shopify lines')
    for conf in (1,0.9,0.7):
        F=[{"e":["shopify/customer_id",d],"a":"core/same_as","v":["shopify/customer_id",s]} for d,s,c in dups if c==conf]
        if F: write(F,sd,conf,label=f'same_as {conf}')
# ---- amazon
ao=list(csv.DictReader(open(X+'/amazon/all_orders.txt'),delimiter='\t'))
oid={};F=[];G=[]
for r in ao:
    i=r['amazon-order-id']
    if i not in oid: oid[i]=1; F.append({"e":["amazon/order_id",i],"a":"amazon/order_id","v":i})
    k=i+'/'+r['sku']; e=["amazon/order_line_key",k]
    G+=[{"e":e,"a":"amazon/order_line_key","v":k},{"e":e,"a":"core/part_of","v":["amazon/order_id",i]},{"e":e,"a":"line/sku","v":SK(amz2sku[r['sku']])}]
fba=list(csv.DictReader(open(X+'/amazon/fba_inbound_shipments.csv')))
H=[{"e":["amazon/inbound_shipment_id",r['Shipment ID']],"a":"amazon/inbound_shipment_id","v":r['Shipment ID']} for r in fba]
print('amazon orders',len(oid),'lines',len(ao),'fba',len(H))
if live:
    ad=[X+'/amazon/all_orders.txt']
    write(F,ad,label='amazon orders'); write(G,ad,label='amazon lines'); write(H,[X+'/amazon/fba_inbound_shipments.csv'],label='fba shipments')
