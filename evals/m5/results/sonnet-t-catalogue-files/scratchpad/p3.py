from lib import *
# Amazon orders + lines, FBA shipments
a=list(csv.DictReader(open(EX+'amazon/all_orders.txt'),delimiter='\t'))
f=[]
for x in a:
    k=x['amazon-order-id']+'/'+x['sku']
    f+=[{'e':['amazon/order_line',k],'a':'core/part_of','v':['amazon/order_id',x['amazon-order-id']]},
        {'e':['amazon/order_line',k],'a':'line/listing','v':['amazon/seller_sku',x['sku']]}]
write(f,'amazon/all_orders.txt')
fb=[r['Shipment ID'] for r in csv.DictReader(open(EX+'amazon/fba_inbound_shipments.csv'))]
assert len(set(fb))==len(fb)
write([{'e':['amazon/fba_shipment_id',s],'a':'amazon/fba_shipment_id','v':s} for s in fb],'amazon/fba_inbound_shipments.csv')
# 3PL
vm={}
for i in csv.DictReader(open(EX+'3pl/inventory_snapshot.csv')): vm[i['Item Code']]=i['UPC']
prods=[json.loads(l) for l in open(EX+'shopify/products.jsonl')]
u2h={p['barcode']:hubcode(p['sku']) for p in prods if 'ProductVariant/' in p['id']}
i2h={k:u2h[u] for k,u in vm.items()}
rc=list(csv.DictReader(open(EX+'3pl/receipts.csv')))
f=[];seen=set()
for r in rc:
    rn=r['Receipt #'];k=rn+'/'+r['Item Code']
    assert k not in seen;seen.add(k)
    f+=[{'e':['tpl/receipt_line',k],'a':'core/part_of','v':['tpl/receipt_no',rn]},
        {'e':['tpl/receipt_line',k],'a':'line/sku','v':['sku/code',i2h[r['Item Code']]]}]
for rn,refs in {r['Receipt #']:r['Reference'] for r in rc}.items():
    for p in re.split(r'\s*/\s*',refs):
        if p:
            assert re.fullmatch(r'PO-\d{4}-\d{4}',p),p
            f.append({'e':['tpl/receipt_no',rn],'a':'receipt/po','v':['po/number',p]})
write(f,'3pl/receipts.csv')
ob=list(csv.DictReader(open(EX+'3pl/outbound.csv')))
fbs=set(fb);f=[];seen=set()
for o in ob:
    k=o['Order Reference']+'/'+o['Item Code']; assert k not in seen; seen.add(k)
    parent=['amazon/fba_shipment_id',o['Order Reference']] if o['Order Reference'] in fbs else ['shopify/order_name',o['Order Reference']]
    f+=[{'e':['tpl/outbound_line',k],'a':'core/part_of','v':parent},
        {'e':['tpl/outbound_line',k],'a':'line/sku','v':['sku/code',i2h[o['Item Code']]]}]
write(f,'3pl/outbound.csv')
