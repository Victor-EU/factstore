from common import *
import sys
pr=products(); hub_by_vid={p['vid']:p['hub'] for p in pr}; hub_by_upc={p['upc']:p['hub'] for p in pr}
B=[]  # (docpath, conf, facts)
def add(doc,conf,facts):
    if facts: B.append((doc,conf,facts))
def rd(f,d=','): return list(csv.DictReader(open(X+f,encoding='utf-8-sig'),delimiter=d))
def S(a,e,v): return {'e':e,'a':a,'v':v}
H=lambda h:['sku/code',h]
# 1 products
add('shopify/products.jsonl',1,[f for p in pr if p['hub']==p['sku'] for f in (S('shopify/variant_id',H(p['hub']),p['vid']),S('sku/upc',H(p['hub']),p['upc']))])
add('shopify/products.jsonl',0.9,[f for p in pr if p['hub']!=p['sku'] for f in (S('shopify/variant_id',H(p['hub']),p['vid']),S('sku/upc',H(p['hub']),p['upc']))])
# 3pl item codes by UPC
inv=rd('3pl/inventory_snapshot.csv'); item_hub={}
f=[]
for r in inv:
    h=hub_by_upc[r['UPC']]; item_hub[r['Item Code']]=h; f.append(S('tpl/item_code',H(h),r['Item Code']))
assert len(set(item_hub.values()))==len(inv)==49
add('3pl/inventory_snapshot.csv',1,f)
# amazon listings
inv=rd('amazon/fba_inventory.txt','\t'); lst={}
ex=[];nm=[]
for r in inv:
    s=r['sku']; h=s if s in hub_by_upc.values() else (re.sub(r'-FBA$','',s) if re.sub(r'-FBA$','',s) in hub_by_upc.values() else None)
    assert h,s
    fs=[S('listing/sku',['amazon/seller_sku',s],H(h)),S('listing/asin',['amazon/seller_sku',s],['amazon/asin',r['asin']]),S('amazon/fnsku',['amazon/seller_sku',s],r['fnsku'])]
    (ex if h==s else nm).extend(fs); lst[s]=h
add('amazon/fba_inventory.txt',1,ex); add('amazon/fba_inventory.txt',0.9,nm)
# shopify orders
cust={};orders=[];lines=[]
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '/Order/' in d['id']: orders.append(d)
    else: lines.append(d)
f=[]
for d in orders:
    oid=d['id'].split('/')[-1]; cid=d['customer']['id'].split('/')[-1]
    f+= [S('shopify/order_name',['shopify/order_id',oid],d['name']),S('order/customer',['shopify/order_id',oid],['shopify/customer_id',cid])]
add('shopify/orders.jsonl',1,f)
f=[]
for d in lines:
    li=d['id'].split('/')[-1]; oid=d['__parentId'].split('/')[-1]; vid=d['variant']['id'].split('/')[-1]
    f+=[S('core/part_of',['shopify/line_item_id',li],['shopify/order_id',oid]),S('line/sku',['shopify/line_item_id',li],H(hub_by_vid[vid]))]
add('shopify/orders.jsonl',1,f)
# amazon orders
ao=rd('amazon/all_orders.txt','\t'); f=[]
for r in ao:
    o=r['amazon-order-id']; k=o+'/'+r['sku']
    assert re.fullmatch(r'\d{3}-\d{7}-\d{7}',o) and r['sku'] in lst
    f+=[S('core/part_of',['amazon/order_line',k],['amazon/order_id',o]),S('line/listing',['amazon/order_line',k],['amazon/seller_sku',r['sku']])]
add('amazon/all_orders.txt',1,f)
# fba shipments
add('amazon/fba_inbound_shipments.csv',1,[S('amazon/fba_shipment_id',['amazon/fba_shipment_id',r['Shipment ID']],r['Shipment ID']) for r in rd('amazon/fba_inbound_shipments.csv')])
# receipts
f=[];bad=set()
for r in rd('3pl/receipts.csv'):
    rn=r['Receipt #']; k=rn+'/'+r['Item Code']; assert r['Item Code'] in item_hub
    f+=[S('core/part_of',['tpl/receipt_line',k],['tpl/receipt_no',rn]),S('line/sku',['tpl/receipt_line',k],H(item_hub[r['Item Code']]))]
    for po in [x.strip() for x in r['Reference'].split('/')] if r['Reference'].strip() else []:
        if re.fullmatch(r'PO-20\d\d-\d{4}',po): f.append(S('receipt/po',['tpl/receipt_no',rn],['po/number',po]))
        else: bad.add(po)
