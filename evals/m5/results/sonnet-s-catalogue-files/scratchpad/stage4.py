from common import *
# Amazon orders + lines
rows=list(csv.DictReader(open(X+'amazon/all_orders.txt'),delimiter='\t'))
bad=[r['amazon-order-id'] for r in rows if not re.fullmatch(r'\d{3}-\d{7}-\d{7}',r['amazon-order-id'])]
badsku=[r['sku'] for r in rows if not r['sku']]
print('bad ids',bad[:5],len(badsku))
f=[];seen=set()
for r in rows:
    o=r['amazon-order-id']; s=r['sku']; k=f'{o}/{s}'
    if k in seen: continue
    seen.add(k)
    e=['amazon/order_line',k]
    f+=[{'e':e,'a':'core/part_of','v':['amazon/order_id',o]},{'e':e,'a':'line/listing','v':['amazon/seller_sku',s]}]
write(f,['amazon/all_orders.txt'],None,label='amazon order lines')
# FBA inbound
sh=lines('amazon/fba_inbound_shipments.csv')
bad=[r['Shipment ID'] for r in sh if not re.fullmatch(r'FBA[0-9A-Z]{9}',r['Shipment ID'])]; print('bad fba',bad)
write([{'e':['amazon/fba_shipment_id',r['Shipment ID']],'a':'amazon/fba_shipment_id','v':r['Shipment ID']} for r in sh],['amazon/fba_inbound_shipments.csv'],None,label='fba shipments')
# 3PL outbound
ob=lines('3pl/outbound.csv'); f=[]; seen=set()
for r in ob:
    ref=r['Order Reference']; ic=r['Item Code']; k=f'{ref}/{ic}'
    assert re.fullmatch(r'ACMH-\d{5}',ic)
    if k in seen: continue
    seen.add(k)
    whole=['amazon/fba_shipment_id',ref] if ref.startswith('FBA') else ['shopify/order_name',ref]
    e=['tpl/outbound_line',k]
    f+=[{'e':e,'a':'core/part_of','v':whole},{'e':e,'a':'line/sku','v':['tpl/item_code',ic]}]
write(f,['3pl/outbound.csv'],None,label='3pl outbound lines')
# 3PL receipts
rc=lines('3pl/receipts.csv'); f=[]; seen=set(); pos=set()
for r in rc:
    n=r['Receipt #']; assert re.fullmatch(r'GSF-RCV-\d{6}',n)
    e=['tpl/receipt_no',n]
    for p in [x.strip() for x in r['Reference'].split('/')]:
        if not p: continue
        assert re.fullmatch(r'PO-\d{4}-\d{4}',p),p
        if (n,p) not in seen: seen.add((n,p)); f.append({'e':e,'a':'receipt/po','v':['po/number',p]})
    k=f'{n}/{r["Item Code"]}'
    if k in seen: continue
    seen.add(k)
    el=['tpl/receipt_line',k]
    f+=[{'e':el,'a':'core/part_of','v':e},{'e':el,'a':'line/sku','v':['tpl/item_code',r['Item Code']]}]
write(f,['3pl/receipts.csv'],None,label='3pl receipts')
