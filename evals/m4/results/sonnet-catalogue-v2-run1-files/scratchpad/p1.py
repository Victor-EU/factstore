from load import *
# --- suppliers from QuickBooks vendors (normalized name/domain match to supplier docs + wechat)
rows=list(csv.DictReader(open(X+'quickbooks/vendors.csv')))
sup_by_name={}
for k,v in factory.SUP.items(): sup_by_name[k]=v
f=[]
for r in rows:
    dom=r['Email'].split('@')[1].split('.')[0].upper()
    nm=next((v for k,v in factory.SUP.items() if k in r['Company name'].upper()),None)
    if nm is None: print('not a supplier:',r['Vendor']); continue
    assert nm==dom,(nm,dom)
    f+= [{"e":["supplier/code",nm],"a":"quickbooks/vendor","v":r['Vendor']}]
print(len(f)); print('quickbooks vendors',tx(f,'quickbooks/vendors.csv',0.9))
# --- SKU hubs from Shopify products
var=read_shopify_products()
hub={}
facts_ex=[];facts_nm=[]
for v in var:
    c=canon(v['sku']); hub[v['id']]=c
    base=[{"e":["sku/code",c],"a":"shopify/variant_id","v":gid(v['id'])}]
    (facts_ex if v['sku']==c else facts_nm).extend(base)
assert len(set(hub.values()))==49
print('variants exact',len(facts_ex),'normalized',len(facts_nm))
upc=[{"e":["sku/code",hub[v['id']]],"a":"sku/upc","v":v['barcode']} for v in var]
print(tx(upc+facts_ex,'shopify/products.jsonl',1))
print(tx(facts_nm,'shopify/products.jsonl',0.9))
json.dump(hub,open(S_:=os.path.dirname(os.path.abspath(__file__))+'/hub.json','w'))
