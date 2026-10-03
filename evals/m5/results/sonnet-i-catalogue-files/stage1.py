from lib import *
import sys
dry='--dry' in sys.argv
prods=[json.loads(l) for l in open(X+'shopify/products.jsonl')]
vs=[p for p in prods if 'sku' in p]
inv={r['UPC']:r for r in csv.DictReader(open(X+'3pl/inventory_snapshot.csv'))}
hubs={}  # variant id -> dict
for p in vs:
    c=canon(p['sku'])
    hubs[gid(p['id'])]=dict(code=c,exact=(c==p['sku']),upc=p['barcode'],item=inv[p['barcode']]['Item Code'],shop=p['sku'])
assert len({h['code'] for h in hubs.values()})==49
# amazon
ao=list(csv.DictReader(open(X+'amazon/all_orders.txt'),delimiter='\t'))
iv=list(csv.DictReader(open(X+'amazon/fba_inventory.txt'),delimiter='\t'))
code2v={h['code']:v for v,h in hubs.items()}
am={}
for r in iv:
    s=r['sku']; c=canon(re.sub(r'-FBA$','',s.upper()))
    assert c in code2v,(s,c)
    am[s]=dict(code=c,asin=r['asin'],fnsku=r['fnsku'])
asins={}
for r in ao:
    assert r['asin']==am[r['sku']]['asin']
print('amazon hubs',len({a['code'] for a in am.values()}),len(am))
assert len({a['code'] for a in am.values()})==len(am)
hp,hf=doc_facts('shopify/products.jsonl')
hi,hif=doc_facts('3pl/inventory_snapshot.csv')
hai,haif=doc_facts('amazon/fba_inventory.txt')
hao,haof=doc_facts('amazon/all_orders.txt')
docs=[hf,hif,haif,haof]
if not dry: write([f for d in docs for f in d],[])
# tier exact: shopify variant + upc + 3pl item (UPC exact), sku/code when exact
f=[]
for v,h in hubs.items():
    e=["shopify/variant_id",v]
    f+= [{"e":e,"a":"sku/upc","v":h['upc']},{"e":e,"a":"tpl/item_code","v":h['item']}]
    if h['exact']: f.append({"e":e,"a":"sku/code","v":h['code']})
print(write(f,[hp,hi],1,dry=dry))
f=[{"e":["shopify/variant_id",v],"a":"sku/code","v":h['code']} for v,h in hubs.items() if not h['exact']]
print(write(f,[hp,hi],0.9,dry=dry))
# amazon
for tier,cond in ((1,lambda s,a:s==a['code']),(0.9,lambda s,a:s!=a['code'])):
    f=[]
    for s,a in am.items():
        if cond(s,a):
            e=["sku/code",a['code']]
            f+=[{"e":e,"a":"amazon/seller_sku","v":s},{"e":e,"a":"amazon/asin","v":a['asin']},{"e":e,"a":"amazon/fnsku","v":a['fnsku']}]
    print(tier,len(f),write(f,[hai,hao],tier,dry=dry))
json.dump({'hubs':hubs,'am':am},open('w/hubs.json','w'))
