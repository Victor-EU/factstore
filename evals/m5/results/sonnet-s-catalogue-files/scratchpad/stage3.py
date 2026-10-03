from common import *
import collections
P=json.load(open('pairs.json'))
first={}
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: continue
    k=d['customer']['id'].split('/')[-1]; first[k]=min(first.get(k,'z'),d['createdAt'])
adj=collections.defaultdict(set); typ={}
for t in 'AB':
    for a,b in P[t]:
        adj[a].add(b); adj[b].add(a); typ[frozenset((a,b))]=typ.get(frozenset((a,b)),'')+t
seen=set(); comps=[]
for k in adj:
    if k in seen: continue
    st=[k]; c=set()
    while st:
        x=st.pop()
        if x in c: continue
        c.add(x); st+=adj[x]
    seen|=c; comps.append(c)
print('components',len(comps),collections.Counter(len(c) for c in comps))
out={0.9:[],0.7:[]}; rule={}
for c in comps:
    s=min(c,key=lambda k:(first[k],k))
    # reach via A edges
    reach={s};st=[s]
    while st:
        x=st.pop()
        for y in adj[x]:
            if y not in reach and 'A' in typ[frozenset((x,y))]: reach.add(y);st.append(y)
    for k in c-{s}:
        conf=0.9 if k in reach else 0.7
        out[conf].append({'e':['shopify/customer_id',k],'a':'core/same_as','v':['shopify/customer_id',s]})
        rule[k]=conf
print({k:len(v) for k,v in out.items()})
json.dump(rule,open('rule.json','w'))
for conf,f in out.items(): write(f,['shopify/orders.jsonl'],conf,label=f'same_as {conf}')
