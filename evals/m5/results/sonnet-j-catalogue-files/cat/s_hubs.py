from lib import *
V=shopify_variants()
ex=[];nm=[]
for v in V:
    c=canon(v['sku']); vid=gid(v['id'])
    base=[f(["sku/code",c],"sku/upc",v['barcode']),f(["sku/code",c],"shopify/variant_id",vid)]
    (ex if v['sku']==c else nm).extend(base)
print(len(ex)//2,len(nm)//2)
assert len({canon(v['sku']) for v in V})==49
write(ex,'shopify/products.jsonl',1,label='hub exact')
write(nm,'shopify/products.jsonl',0.9,label='hub normalized')
# 3PL item codes by UPC
inv=list(csv.DictReader(open(EX+'3pl/inventory_snapshot.csv')))
fa=[f(["sku/upc",r['UPC']],"tpl/item_code",r['Item Code']) for r in inv]
write(fa,'3pl/inventory_snapshot.csv',1,label='3pl item_code by UPC')
