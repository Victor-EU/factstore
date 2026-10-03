from common import *
P=[json.loads(l) for l in open(EX+'/shopify/products.jsonl')]
V=[p for p in P if 'ProductVariant' in p['id']]
inv={r['UPC']:r for r in csv.DictReader(open(EX+'/3pl/inventory_snapshot.csv'))}
a=[];b=[]
for v in V:
    code=code_norm(v['sku']); assert code
    e=["sku/code",code]
    fs=[{"e":e,"a":"sku/code","v":code},{"e":e,"a":"sku/upc","v":v['barcode']},{"e":e,"a":"shopify/variant_id","v":v['id'].rsplit('/',1)[1]}]
    (a if code==v['sku'] else b).extend(fs)
write(a,'shopify/products.jsonl',1,label='hubs exact spelling')
write(b,'shopify/products.jsonl',0.9,label='hubs normalized spelling')
# 3pl item codes via UPC
f=[]
for u,r in inv.items(): f.append({"e":["sku/upc",u],"a":"tpl/item_code","v":r['Item Code']})
write(f,'3pl/inventory_snapshot.csv',1,label='tpl item codes via upc')
