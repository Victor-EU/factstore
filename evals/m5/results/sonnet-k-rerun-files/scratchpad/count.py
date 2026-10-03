import json,csv,factstore
o=set();l=set();c=set()
for ln in open('shopify/orders.jsonl'):
    d=json.loads(ln); i=d['id']
    if 'Order/' in i:
        o.add(i.split('/')[-1])
        if d.get('customer'): c.add(d['customer']['id'].split('/')[-1])
    elif 'LineItem' in i: l.add(i.split('/')[-1])
print('shop orders',len(o),'lines',len(l),'cust',len(c))
am=list(csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'))
print('amz orders',len({r['amazon-order-id'] for r in am}),'rows',len(am))
ob=list(csv.DictReader(open('3pl/outbound.csv')))
print('3pl out rows',len(ob),'receipts',len({r['Receipt #'] for r in csv.DictReader(open('3pl/receipts.csv'))}))
def q(a):
    out=set();off=0
    while True:
        rs=factstore.query(f'select v from "{a}" order by e limit 1000 offset {off}').rows
        out|={r[0] for r in rs}
        if len(rs)<1000: return out
        off+=1000
for a,s in [('shopify/order_id',o),('shopify/line_item_id',l),('shopify/customer_id',c)]:
    st=q(a);print(a,len(st),'new',len(s-st),'gone',len(st-s))
st=q('amazon/order_id');print('amz order new',len({r['amazon-order-id'] for r in am}-st))
