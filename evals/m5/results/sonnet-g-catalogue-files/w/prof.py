import json,csv,collections as C
P='exports/'
prods=[json.loads(l) for l in open(P+'shopify/products.jsonl')]
vars_=[p for p in prods if 'ProductVariant' in p['id']]
print(len(prods),len(vars_), len({v['sku'] for v in vars_}), len({v['barcode'] for v in vars_}))
orders={};lines=[];custs=C.defaultdict(set)
for l in open(P+'shopify/orders.jsonl'):
    r=json.loads(l)
    if '/Order/' in r['id']: orders[r['id']]=r
    elif '/LineItem/' in r['id']: lines.append(r)
print(len(orders),len(lines),len({l['id'] for l in lines}))
print(C.Counter(bool(o.get('customer')) for o in orders.values()))
cu={o['customer']['id'] for o in orders.values() if o.get('customer')}
print('cust',len(cu), 'names',len({o['name'] for o in orders.values()}))
print('line var None',sum(1 for l in lines if not l.get('variant')), 'sku blank',sum(1 for l in lines if not l.get('sku')))
vs={v['sku'] for v in vars_}
print('line skus not in variants',C.Counter(l['sku'] for l in lines if l['sku'] not in vs).most_common(10))
print('line variant not in',sum(1 for l in lines if l.get('variant') and l['variant']['id'] not in {v['id'] for v in vars_}))
print(C.Counter(l['__parentId'] in orders for l in lines))
