import sys;sys.path.insert(0,'scripts')
from common import *
cust={}
for l in open(EX+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d or not d['customer']: continue
    c=d['customer']; a=d['shippingAddress'] or {}
    x=cust.setdefault(gid(c['id']),dict(email=c['email'],fn=c['firstName'],ln=c['lastName'],addr=(a.get('address1') or '').lower().strip(),zip=a.get('zip'),first=d['createdAt'],name=a.get('name')))
    x['first']=min(x['first'],d['createdAt'])
def nm(e):
    u,d=e.lower().strip().rsplit('@',1); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
par={i:i for i in cust}
def find(i):
    while par[i]!=i: par[i]=par[par[i]]; i=par[i]
    return i
for keyf in (lambda v:nm(v['email']), lambda v:(v['fn'].lower(),v['ln'].lower(),v['addr'],v['zip']) if v['addr'] and v['zip'] else None):
    g=collections.defaultdict(list)
    for i,v in cust.items():
        k=keyf(v)
        if k: g[k].append(i)
    for x in g.values():
        for j in x[1:]: par[find(j)]=find(x[0])
groups=collections.defaultdict(list)
for i in cust: groups[find(i)].append(i)
edges=[]  # (dup, survivor, rule)
for x in groups.values():
    if len(x)<2: continue
    x.sort(key=lambda i:(cust[i]['first'],int(i))); s=x[0]
    for j in x[1:]:
        rule='mailbox' if nm(cust[j]['email'])==nm(cust[s]['email']) else 'name+address'
        edges.append((j,s,rule))
if __name__=='__main__':
    print(collections.Counter(r for _,_,r in edges), 'max group',max(len(x) for x in groups.values()))
    import random; random.seed(1)
    for rule in ('mailbox','name+address'):
        print('---',rule)
        for j,s,r in random.sample([e for e in edges if e[2]==rule],10):
            print([ (cust[i]['email'],cust[i]['name'],cust[i]['addr'],cust[i]['zip']) for i in (s,j)])
    if '--write' in sys.argv:
        for rule,conf in (('mailbox',0.9),('name+address',0.7)):
            f=[{'e':['shopify/customer_id',j],'a':'core/same_as','v':['shopify/customer_id',s]} for j,s,r in edges if r==rule]
            write(f,['shopify/orders.jsonl'],conf); print('wrote',rule,len(f))
