import json,csv,re,collections as C
orders=[]
for l in open('shopify/orders.jsonl'):
    d=json.loads(l)
    if 'LineItem' not in d['id']: orders.append(d)
names={o['name'] for o in orders}
ob=list(csv.DictReader(open('3pl/outbound.csv')))
fb={r['Shipment ID'] for r in csv.DictReader(open('amazon/fba_inbound_shipments.csv'))}
print('ob # not in shopify',len({r['Order Reference'] for r in ob if r['Order Reference'].startswith('#')}-names), 'fba not in',{r['Order Reference'] for r in ob if r['Order Reference'].startswith('FBA')}-fb)
print('order name pattern',C.Counter(re.sub(r'\d','9',o['name']) for o in orders))
# customers
em_diff=sum(1 for o in orders if o['email'] and o['customer']['email'].lower()!=o['email'].lower()); print('order email != cust email',em_diff, 'blank order email',sum(1 for o in orders if not o['email']))
cust=C.defaultdict(lambda:{'emails':set(),'nameaddr':set(),'first':'9'})
def nm(x): return re.sub(r'\s+',' ',x.strip().lower())
for o in orders:
    c=o['customer']; r=cust[c['id']]
    r['emails'].add(c['email'].lower())
    if o['email']: r['emails'].add(o['email'].lower())
    sa=o['shippingAddress']
    if sa: r['nameaddr'].add((nm(sa['name']),nm(sa['address1']),sa['zip'][:5]))
    r['nameaddr'].add((nm(c['firstName']+' '+c['lastName']),) ) if False else None
    r['first']=min(r['first'],o['createdAt'])
print(len(cust))
def norm(e):
    l,d=e.split('@'); l=l.split('+')[0]
    if d in('gmail.com','googlemail.com'): l=l.replace('.','')
    return l+'@'+d
byk=C.defaultdict(set)
for cid,r in cust.items():
    for e in r['emails']: byk[('m',norm(e))].add(cid)
    for na in r['nameaddr']: byk[('na',na)].add(cid)
pairs=C.Counter()
for k,v in byk.items():
    if len(v)>1: pairs[(k[0],len(v))]+=1
print(pairs)
raw=C.defaultdict(set)
for cid,r in cust.items():
    for e in r['emails']: raw[e].add(cid)
print('exact-mailbox groups',sum(1 for v in raw.values() if len(v)>1))
print('customer ids pattern',C.Counter(re.sub(r'\d','9',c) for c in cust).most_common(3))
ex=[(k,v) for k,v in byk.items() if len(v)>1][:8]
for k,v in ex: print(k,[(c,sorted(cust[c]['emails']),sorted(cust[c]['nameaddr']),cust[c]['first']) for c in v])
