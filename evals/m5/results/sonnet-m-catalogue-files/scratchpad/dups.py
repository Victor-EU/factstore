import json,re,sys,collections as C
sys.argv+=[]
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-m-l3ll44x6/catalogue/work/exports'
cust=C.defaultdict(lambda:{'emails':set(),'na':set(),'first':'9'})
nm=lambda x:re.sub(r'\s+',' ',x.strip().lower())
for l in open(EX+'/shopify/orders.jsonl'):
    d=json.loads(l)
    if 'LineItem' in d['id']: continue
    c=d['customer']; r=cust[c['id'].rsplit('/',1)[1]]
    r['emails'].update({c['email'].lower(),d['email'].lower()})
    sa=d['shippingAddress']
    if sa: r['na'].add((nm(sa['name']),nm(sa['address1']),sa['zip'][:5]))
    r['first']=min(r['first'],d['createdAt'])
def norm(e):
    l,dm=e.split('@'); l=l.split('+')[0]
    if dm in('gmail.com','googlemail.com'): l=l.replace('.','')
    return l+'@'+dm
key=C.defaultdict(lambda:C.defaultdict(set))
for cid,r in cust.items():
    for e in r['emails']: key['m'][norm(e)].add(cid)
    for n in r['na']: key['na'][n].add(cid)
pairs={}  # newer -> (older, rule)
edges=C.defaultdict(dict)
for rule in('m','na'):
    for k,v in key[rule].items():
        if len(v)<2: continue
        v=sorted(v,key=lambda c:(cust[c]['first'],c)); old=v[0]
        for n in v[1:]: edges[n].setdefault(old,set()).add(rule)
# resolve: each newer account -> oldest root
def root(c,seen=()):
    if c in edges and c not in seen:
        o=min(edges[c],key=lambda x:(cust[x]['first'],x)); return root(o,seen+(c,))
    return c
out=[]
for n,olds in edges.items():
    o=min(olds,key=lambda x:(cust[x]['first'],x)); rules=olds[o]
    out.append((n,o,sorted(rules)))
# multi-hop heads
final={n:root(n) for n in edges}
indeg=C.Counter(final.values()); print('pairs',len(out),'rules',C.Counter(tuple(r) for _,_,r in out),'max pointing at one',indeg.most_common(3))
print('same_as chain anomalies',sum(1 for n,o,r in out if o in edges))
json.dump(out,open(sys.path[0]+'/dups.json','w'))
import random; random.seed(1)
for rule in ('m','na'):
    sel=[x for x in out if rule in x[2]]
    print('RULE',rule,len(sel))
    for n,o,r in random.sample(sel,10):
        print(' ',sorted(cust[o]['emails']),sorted(cust[o]['na']),'<-',sorted(cust[n]['emails']),sorted(cust[n]['na']))
print('--- m only')
for n,o,r in out:
    if r==['m']: print(' ',sorted(cust[o]['emails']),sorted(cust[o]['na']),cust[o]['first'][:10],'<-',sorted(cust[n]['emails']),sorted(cust[n]['na']),cust[n]['first'][:10])
