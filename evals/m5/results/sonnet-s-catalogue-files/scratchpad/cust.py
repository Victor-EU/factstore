import json,collections,re
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-s-kfe1uo8m/catalogue/work/exports/'
C=collections.defaultdict(lambda:{'em':set(),'nm':set(),'ad':set(),'n':0,'first':None})
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: continue
    c=d['customer']; r=C[c['id'].split('/')[-1]]; r['n']+=1
    r['first']=r['first'] or d['createdAt']
    for e in (c.get('email'),d.get('email')):
        if e: r['em'].add(e.lower().strip())
    nm=' '.join(filter(None,[c.get('firstName'),c.get('lastName')])).lower()
    if nm: r['nm'].add(nm)
    sa=d.get('shippingAddress')
    if sa:
        if sa.get('name'): r['nm'].add(sa['name'].lower().strip())
        r['ad'].add((sa.get('address1','') or '').lower().strip()+'|'+(sa.get('zip') or ''))
json.dump({k:{a:(sorted(b) if isinstance(b,set) else b) for a,b in v.items()} for k,v in C.items()},open('cust.json','w'))
print(len(C), collections.Counter(len(v['em']) for v in C.values()), collections.Counter(len(v['nm']) for v in C.values()))
