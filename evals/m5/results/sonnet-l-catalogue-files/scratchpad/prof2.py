import json,re,csv,collections as C
pat=re.compile(r'AH-[A-Z]{3}-\d{4}-[A-Z]{3}')
P=[json.loads(l) for l in open('shopify/products.jsonl')]
V={p['sku']:p for p in P if 'ProductVariant' in p['id']}
inv=list(csv.DictReader(open('3pl/inventory_snapshot.csv')))
print('3pl inv',len(inv),len({r['Item Code'] for r in inv}),len({r['UPC'] for r in inv}))
for r in inv:
    if not pat.fullmatch(r['Client SKU']) or r['Client SKU'] not in V: print(' inv odd',r['Item Code'],r['Client SKU'],r['UPC'])
byupc={p['barcode']:p['sku'] for p in V.values()}
for r in inv:
    if byupc.get(r['UPC'])!=r['Client SKU']: print(' upc mismatch',r['Client SKU'],byupc.get(r['UPC']),r['UPC'])
print('shop upc not in 3pl',[s for u,s in byupc.items() if u not in {r['UPC'] for r in inv}])
ob=list(csv.DictReader(open('3pl/outbound.csv')))
c=C.Counter((r['Item Code'],r['Client SKU']) for r in ob); ic={r['Item Code'] for r in inv}
print('outbound pairs',len(c)); 
for k,n in c.items():
    if k[0] not in ic or not pat.fullmatch(k[1]): print(' ob odd',k,n)
print(C.Counter(re.sub(r'\d','9',r['Order Reference']) for r in ob).most_common(10))
rc=list(csv.DictReader(open('3pl/receipts.csv')))
print('rcpt',len(rc),len({r['Receipt #'] for r in rc}),len({(r['Receipt #'],r['Item Code']) for r in rc}))
print(C.Counter(r['Reference'] for r in rc).most_common(60))
for k in {(r['Item Code'],r['Client SKU']) for r in rc}:
    if k[0] not in ic: print(' rc odd',k)
am=list(csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'))
print('amz',len(am),len({r['amazon-order-id'] for r in am}),len({(r['amazon-order-id'],r['sku']) for r in am}))
sk=C.Counter(r['sku'] for r in am); print(len(sk))
for s,n in sorted(sk.items()): print('  ',s,n,s in V, len({r['asin'] for r in am if r['sku']==s}))
fi=list(csv.DictReader(open('amazon/fba_inventory.txt'),delimiter='\t'))
for r in fi: print(' fba',r['sku'],r['fnsku'],r['asin'])
