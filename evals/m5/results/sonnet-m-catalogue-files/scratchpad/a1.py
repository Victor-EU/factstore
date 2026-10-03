import json,csv,collections as C
prod=[json.loads(l) for l in open('shopify/products.jsonl')]
var=[p for p in prod if 'ProductVariant' in p['id']]
print(len(var), len({v['sku'] for v in var}), len({v['id'] for v in var}), [v['sku'] for v in var if not v['sku']])
hub={v['sku'] for v in var}
orders=[];lines=[]
for l in open('shopify/orders.jsonl'):
    d=json.loads(l)
    (lines if 'LineItem' in d['id'] else orders).append(d)
oid={o['id'] for o in orders}
print(len(orders),len(oid),len({o['name'] for o in orders}),len(lines),len({l['id'] for l in lines}))
cu=[o['customer'] for o in orders if o['customer']]
print('nocust',len(orders)-len(cu),len({c['id'] for c in cu}))
ls=C.Counter(l['sku'] for l in lines); print('shopify line skus not in hub',{k:v for k,v in ls.items() if k not in hub})
print('line variant none',sum(1 for l in lines if not l['variant']))
print('orphan lines',sum(1 for l in lines if l['__parentId'] not in oid))
t=list(csv.DictReader(open('3pl/inventory_snapshot.csv')))
print('3pl inv',len(t),{r['Client SKU'] for r in t}-hub, hub-{r['Client SKU'] for r in t})
ob=list(csv.DictReader(open('3pl/outbound.csv')))
print('ob skus off',C.Counter(r['Client SKU'] for r in ob if r['Client SKU'] not in hub))
print('ob codes',len({r['Item Code'] for r in ob}), len({r['Item Code'] for r in t}))
print(C.Counter(r['Order Reference'][:3] for r in ob).most_common(6))
k=C.Counter((r['Order Reference'],r['Item Code']) for r in ob); print('dup keys',sum(1 for v in k.values() if v>1))
rc=list(csv.DictReader(open('3pl/receipts.csv')))
print('rc off',C.Counter(r['Client SKU'] for r in rc if r['Client SKU'] not in hub)); print(C.Counter(r['Reference'] for r in rc).most_common(40))
