from lib import *
H=json.load(open('w/hubs.json'))
# --- shopify
o=[json.loads(l) for l in open(X+'shopify/orders.jsonl')]
hs,hsf=doc_facts('shopify/orders.jsonl'); write(hsf,[])
f=[]; seen=set()
for x in o:
    if '__parentId' in x:
        le=["shopify/line_item_id",gid(x['id'])]
        f+=[{"e":le,"a":"core/part_of","v":["shopify/order_id",gid(x['__parentId'])]},
            {"e":le,"a":"line/sku","v":["shopify/variant_id",gid(x['variant']['id'])]}]
    else:
        oe=["shopify/order_id",gid(x['id'])]; ce=["shopify/customer_id",gid(x['customer']['id'])]
        f+=[{"e":oe,"a":"shopify/order_name","v":x['name']},{"e":oe,"a":"order/customer","v":ce}]
        if ce[1] not in seen: seen.add(ce[1]); f.append({"e":ce,"a":"shopify/customer_id","v":ce[1]})
print('shopify',len(f),write(f,[hs],1))
# --- amazon
ao=list(csv.DictReader(open(X+'amazon/all_orders.txt'),delimiter='\t'))
ha,haf=doc_facts('amazon/all_orders.txt')
f=[];so=set()
for r in ao:
    oid=r['amazon-order-id']; assert re.match(r'^\d{3}-\d{7}-\d{7}$',oid)
    oe=["amazon/order_id",oid]
    if oid not in so: so.add(oid); f.append({"e":oe,"a":"amazon/order_id","v":oid})
    le=["amazon/order_line",f"{oid}/{r['sku']}"]
    f+=[{"e":le,"a":"core/part_of","v":oe},{"e":le,"a":"line/sku","v":["amazon/seller_sku",r['sku']]}]
print('amazon orders',len(so),len(f),write(f,[ha],1))
hf_,hff=doc_facts('amazon/fba_inbound_shipments.csv'); write(hff,[])
fi=list(csv.DictReader(open(X+'amazon/fba_inbound_shipments.csv')))
print('fba',write([{"e":["amazon/fba_shipment_id",r['Shipment ID']],"a":"amazon/fba_shipment_id","v":r['Shipment ID']} for r in fi],[hf_],1))
