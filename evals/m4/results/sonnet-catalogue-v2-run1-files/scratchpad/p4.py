from load import *
# customer duplicates; personal data used here only to compare, never written
cust={};first={};addr=collections.defaultdict(set)
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l)
    if d['id'].split('/')[3]!='Order': continue
    c=d['customer']; i=gid(c['id']); cust.setdefault(i,c); first[i]=min(first.get(i,'z'),d['createdAt'])
    a=d.get('shippingAddress') or {}
    if a.get('name','').lower()==(c['firstName']+' '+c['lastName']).lower():
        addr[i].add((a['name'].lower(),a['address1'].lower(),a['zip']))
def norm(e):
    loc,dom=e.lower().split('@'); loc=loc.split('+')[0]
    if dom in('gmail.com','googlemail.com'): loc=loc.replace('.','')
    return loc+'@'+dom
g1=collections.defaultdict(set)
for i,c in cust.items(): g1[norm(c['email'])].add(i)
g2=collections.defaultdict(set)
for i,s in addr.items():
    for a in s: g2[a].add(i)
mark={}  # dup -> (survivor,tier)
def root(i):
    while i in mark: i=mark[i][0]
    return i
for tier,groups in ((0.9,g1),(0.7,g2)):
    for k,v in groups.items():
        if len(v)<2: continue
        s=min((root(i) for i in v),key=lambda i:(first[i],i))
        for i in sorted(v):
            if root(i)!=s and i not in mark:
                assert i!=s; mark[i]=(s,tier)
# no cycles/chains
for t in (0.9,0.7):
    f=[{"e":["shopify/customer_id",d],"a":"core/same_as","v":["shopify/customer_id",root(d)]} for d,(s,tt) in sorted(mark.items()) if tt==t]
    print(t,len(f),tx(f,'shopify/orders.jsonl',t))

print('dups',len(mark),'survivors',len({root(d) for d in mark}))
assert all(root(d)!=d for d in mark)