print('bad po refs',bad)
add('3pl/receipts.csv',1,f)
# outbound
f=[]
for r in rd('3pl/outbound.csv'):
    o=r['Order Reference']; k=o+'/'+r['Item Code']
    whole=['amazon/fba_shipment_id',o] if o.startswith('FBA') else ['shopify/order_name',o]
    f+=[S('core/part_of',['tpl/outbound_line',k],whole),S('line/sku',['tpl/outbound_line',k],H(item_hub[r['Item Code']]))]
add('3pl/outbound.csv',1,f)
# vendors
vend=rd('quickbooks/vendors.csv'); f=[]
for r in vend:
    m=re.search(r'@(\w+)\.example',r['Email']); 
    code=m[1].upper() if m and r['Email'] and r['Currency'] and not r['Vendor'].startswith(('Pacific','Harbor','Garden')) else None
    e=['supplier/code',code] if code else ['quickbooks/vendor',r['Vendor']]
    f.append(S('quickbooks/vendor',e,r['Vendor']))
    if code: f.append(S('supplier/code',e,code))
    print(r['Vendor'],code)
add('quickbooks/vendors.csv',1,f)
# factory crosswalk
it=pdf_items(); seen=set()
for doc,sup,code,desc,hs in it:
    cand=[p for p in pr if norm(p['name'])==norm(desc)]; h=cand[0]['hub']
    k=(sup,code)
    f=[S('factory/item_code',H(h),f'{sup}:{code}'),S('sku/supplier',H(h),['supplier/code',sup]),S('sku/hs_code',H(h),hs)]
    add(doc,0.7,f)
# customers same_as
cu={};ad=C.defaultdict(set);first={}
for d in orders:
    c=d['customer'];cid=c['id'].split('/')[-1];a=d['shippingAddress']
    cu[cid]=(c['email'],c['firstName'].lower(),c['lastName'].lower()); ad[cid].add((a['address1'],a['zip']))
    first[cid]=min(first.get(cid,'9'),d['createdAt'])
f=[S('x',['shopify/customer_id',c],c) for c in cu]
f=[S('shopify/customer_id',['shopify/customer_id',c],c) for c in cu]
add('shopify/orders.jsonl',1,f)
def nmb(e): u,_,dm=e.lower().partition('@'); return u.split('+')[0]+'@'+dm
par={k:k for k in cu}
def fd(x):
    while par[x]!=x: par[x]=par[par[x]]; x=par[x]
    return x
ev=C.defaultdict(list)
g=C.defaultdict(list)
for k,v in cu.items(): g[nmb(v[0])].append(k)
for x in g.values():
    for y in x[1:]: par[fd(y)]=fd(x[0]); ev[frozenset((x[0],y))]=['mailbox']
g=C.defaultdict(set)
for k,v in cu.items():
    for a in ad[k]: g[(v[1],v[2])+a].add(k)
for x in g.values():
    x=sorted(x)
    for y in x[1:]: par[fd(y)]=fd(x[0]); ev.setdefault(frozenset((x[0],y)),['nameaddr'])
comp=C.defaultdict(list)
for k in cu: comp[fd(k)].append(k)
mb=[];na=[];pairs=[]
for m in comp.values():
    if len(m)<2: continue
    m.sort(key=lambda c:(first[c],c)); s=m[0]; done={s}
    rest=m[1:]
    while rest:
        prog=False
        for y in list(rest):
            for z in sorted(done,key=lambda c:(c!=s,first[c])):
                e=ev.get(frozenset((y,z)))
                if e:
                    (mb if e[0]=='mailbox' else na).append(S('core/same_as',['shopify/customer_id',y],['shopify/customer_id',z])); pairs.append((y,z,e[0]))
                    done.add(y);rest.remove(y);prog=True;break
        assert prog
add('shopify/orders.jsonl',0.9,mb);add('shopify/orders.jsonl',0.7,na)
json.dump(pairs,open('pairs.json','w'))
print('same_as',len(mb),len(na))
if __name__=='__main__':
    print(len(B),sum(len(b[2]) for b in B))
