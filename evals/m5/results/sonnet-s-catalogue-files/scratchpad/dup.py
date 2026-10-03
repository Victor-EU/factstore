import json,collections,re
C=json.load(open('cust.json'))
def norm(e):
    u,d=e.split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.',''); d='gmail.com'
    return u+'@'+d
G=collections.defaultdict(list)
for k,v in C.items(): G[norm(v['em'][0])].append(k)
exact=collections.defaultdict(list)
for k,v in C.items(): exact[v['em'][0]].append(k)
print('exact-email groups',sum(1 for g in exact.values() if len(g)>1))
multi={e:g for e,g in G.items() if len(g)>1}
print('norm groups',len(multi),collections.Counter(len(g) for g in multi.values()))
import itertools
for e,g in list(multi.items())[:12]:
    print(e,[(k,C[k]['em'],C[k]['nm'],C[k]['ad'][:1],C[k]['first'][:10],C[k]['n']) for k in g])
# name+address
NA=collections.defaultdict(set)
for k,v in C.items():
    for n in v['nm']:
        for a in v['ad']: NA[(n,a)].add(k)
na={x:g for x,g in NA.items() if len(g)>1}
print('name+addr groups',len(na))
inemail=sum(1 for x,g in na.items() if len({norm(C[k]['em'][0]) for k in g})==1)
print('of which same normalized email',inemail)
for x,g in list(na.items())[:8]: print(x,[(k,C[k]['em']) for k in g])
