import sys,json
exec(open('cust.py').read().split("print(len(cu)")[0])
from common import *
import re
dry='--go' not in sys.argv
gid=lambda g:g.rsplit('/',1)[1]
def root(d):
    s=pairs[d][0]
    while s in pairs: s=pairs[s][0]
    return s
P=[json.loads(l) for l in open(EX+'shopify/products.jsonl')]
sk=json.load(open('skutx.json'))
v2hub={}
for f in sk['tx1']+sk['tx2']:
    if f['a']=='shopify/variant_id': v2hub[f['v']]=f['e'][1]
L=[]
for l in open(EX+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: L.append(d)
assert all(gid(x['variant']['id']) in v2hub for x in L)
cf=[{"e":["shopify/customer_id",gid(k)],"a":"shopify/customer_id","v":gid(k)} for k in cu]
of=[]
for o in O.values():
    e=["shopify/order_id",gid(o['id'])]
    of+=[{"e":e,"a":"shopify/order_id","v":gid(o['id'])},{"e":e,"a":"order/customer","v":["shopify/customer_id",gid(o['customer']['id'])]}]
lf=[]
for x in L:
    e=["shopify/line_item_id",gid(x['id'])]
    lf+=[{"e":e,"a":"shopify/line_item_id","v":gid(x['id'])},{"e":e,"a":"core/part_of","v":["shopify/order_id",gid(x['__parentId'])]},{"e":e,"a":"line/sku","v":["sku/code",v2hub[gid(x['variant']['id'])]]}]
dup={0.9:[],0.7:[]}
for d in pairs:
    t=pairs[d][1]
    dup[t if t!=1 else 0.9].append({"e":["shopify/customer_id",gid(d)],"a":"core/same_as","v":["shopify/customer_id",gid(root(d))]})
print(len(cf),len(of)//2,len(lf)//3,{k:len(v) for k,v in dup.items()})
if not dry:
    R=['shopify/orders.jsonl']
    for facts,c in [(cf,None),(of,None),(lf,None),(dup[0.9],0.9),(dup[0.7],0.7)]:
        for r in write(facts,R,c,chunk=5000): print(r.tx)
