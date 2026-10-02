import json,csv,collections as C,re
P='exports/'
vars_=[json.loads(l) for l in open(P+'shopify/products.jsonl')]
vars_=[v for v in vars_ if 'ProductVariant' in v['id']]
hub={v['sku'] for v in vars_}
def rd(f,**k): return list(csv.DictReader(open(P+f,encoding='utf-8-sig'),**k))
rc=rd('3pl/receipts.csv'); ob=rd('3pl/outbound.csv')
g=C.defaultdict(set)
for r in rc: g[r['Receipt #']].add(r['Reference'])
print({k:v for k,v in g.items() if len(v)>1})
print({k:v for k,v in g.items() if '' in v})
print(set(len(r['Received Date']) for r in rc))
orders=set()
for l in open(P+'shopify/orders.jsonl'):
    r=json.loads(l)
    if '/Order/' in r['id']: orders.add(r['name'])
print('ob # not in shopify',[r['Order Reference'] for r in ob if r['Order Reference'].startswith('#') and r['Order Reference'] not in orders][:10])
fb=rd('amazon/fba_inbound_shipments.csv'); fbi={r['Shipment ID'] for r in fb}
print('fba',len(fb),len(fbi),'ob fba missing',{r['Order Reference'] for r in ob if r['Order Reference'][0]=='F' and r['Order Reference'] not in fbi})
print('ob fba count',len({r['Order Reference'] for r in ob if r['Order Reference'][0]=='F'}))
inv=list(csv.DictReader(open(P+'amazon/fba_inventory.txt'),delimiter='\t'))
print('ainv',len(inv),len({r['sku'] for r in inv}),len({r['fnsku'] for r in inv}),len({r['asin'] for r in inv}))
for r in inv: print(r['sku'],r['fnsku'],r['asin'])
ao=list(csv.DictReader(open(P+'amazon/all_orders.txt'),delimiter='\t'))
print('ao',len(ao),len({r['amazon-order-id'] for r in ao}),len({(r['amazon-order-id'],r['sku']) for r in ao}))
sk=C.Counter(r['sku'] for r in ao); print(len(sk)); 
for s,n in sorted(sk.items()): print(s,n,s in hub)
am=C.defaultdict(set)
for r in ao: am[r['sku']].add(r['asin'])
print({k:v for k,v in am.items() if len(v)>1})
print(C.Counter(bool(r['amazon-order-id']) for r in ao), [r for r in ao if not re.match(r'^\d{3}-\d{7}-\d{7}$',r['amazon-order-id'])][:3])
