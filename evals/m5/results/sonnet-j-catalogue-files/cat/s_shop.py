from lib import *
facts=[];cust={}
for l in open(EX+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d:
        facts+=[f(["shopify/line_item_id",gid(d['id'])],"core/part_of",["shopify/order_id",gid(d['__parentId'])]),
                f(["shopify/line_item_id",gid(d['id'])],"line/sku",["shopify/variant_id",gid(d['variant']['id'])])]
    else:
        o=["shopify/order_id",gid(d['id'])]
        c=d['customer'];assert c and c['id']
        facts+=[f(o,"shopify/order_name",d['name']),f(o,"order/customer",["shopify/customer_id",gid(c['id'])])]
        a=d['shippingAddress'] or {}
        r=cust.setdefault(gid(c['id']),{'email':(c['email'] or '').lower(),'name':(c['firstName'],c['lastName']),'addr':set(),'first':d['createdAt']})
        r['addr'].add((a.get('address1'),a.get('zip')));r['first']=min(r['first'],d['createdAt'])
write(facts,'shopify/orders.jsonl',label='shopify orders+lines')
# duplicates
def norm(e):
    u,dm=e.split('@');return u.split('+')[0]+'@'+dm
par={k:k for k in cust}
def find(x):
    while par[x]!=x: x=par[x]
    return x
edges=[]
g=collections.defaultdict(list)
for k,v in cust.items():
    if v['email']: g[norm(v['email'])].append(k)
for s in g.values():
    for x in s[1:]: edges.append((s[0],x,'mbx'))
g=collections.defaultdict(list)
for k,v in cust.items():
    if v['name'][0] and v['name'][1]:
        for a in v['addr']:
            if a[0] and a[1]: g[(v['name'],a)].append(k)
for s in g.values():
    for x in s[1:]: edges.append((s[0],x,'nameaddr'))
for a,b,_ in edges: par[find(a)]=find(b)
comp=collections.defaultdict(list)
for k in cust: comp[find(k)].append(k)
same=[];stats=collections.Counter();pairs=collections.defaultdict(list)
for m in comp.values():
    if len(m)<2: continue
    m.sort(key=lambda k:(cust[k]['first'],k));root=m[0]
    for x in m[1:]:
        rule='mbx' if norm(cust[x]['email'])==norm(cust[root]['email']) else 'nameaddr'
        # require direct evidence against root
        if rule=='nameaddr' and not (cust[x]['name']==cust[root]['name'] and cust[x]['addr']&cust[root]['addr']): rule='chain'
        pairs[rule].append((root,x));stats[rule]+=1
print(stats,len(comp))
fan=collections.Counter(r for p in pairs.values() for r,_ in p);print(fan.most_common(3))
json.dump({k:[(a,b,cust[a]['name'],cust[b]['name'],cust[a]['email'],cust[b]['email']) for a,b in v] for k,v in pairs.items()},open(SCR+'/dups.json','w'))
if os.environ.get('DUPS'):
    for rule,conf in(('mbx',0.9),('nameaddr',0.7)):
        write([f(["shopify/customer_id",x],"core/same_as",["shopify/customer_id",r]) for r,x in pairs[rule]],'shopify/orders.jsonl',conf,label='same_as '+rule)
