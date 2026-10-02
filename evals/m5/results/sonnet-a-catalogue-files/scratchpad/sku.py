import json,csv,re,collections,sys
from common import *
dry='--go' not in sys.argv
def canon(s):
    s=s.upper().replace('-FBA','')
    m=re.fullmatch(r'AH-?([A-Z]{3})-?0*(\d{1,4})-?([A-Z]{3})',s)
    assert m,s
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}'
P=[json.loads(l) for l in open(EX+'shopify/products.jsonl')]
par={p['id']:p for p in P if 'sku' not in p}
var=[p for p in P if 'sku' in p]
hubs={}
for v in var:
    c=canon(v['sku']); assert c not in hubs; hubs[c]=v
assert len(hubs)==49
byupc={v['barcode']:c for c,v in hubs.items()}
vid=lambda g:g.rsplit('/',1)[1]
t3=list(csv.DictReader(open(EX+'3pl/inventory_snapshot.csv')))
fb=list(csv.DictReader(open(EX+'amazon/fba_inventory.txt'),delimiter='\t'))
# ---- tier lists
shop_exact=[];shop_norm=[]
for c,v in hubs.items(): (shop_exact if v['sku']==c else shop_norm).append(c)
f=[]  # shopify tx exact
def sh(c,v): return [{"e":["sku/code",c],"a":"sku/code","v":c},{"e":["sku/code",c],"a":"shopify/variant_id","v":vid(v['id'])},{"e":["sku/code",c],"a":"sku/upc","v":v['barcode']}]
tx1=[x for c in shop_exact for x in sh(c,hubs[c])]
tx2=[x for c in shop_norm for x in sh(c,hubs[c])]
# 3pl by UPC (exact)
tx3=[];t3n=0
for r in t3:
    c=byupc[r['UPC']]
    tx3.append({"e":["sku/code",c],"a":"tpl/item_code","v":r['Item Code']})
# amazon
tx4=[];tx5=[];seen=set()
for r in fb:
    c=canon(r['sku']); assert c in hubs and c not in seen; seen.add(c)
    fs=[{"e":["sku/code",c],"a":"amazon/seller_sku","v":r['sku']},{"e":["sku/code",c],"a":"amazon/asin","v":r['asin']},{"e":["sku/code",c],"a":"amazon/fnsku","v":r['fnsku']}]
    (tx4 if r['sku']==c else tx5).extend(fs)
# factory
T=json.load(open('/tmp/claude-501/factory.json'))
desc={c:(par[v['__parentId']]['title']+' '+v['title']).lower() for c,v in hubs.items()}
dn=lambda s:re.sub(r'[^a-z0-9]+',' ',s).strip()
inv=collections.defaultdict(list)
for c,d in desc.items(): inv[dn(d)].append(c)
tx6=[];used=set()
for k,((d,hs),) in ((k,v) for k,v in T.items()):
    cands=inv.get(dn(d),[])
    if len(cands)!=1: print('NOMATCH',k,d,cands); continue
    c=cands[0]; assert c not in used; used.add(c)
    sup=k.split(':')[0]
    tx6+=[{"e":["sku/code",c],"a":"factory/item_code","v":k},{"e":["sku/code",c],"a":"sku/hs_code","v":hs},{"e":["sku/code",c],"a":"sku/supplier","v":["supplier/code",sup]},{"e":["supplier/code",sup],"a":"supplier/code","v":sup}]
print(len(tx1)//3,len(tx2)//3,len(tx3),len(tx4)//3,len(tx5)//3,len(tx6)//4,'unmatched hubs',[c for c in hubs if c not in used])
print(shop_norm)
json.dump({'tx1':tx1,'tx2':tx2,'tx3':tx3,'tx4':tx4,'tx5':tx5,'tx6':tx6},open('skutx.json','w'))
if not dry:
    pdfs=sorted('supplier_docs/'+f for f in os.listdir(EX+'supplier_docs') if f.startswith('CI-PL'))
    for facts,rels,conf in [(tx1,['shopify/products.jsonl'],1),(tx2,['shopify/products.jsonl'],0.9),(tx3,['3pl/inventory_snapshot.csv','shopify/products.jsonl'],1),(tx4,['amazon/fba_inventory.txt'],1),(tx5,['amazon/fba_inventory.txt'],0.9),(tx6,pdfs+['shopify/products.jsonl'],0.7)]:
        for r in write(facts,rels,conf): print(r.tx if hasattr(r,'tx') else r)
