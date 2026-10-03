from lib import *
# --- Shopify variants -> hubs
prods=[json.loads(l) for l in open(EX+'shopify/products.jsonl')]
var=[p for p in prods if 'ProductVariant/' in p['id']]
vmap={}; ex=[];nm=[]; tiers=[]
for v in var:
    h=hubcode(v['sku']); vmap[v['id'].split('/')[-1]]=h
    f=[{'e':['sku/code',h],'a':'shopify/variant_id','v':v['id'].split('/')[-1]},
       {'e':['sku/code',h],'a':'sku/upc','v':v['barcode']}]
    (ex if v['sku']==h else nm).append(f)
json.dump(vmap,open(S+'vmap.json','w'))
print(len(ex),len(nm),[v['sku'] for v in var if v['sku']!=hubcode(v['sku'])])
write([x for f in ex for x in f],'shopify/products.jsonl',1)
write([x for f in nm for x in f],'shopify/products.jsonl',0.9)
# --- 3PL items via UPC (exact)
inv=list(csv.DictReader(open(EX+'3pl/inventory_snapshot.csv')))
u2h={v['barcode']:hubcode(v['sku']) for v in var}
f=[{'e':['sku/code',u2h[i['UPC']]],'a':'tpl/item_code','v':i['Item Code']} for i in inv]
assert len({x['v'] for x in f})==49==len({x['e'][1] for x in f})
write(f,'3pl/inventory_snapshot.csv',1)
# --- Amazon listings
inv=list(csv.DictReader(open(EX+'amazon/fba_inventory.txt'),delimiter='\t'))
orders=list(csv.DictReader(open(EX+'amazon/all_orders.txt'),delimiter='\t'))
lst={}
for x in orders: lst[x['sku']]=x['asin']
fn={x['sku']:(x['fnsku'],x['asin']) for x in inv}
assert all(lst[k]==v[1] for k,v in fn.items()), 'asin mismatch'
assert set(lst)==set(fn)
exa=[];nma=[]
for s,asin in lst.items():
    h=hubcode(s)
    f=[{'e':['amazon/seller_sku',s],'a':'listing/sku','v':['sku/code',h]},
       {'e':['amazon/seller_sku',s],'a':'listing/asin','v':['amazon/asin',asin]},
       {'e':['amazon/seller_sku',s],'a':'amazon/fnsku','v':fn[s][0]}]
    (exa if s==h else nma).append(f)
print(len(exa),len(nma))
write([x for f in exa for x in f],'amazon/fba_inventory.txt',1)
write([x for f in nma for x in f],'amazon/fba_inventory.txt',0.9)
