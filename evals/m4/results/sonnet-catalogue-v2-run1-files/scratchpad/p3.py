from load import *
LIM=int(os.environ.get('LIM','0'))
orders=[];lines=[];cust={};first={};addr=collections.defaultdict(set)
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l); k=d['id'].split('/')[3]
    if k=='Order':
        o=["shopify/order_id",gid(d['id'])]; c=d['customer']; cid=gid(c['id'])
        orders+=[{"e":o,"a":"shopify/order_name","v":d['name']},{"e":o,"a":"order/customer","v":["shopify/customer_id",cid]}]
    else:
        lines+=[{"e":["shopify/line_item_id",gid(d['id'])],"a":"core/part_of","v":["shopify/order_id",gid(d['__parentId'])]},
                {"e":["shopify/line_item_id",gid(d['id'])],"a":"line/sku","v":["shopify/variant_id",gid(d['variant']['id'])]}]
print(len(orders)//2,len(lines)//2)
# orders (with customers) first, then lines
print(tx(orders,'shopify/orders.jsonl'))
print(tx(lines,'shopify/orders.jsonl'))
