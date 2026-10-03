import json,re,csv,collections as C
O=[json.loads(l) for l in open('shopify/orders.jsonl')]
orders=[o for o in O if '/Order/' in o['id']]
names={o['name'] for o in orders}
ob=list(csv.DictReader(open('3pl/outbound.csv')))
k=C.Counter((r['Order Reference'],r['Item Code']) for r in ob)
print('ob rows',len(ob),'distinct keys',len(k))
refs={r['Order Reference'] for r in ob}
print('refs not shop',[r for r in refs if r.startswith('#') and r not in names][:10], len([r for r in refs if r.startswith('#') and r not in names]))
print('other refs',sorted(r for r in refs if not r.startswith('#') and not re.fullmatch(r'FBA[0-9A-Z]{8}',r)))
fb=list(csv.DictReader(open('amazon/fba_inbound_shipments.csv'))); fid={r['Shipment ID'] for r in fb}
print('fba ids',len(fb),len(fid),'ob fba refs not in file',[r for r in refs if r.startswith('FBA') and r not in fid])
print('fba file ids not in ob',len(fid-refs))
print('blank/odd shipids',[r for r in fid if not re.fullmatch(r'FBA[0-9A-Z]{8}',r)])
rc=list(csv.DictReader(open('3pl/receipts.csv')))
pos=set()
for r in rc:
    for p in re.split(r'\s*/\s*',r['Reference']):
        if p: pos.add(p)
print(sorted(pos)); print({r['Receipt #'] for r in rc if not r['Reference']})
print(C.Counter(re.sub(r'\d','9',r['Receipt #']) for r in rc))
# amazon
am=list(csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'))
print(C.Counter(re.sub(r'\d','9',r['amazon-order-id']) for r in am))
print(C.Counter(r['fulfillment-channel'] for r in am),C.Counter(r['order-status'] for r in am), sum(1 for r in am if r['merchant-order-id']))
fi={r['sku']:r for r in csv.DictReader(open('amazon/fba_inventory.txt'),delimiter='\t')}
bad=[(r['sku'],r['asin']) for r in am if r['sku'] in fi and fi[r['sku']]['asin']!=r['asin']]; print('asin mismatch',len(bad),set(bad))
print('asin dup',[a for a,n in C.Counter(r['asin'] for r in fi.values()).items() if n>1],'fnsku dup',[a for a,n in C.Counter(r['fnsku'] for r in fi.values()).items() if n>1])
print('blank in fi', [r['sku'] for r in fi.values() if not r['fnsku'] or not r['asin']])
# customers
cust={}
for o in orders:
    c=o['customer']; cust.setdefault(c['id'],set()).add((c['email'] or '').lower())
print(len(cust),sum(1 for v in cust.values() if len(v)>1), sum(1 for o in orders if not o['customer'].get('id')))
