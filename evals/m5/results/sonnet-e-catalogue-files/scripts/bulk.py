import sys;sys.path.insert(0,'scripts')
from common import *
DRY='--dry' in sys.argv; LIMIT=int(sys.argv[sys.argv.index('--limit')+1]) if '--limit' in sys.argv else None
prods,vars_=shopify_products()
v2hub={gid(v['id']):hub_code(v['sku']) for v in vars_}
H=lambda c:['sku/code',c]
# ---- Shopify
orders=[];lines=[]
for l in open(EX+'shopify/orders.jsonl'):
    d=json.loads(l); (lines if '__parentId' in d else orders).append(d)
if LIMIT: orders=orders[:LIMIT]; ids={o['id'] for o in orders}; lines=[l for l in lines if l['__parentId'] in ids]
f=[]; custs={}
for o in orders:
    oid=gid(o['id']); e=['shopify/order_id',oid]
    f+=[{'e':e,'a':'shopify/order_id','v':oid},{'e':e,'a':'shopify/order_name','v':o['name']}]
    c=o['customer']
    if c:
        cid=gid(c['id']); f+=[{'e':['shopify/customer_id',cid],'a':'shopify/customer_id','v':cid},{'e':e,'a':'order/customer','v':['shopify/customer_id',cid]}]
    else: print('no customer',o['name'])
write(f,['shopify/orders.jsonl'],dry=DRY); print('shopify orders',len(orders))
f=[]
for l in lines:
    lid=gid(l['id']); e=['shopify/line_item_id',lid]
    f+=[{'e':e,'a':'shopify/line_item_id','v':lid},{'e':e,'a':'core/part_of','v':['shopify/order_id',gid(l['__parentId'])]},{'e':e,'a':'line/sku','v':H(v2hub[gid(l['variant']['id'])])}]
write(f,['shopify/orders.jsonl'],dry=DRY); print('shopify lines',len(lines))
# ---- Amazon
A=list(csv.DictReader(open(EX+'amazon/all_orders.txt'),delimiter='\t'))
if LIMIT: A=A[:LIMIT]
f=[]
for r in A:
    oid=r['amazon-order-id']; k=f"{oid}/{r['sku']}"; e=['amazon/order_line',k]
    f+=[{'e':['amazon/order_id',oid],'a':'amazon/order_id','v':oid},{'e':e,'a':'amazon/order_line','v':k},{'e':e,'a':'core/part_of','v':['amazon/order_id',oid]},{'e':e,'a':'line/sku','v':H(hub_code(r['sku']))}]
write(f,['amazon/all_orders.txt'],dry=DRY); print('amazon lines',len(A))
F=list(csv.DictReader(open(EX+'amazon/fba_inbound_shipments.csv')))
write([{'e':['amazon/fba_shipment_id',r['Shipment ID']],'a':'amazon/fba_shipment_id','v':r['Shipment ID']} for r in F],['amazon/fba_inbound_shipments.csv'],dry=DRY)
# ---- 3PL
item2hub={r['Item Code']:hub_code(r2) for r in csv.DictReader(open(EX+'3pl/inventory_snapshot.csv')) for r2 in [r['Client SKU'] or None] if r2} 
upc2hub={v['barcode']:hub_code(v['sku']) for v in vars_}
item2hub={r['Item Code']:upc2hub[r['UPC']] for r in csv.DictReader(open(EX+'3pl/inventory_snapshot.csv'))}
R=list(csv.DictReader(open(EX+'3pl/receipts.csv')))
f=[];seenpo=collections.Counter()
for r in R:
    rn=r['Receipt #']; k=f"{rn}/{r['Item Code']}"; e=['tpl/receipt_line',k]
    f+=[{'e':['tpl/receipt_no',rn],'a':'tpl/receipt_no','v':rn},{'e':e,'a':'tpl/receipt_line','v':k},{'e':e,'a':'core/part_of','v':['tpl/receipt_no',rn]},{'e':e,'a':'line/sku','v':H(item2hub[r['Item Code']])}]
    for po in [p.strip() for p in r['Reference'].split('/') if p.strip()]:
        assert re.fullmatch(r'PO-\d{4}-\d{4}',po),po; seenpo[po]+=1
        f.append({'e':['tpl/receipt_no',rn],'a':'receipt/po','v':['po/number',po]})
write(f,['3pl/receipts.csv'],dry=DRY); print('receipt lines',len(R),'distinct POs',len(seenpo))
O=list(csv.DictReader(open(EX+'3pl/outbound.csv')))
if LIMIT: O=O[:LIMIT]
f=[]
for r in O:
    ref=r['Order Reference']; k=f"{ref}/{r['Item Code']}"; e=['tpl/outbound_line',k]
    whole=['shopify/order_name',ref] if ref.startswith('#') else ['amazon/fba_shipment_id',ref]
    f+=[{'e':e,'a':'tpl/outbound_line','v':k},{'e':e,'a':'core/part_of','v':whole},{'e':e,'a':'line/sku','v':H(item2hub[r['Item Code']])}]
write(f,['3pl/outbound.csv'],dry=DRY); print('outbound lines',len(O))
