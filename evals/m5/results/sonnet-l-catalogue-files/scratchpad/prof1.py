import json,re,collections as C
P=[json.loads(l) for l in open('shopify/products.jsonl')]
vars_=[p for p in P if 'ProductVariant' in p['id']]
print(len(P),len(vars_),len({v['sku'] for v in vars_}),len({v['barcode'] for v in vars_}))
print([v['sku'] for v in vars_ if not re.fullmatch(r'AH-[A-Z]{3}-\d{4}-[A-Z]{3}',v['sku'] or '')])
O=[json.loads(l) for l in open('shopify/orders.jsonl')]
orders=[o for o in O if '/Order/' in o['id']]; lines=[o for o in O if '/LineItem/' in o['id']]
print(len(orders),len(lines),len({o['id'] for o in orders}),len({o['name'] for o in orders}),len({l['id'] for l in lines}))
print(C.Counter(type(o.get('customer')).__name__ for o in orders))
cs={o['customer']['id'] for o in orders if o.get('customer')}; print(len(cs))
print(C.Counter(bool(l.get('variant')) for l in lines), C.Counter(bool(l.get('sku')) for l in lines))
vs={v['id'] for v in vars_}; print(len({l['variant']['id'] for l in lines if l.get('variant')}-vs))
sk={v['sku'] for v in vars_}; print(C.Counter(l['sku'] for l in lines if l['sku'] not in sk).most_common(20))
