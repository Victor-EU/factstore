import json,collections,re
def nm(e):
    e=(e or '').strip().lower()
    if '@' not in e: return None
    u,d=e.split('@',1); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
def load():
    acc=collections.defaultdict(lambda: {'mail':set(),'name':set(),'addr':set(),'first':None,'orders':0,'raw':set()})
    for l in open('shopify/orders.jsonl'):
        d=json.loads(l)
        if '__parentId' in d: continue
        c=d['customer']; a=acc[c['id'].split('/')[-1]]
        a['orders']+=1; a['first']=a['first'] or d['createdAt']
        if a['first']>d['createdAt']: a['first']=d['createdAt']
        for e in (c.get('email'),d.get('email')):
            if nm(e): a['mail'].add(nm(e)); a['raw'].add(e.lower())
        n=((c.get('firstName') or '')+' '+(c.get('lastName') or '')).strip().lower()
        sa=d.get('shippingAddress') or {}
        if n: a['name'].add(n)
        if sa.get('name'): a['name'].add(sa['name'].strip().lower())
        if sa.get('address1'):
            a['addr'].add((re.sub(r'\W+',' ',sa['name'].lower()).strip() if sa.get('name') else '', re.sub(r'\W+',' ',sa['address1'].lower()).strip(), (sa.get('zip') or '')[:5]))
    return acc
