from load import *
hub=json.load(open(os.path.dirname(os.path.abspath(__file__))+'/hub.json'))
codes=set(hub.values())
# ---- 3PL item codes: exact on UPC
inv=list(csv.DictReader(open(X+'3pl/inventory_snapshot.csv')))
f=[{"e":["sku/upc",r['UPC']],"a":"tpl/item_code","v":r['Item Code']} for r in inv]
print('3pl',tx(f,'3pl/inventory_snapshot.csv',1))
# ---- Amazon: seller sku normalized onto hub; asin/fnsku ride on the same row
fi=list(csv.DictReader(open(X+'amazon/fba_inventory.txt'),delimiter='\t'))
f=[]
for r in fi:
    c=canon(r['sku']); assert c in codes,c
    h=["sku/code",c]
    f+=[{"e":h,"a":"amazon/seller_sku","v":r['sku']},{"e":h,"a":"amazon/asin","v":r['asin']},{"e":h,"a":"amazon/fnsku","v":r['fnsku']}]
assert len({canon(r['sku']) for r in fi})==25
print('amazon',tx(f,'amazon/fba_inventory.txt',0.9))
# ---- factory items: corroborated on description
import difflib
vs=read_shopify_products(); prod={}
for l in open(X+'shopify/products.jsonl'):
    d=json.loads(l)
    if 'Product/' in d['id']: prod[d['id']]=d
def toks(s):
    s=s.lower().replace(',',' ').replace('grey','gray').replace('speckled white','speckled').replace('natural','nat')
    return set(re.findall(r'[a-z0-9.\-]+',s))
items=factory.parse(); f=[];seen={}
for (sup,code),v in sorted(items.items()):
    d=sorted(v['desc'])[0]; dt=toks(d)
    sc=sorted(((len(dt&toks(prod[x['__parentId']]['title']+' '+x['title']))/len(dt|toks(prod[x['__parentId']]['title']+' '+x['title'])),hub[x['id']]) for x in vs),reverse=True)
    assert sc[0][0]==1.0 and sc[1][0]<0.8,(code,sc[:2])
    c=sc[0][1]; assert c not in seen; seen[c]=(sup,code)
    assert len(v['hs'])==1
    h=["sku/code",c]
    ff=[{"e":h,"a":"factory/item_code","v":f"{sup}:{code}"},{"e":h,"a":"sku/supplier","v":["supplier/code",sup]},{"e":h,"a":"sku/hs_code","v":list(v['hs'])[0]}]
    doc=sorted(x for x in v['doc'] if x.startswith('CI-PL'))[0]
    f+=ff; n=tx(ff,'supplier_docs/'+doc,0.7)
assert len(seen)==49
print('factory',len(f))
json.dump(f,open(os.path.dirname(os.path.abspath(__file__))+'/factory_facts.json','w'))
