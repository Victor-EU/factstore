from common import *
V=variants(); inv=rd('3pl/inventory_snapshot.csv'); upc2item={r['UPC']:r['Item Code'] for r in inv}
ex=[];nm=[];tp=[]
for v in V:
    c=norm(v['sku']); assert c
    item=upc2item[v['barcode']]
    # 3PL: UPC equal in Shopify and 3PL; exact
    tp+= [{"e":sku(c),"a":"tpl/item_code","v":item},{"e":sku(c),"a":"sku/upc","v":v['barcode']}] if c==v['sku'] else [{"e":sku(c),"a":"tpl/item_code","v":item}]
    grp= ex if c==v['sku'] else nm
    grp.append({"e":sku(c),"a":"shopify/variant_id","v":gid(v['id'])})
    if c!=v['sku']: nm.append({"e":sku(c),"a":"sku/upc","v":v['barcode']})
    else: pass
S=['shopify/products.jsonl','3pl/inventory_snapshot.csv']
write(ex+tp,S,1,label='exact')
write(nm,S,0.9,label='normalized')
