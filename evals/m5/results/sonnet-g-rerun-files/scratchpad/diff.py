import json,csv,factstore
def st(a):
    out=set();o=0
    while True:
        r=factstore.query(f'select v from "{a}" order by e limit 1000 offset {o}').rows
        out|={x[0] for x in r}; o+=1000
        if len(r)<1000: return out
orders=set();cust=set();lines=set()
for l in open('shopify/orders.jsonl'):
    o=json.loads(l)
    if o['id'].startswith('gid://shopify/Order/'):
        orders.add(o['id'].rsplit('/',1)[1])
        c=o.get('customer')
        if c: cust.add(c['id'].rsplit('/',1)[1])
    elif 'LineItem' in o['id']: lines.add(o['id'].rsplit('/',1)[1])
print('orders',len(orders),len(orders-st('shopify/order_id')))
print('cust',len(cust),len(cust-st('shopify/customer_id')))
print('lines',len(lines),len(lines-st('shopify/line_item_id')))
ao=set();al=set()
for r in csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'):
    ao.add(r['amazon-order-id']);al.add(r['amazon-order-id']+'/'+r['sku'])
print('amz orders',len(ao),len(ao-st('amazon/order_id')),'lines',len(al),len(al-st('amazon/order_line')))
ob={r['Order Reference']+'/'+r['Item Code'] for r in csv.DictReader(open('3pl/outbound.csv'))}
print('outbound',len(ob),len(ob-st('tpl/outbound_line')))
rl={r['Receipt #']+'/'+r['Item Code'] for r in csv.DictReader(open('3pl/receipts.csv'))}
print('rcpt',len(rl),len(rl-st('tpl/receipt_line')))
