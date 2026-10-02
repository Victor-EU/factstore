import json,csv,collections as C
P='exports/'
vars_=[json.loads(l) for l in open(P+'shopify/products.jsonl')]
vars_=[v for v in vars_ if 'ProductVariant' in v['id']]
hub={v['sku'] for v in vars_}; upc={v['barcode']:v['sku'] for v in vars_}
def rd(f,**k): return list(csv.DictReader(open(P+f,encoding='utf-8-sig'),**k))
inv=rd('3pl/inventory_snapshot.csv'); rc=rd('3pl/receipts.csv'); ob=rd('3pl/outbound.csv')
print('inv',len(inv),len({r['Item Code'] for r in inv}),[r['Client SKU'] for r in inv if r['Client SKU'] not in hub])
print('inv upc mismatch',[(r['Client SKU'],upc.get(r['UPC'])) for r in inv if upc.get(r['UPC'])!=r['Client SKU']])
print('rc cols',len(rc),len({(r['Receipt #'],r['Item Code']) for r in rc}),len({r['Receipt #'] for r in rc}))
print('rc sku bad',C.Counter(r['Client SKU'] for r in rc if r['Client SKU'] not in hub))
print('rc ref',C.Counter(r['Reference'] for r in rc).most_common(60))
print('ob',len(ob),len({(r['Order Reference'],r['Item Code']) for r in ob}))
print('ob sku bad',C.Counter(r['Client SKU'] for r in ob if r['Client SKU'] not in hub))
print('ob ref non-#',C.Counter(r['Order Reference'] for r in ob if not r['Order Reference'].startswith('#')).most_common(60))
ic={r['Item Code']:r['Client SKU'] for r in inv}
print('item code vs sku mismatch', {(r['Item Code'],r['Client SKU']) for r in rc+ob if ic.get(r['Item Code'])!=r['Client SKU']})
print('blank refs', sum(1 for r in ob if not r['Order Reference'].strip()))
