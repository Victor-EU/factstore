import json,csv,collections as C,re
P='exports/'
V=[json.loads(l) for l in open(P+'shopify/products.jsonl')]
V=[v for v in V if 'ProductVariant' in v['id']]
def rd(f,**k): return list(csv.DictReader(open(P+f,encoding='utf-8-sig'),**k))
inv=rd('3pl/inventory_snapshot.csv'); rc=rd('3pl/receipts.csv'); ob=rd('3pl/outbound.csv')
upc2item={r['UPC']:r['Item Code'] for r in inv}
sp=C.defaultdict(C.Counter)
for v in V: sp[upc2item[v['barcode']]]['shop:'+v['sku']]+=1
shl=C.Counter()
for l in open(P+'shopify/orders.jsonl'):
    r=json.loads(l)
    if '/LineItem/' in r['id']: shl[r['sku']]+=1
sku2item={v['sku']:upc2item[v['barcode']] for v in V}
for s,n in shl.items(): sp[sku2item[s]]['shoplines:'+s]+=n
for r in inv+rc+ob: sp[r['Item Code']]['3pl:'+r['Client SKU']]+=1
def norm(s):
    s=s.upper().replace('_','-'); s=re.sub(r'-FBA$','',s)
    m=re.match(r'^AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})$',s)
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}' if m else None
ao=list(csv.DictReader(open(P+'amazon/all_orders.txt'),delimiter='\t'))
am=C.Counter(r['sku'] for r in ao)
for s,n in am.items():
    sp[None]['amz:'+s]=n
for k,c in sorted(sp.items(),key=lambda x:str(x[0])):
    print(k,dict(c)) if k else None
cands=C.defaultdict(list)
for k,c in sp.items():
    if k:
        for key in c: cands[norm(key.split(':',1)[1]) if key.split(':',1)[1] else None].append((k,key))
print({n:set(i for i,_ in l) for n,l in cands.items() if len({i for i,_ in l})>1})
print(len([n for n in cands if n]))
print('amz',[(s,norm(s),norm(s) in cands) for s in am])
