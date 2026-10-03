from lib import *
facts=[];seen=set()
for r in csv.DictReader(open(EX+'amazon/all_orders.txt'),delimiter='\t'):
    o=["amazon/order_id",r['amazon-order-id']]
    if r['amazon-order-id'] not in seen:
        seen.add(r['amazon-order-id']);facts.append(f(o,"amazon/order_id",r['amazon-order-id']))
    l=["amazon/order_line",r['amazon-order-id']+'/'+r['sku']]
    facts+=[f(l,"core/part_of",o),f(l,"line/listing",["amazon/seller_sku",r['sku']])]
write(facts,'amazon/all_orders.txt',label='amazon orders+lines')
fb=[f(["amazon/fba_shipment_id",r['Shipment ID']],"amazon/fba_shipment_id",r['Shipment ID']) for r in csv.DictReader(open(EX+'amazon/fba_inbound_shipments.csv'))]
write(fb,'amazon/fba_inbound_shipments.csv',label='fba shipments')
