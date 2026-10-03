import json,collections
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-s-kfe1uo8m/catalogue/work/exports/'
A=collections.defaultdict(lambda:{'em':None,'nm':None,'ad':set(),'first':None,'ords':[]})
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: continue
    c=d['customer']; k=c['id'].split('/')[-1]; r=A[k]
    r['em']=c['email'].lower(); r['nm']=(c['firstName'] or '').lower()+' '+(c['lastName'] or '').lower()
    sa=d['shippingAddress']
    if sa and sa['name'].lower().strip()==r['nm'].strip(): r['ad'].add(sa['address1'].lower().strip()+'|'+sa['zip'])
    r['first']=min(r['first'] or d['createdAt'],d['createdAt'])
def norm(e):
    u,d=e.split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.',''); d='gmail.com'
    return u+'@'+d
G=collections.defaultdict(list)
for k,v in A.items(): G[norm(v['em'])].append(k)
pairsA=set()
for g in G.values():
    if len(g)>1:
        g=sorted(g,key=lambda k:(A[k]['first'],k))
        for k in g[1:]: pairsA.add((k,g[0]))
print('A pairs',len(pairsA))
same=sum(1 for a,b in pairsA if A[a]['nm']==A[b]['nm']); print('A same cust name',same)
for a,b in pairsA:
    if A[a]['nm']!=A[b]['nm']: print('DIFF',A[a]['em'],A[a]['nm'],'|',A[b]['em'],A[b]['nm'])
NA=collections.defaultdict(set)
for k,v in A.items():
    for a in v['ad']: NA[(v['nm'],a)].add(k)
B=[sorted(g,key=lambda k:(A[k]['first'],k)) for g in NA.values() if len(g)>1]
Bp=set()
for g in B:
    for k in g[1:]: Bp.add((k,g[0]))
Bp-=pairsA
print('B pairs not in A',len(Bp))
# which are not same-norm-email groups
for a,b in list(Bp)[:25]: print(A[a]['em'],A[b]['em'],A[a]['nm'])
json.dump({'A':sorted(pairsA),'B':sorted(Bp)},open('pairs.json','w'))
