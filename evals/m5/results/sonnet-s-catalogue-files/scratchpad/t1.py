from common import *
var=shopify_products()
print([ (v['sku'],hubcode(v['sku'])) for v in var if v['sku']!=hubcode(v['sku'])])
am=list(csv.DictReader(open(X+'amazon/fba_inventory.txt'),delimiter='\t'))
hubs={hubcode(v['sku']) for v in var}
for r in am:
    s=r['sku']; b=re.sub(r'-FBA$','',s)
    print(s, b in hubs, b==s)
