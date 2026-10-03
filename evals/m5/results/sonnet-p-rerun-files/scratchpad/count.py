import json,csv
orders=set();lines=set();cust=set();ocust=0
for l in open('shopify/orders.jsonl'):
    r=json.loads(l)
    if r['id'].startswith('gid://shopify/Order/'):
        orders.add(r['id'].split('/')[-1]); 
        if r.get('customer'): cust.add(r['customer']['id'].split('/')[-1])
    elif 'LineItem' in r['id']: lines.add(r['id'].split('/')[-1])
print('shopify orders',len(orders),'lines',len(lines),'customers',len(cust))
ao=set();al=set();n=0
for r in csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'):
    ao.add(r['amazon-order-id']);n+=1
print('amazon orders',len(ao),'rows',n)
rows=list(csv.DictReader(open('3pl/outbound.csv')))
print('outbound rows',len(rows),'keys',len({(r['Order Reference'],r['Item Code']) for r in rows}))
rc=list(csv.DictReader(open('3pl/receipts.csv')))
print('receipt rows',len(rc),'receipts',len({r['Receipt #'] for r in rc}))
print('fba',len(list(csv.DictReader(open('amazon/fba_inbound_shipments.csv')))),'inv',len(open('amazon/fba_inventory.txt').read().splitlines())-1)
