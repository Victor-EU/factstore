from common import *
import sys
live = len(sys.argv)>1 and sys.argv[1]=='live'
parents,vs=load_products()
tp={r['UPC']:r for r in csv.DictReader(open(X+'/3pl/inventory_snapshot.csv'))}
amz=list(csv.DictReader(open(X+'/amazon/fba_inventory.txt'),delimiter='\t'))
# hubs
hubs={}  # canon -> dict
for v in vs:
    c=canon(v['sku']); assert c not in hubs
    t=tp[v['barcode']]
    hubs[c]=dict(code=c,exact=(v['sku']==c),upc=v['barcode'],var=num(v['id']),item=t['Item Code'])
# amazon
am={}
for r in amz:
    s=r['sku']; base=re.sub(r'-FBA$','',s)
    assert base in hubs,s
    assert base not in am
    am[base]=(s,r['asin'],r['fnsku'],s==base)
# every sku in orders in inventory
osk={r['sku'] for r in csv.DictReader(open(X+'/amazon/all_orders.txt'),delimiter='\t')}
assert osk=={r[0] for r in am.values()},osk^{r[0] for r in am.values()}
# 3pl item codes referenced elsewhere exist
def hubfacts(h):
    e=["sku/code",h['code']]
    return [{"e":e,"a":"sku/code","v":h['code']},{"e":e,"a":"sku/family","v":h['code'].split('-')[1]},
            {"e":e,"a":"sku/upc","v":h['upc']},{"e":e,"a":"shopify/variant_id","v":h['var']},{"e":e,"a":"tpl/item_code","v":h['item']}]
docs=[X+'/shopify/products.jsonl',X+'/3pl/inventory_snapshot.csv']
A=[f for h in hubs.values() if h['exact'] for f in hubfacts(h)]
B=[f for h in hubs.values() if not h['exact'] for f in hubfacts(h)]
print(len(hubs),sum(h['exact'] for h in hubs.values()),[ (h['code']) for h in hubs.values() if not h['exact']])
C=[];D=[]
for c,(s,asin,fn,ex) in am.items():
    e=["sku/code",c]
    L=C if ex else D
    L+= [{"e":e,"a":"amazon/seller_sku","v":s},{"e":e,"a":"amazon/asin","v":asin},{"e":e,"a":"amazon/fnsku","v":fn}]
print(len(C)//3,len(D)//3)
adocs=[X+'/amazon/fba_inventory.txt']
if live:
    write(A,docs,1,label='A shopify+3pl exact via UPC, clean code')
    write(B,docs,0.9,label='B shopify malformed code normalized')
    write(C,adocs,1,label='C amazon exact')
    write(D,adocs,0.9,label='D amazon -FBA')
json.dump({c:h for c,h in hubs.items()},open(S+'/hubs.json','w'))
