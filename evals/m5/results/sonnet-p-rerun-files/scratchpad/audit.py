import json,collections,re,sys
em=collections.defaultdict(set);nm=collections.defaultdict(set);ad=collections.defaultdict(set)
for l in open('shopify/orders.jsonl'):
    r=json.loads(l)
    if not r['id'].startswith('gid://shopify/Order/') or not r.get('customer'): continue
    c=r['customer']['id'].split('/')[-1]
    for e in (r['customer'].get('email'),r.get('email')):
        if e: em[c].add(e.lower())
    cu=r['customer']; nm[c].add(((cu.get('firstName') or '')+' '+(cu.get('lastName') or '')).lower().strip())
    s=r.get('shippingAddress')
    if s:
        nm[c].add((s.get('name') or '').lower()); ad[c].add((s.get('address1','').lower(),s.get('zip','')))
def norm(e,gm=False):
    u,d=e.split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
pairs=[l for l in json.load(sys.stdin)]
cnt=collections.Counter(); bad=[]
for n,o,conf in pairs:
    exact=em[n]&em[o]; normd={norm(x) for x in em[n]}&{norm(x) for x in em[o]}
    nameaddr=(nm[n]&nm[o]-{''}) and (ad[n]&ad[o])
    rule='exact_mailbox' if exact else 'normalized_mailbox' if normd else 'name+addr' if nameaddr else 'NONE'
    cnt[(conf,rule)]+=1
    if rule=='NONE' or conf=='0.7': bad.append((n,o,conf,rule,sorted(em[n]),sorted(em[o]),sorted(nm[n]),sorted(nm[o]),sorted(ad[n]),sorted(ad[o])))
print(cnt)
for b in bad[:12]: print(b)
