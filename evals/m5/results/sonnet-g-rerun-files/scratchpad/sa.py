import json,factstore,re,collections
pairs=[];o=0
while True:
    r=factstore.query(f'select a.v,b.v,c.v from "core/same_as" s join "shopify/customer_id" a on a.e=s.e join "shopify/customer_id" b on b.e=s.v left join "core/confidence" c on c.e=0 order by a.v limit 1000 offset {o}').rows
    pairs+=r;o+=1000
    if len(r)<1000:break
print(len(pairs))
info={}
for l in open('shopify/orders.jsonl'):
    o=json.loads(l)
    c=o.get('customer')
    if c and o['id'].startswith('gid://shopify/Order/'):
        cid=c['id'].rsplit('/',1)[1]
        sa=o.get('shippingAddress') or {}
        info.setdefault(cid,(c.get('email'),(c.get('firstName') or '')+' '+(c.get('lastName') or ''),sa.get('address1'),sa.get('zip')))
def norm(e,gm=True):
    l,d=e.lower().split('@');l=l.split('+')[0]
    if d in('gmail.com','googlemail.com'):l=l.replace('.','')
    return l+'@'+d
cnt=collections.Counter();tgt=collections.Counter();bad=[]
for a,b,_ in pairs:
    x,y=info[a],info[b];tgt[b]+=1
    if x[0]==y[0]:r='same'
    elif norm(x[0])==norm(y[0]):r='norm'
    elif x[1].lower()==y[1].lower() and x[2]==y[2]:r='name+addr'
    else:r='NONE';bad.append((x,y))
    cnt[r]+=1
    if r!='same' and cnt[r]<=10:print(r,x,y)
print(cnt,tgt.most_common(3));print(bad[:10])
