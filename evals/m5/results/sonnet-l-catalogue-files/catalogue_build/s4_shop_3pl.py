from common import *
num=lambda g:g.rsplit('/',1)[1]
f=[];seen=set()
for l in open(EX+'/shopify/orders.jsonl'):
    o=json.loads(l)
    if '/Order/' in o['id']:
        oid=num(o['id']); c=num(o['customer']['id']); e=["shopify/order_id",oid]
        assert re.fullmatch(r'\d+',oid) and re.fullmatch(r'\d+',c) and re.fullmatch(r'#\d+',o['name'])
        if c not in seen: seen.add(c); f.append({"e":["shopify/customer_id",c],"a":"shopify/customer_id","v":c})
        f+=[{"e":e,"a":"shopify/order_id","v":oid},{"e":e,"a":"shopify/order_name","v":o['name']},{"e":e,"a":"order/customer","v":["shopify/customer_id",c]}]
    else:
        i=num(o['id']); e=["shopify/line_item_id",i]
        f+=[{"e":e,"a":"shopify/line_item_id","v":i},{"e":e,"a":"core/part_of","v":["shopify/order_id",num(o['__parentId'])]},
            {"e":e,"a":"line/sku","v":["shopify/variant_id",num(o['variant']['id'])]}]
write(f,'shopify/orders.jsonl',None,label='shopify customers/orders/lines')
# 3PL
rc=list(csv.DictReader(open(EX+'/3pl/receipts.csv')));f=[];seen=set()
for r in rc:
    n=r['Receipt #']; e=["tpl/receipt_no",n]
    if n not in seen:
        seen.add(n); f.append({"e":e,"a":"tpl/receipt_no","v":n})
        for p in [x for x in re.split(r'\s*/\s*',r['Reference']) if x]:
            assert re.fullmatch(r'PO-\d{4}-\d{4}',p); f.append({"e":e,"a":"receipt/po","v":["po/number",p]})
    k=f"{n}/{r['Item Code']}"; l=["tpl/receipt_line",k]
    f+=[{"e":l,"a":"tpl/receipt_line","v":k},{"e":l,"a":"core/part_of","v":e},{"e":l,"a":"line/sku","v":["tpl/item_code",r['Item Code']]}]
write(f,'3pl/receipts.csv',None,label='receipts')
f=[]
for r in csv.DictReader(open(EX+'/3pl/outbound.csv')):
    ref=r['Order Reference']; k=f"{ref}/{r['Item Code']}"; l=["tpl/outbound_line",k]
    whole=["shopify/order_name",ref] if ref.startswith('#') else ["amazon/fba_shipment_id",ref]
    f+=[{"e":l,"a":"tpl/outbound_line","v":k},{"e":l,"a":"core/part_of","v":whole},{"e":l,"a":"line/sku","v":["tpl/item_code",r['Item Code']]}]
write(f,'3pl/outbound.csv',None,label='outbound')
