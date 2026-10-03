from common import *
sys.path.insert(0,S)
from docs import items
import re
prod,vs=products()
def norm(s): return re.sub(r'\s+',' ',s.lower().replace('gray','grey').replace(',','').replace('-',' ')).strip()
# --- suppliers + quickbooks vendors
QB=list(csv.DictReader(open(W+'quickbooks/vendors.csv')))
SUP={'NBBW':'Mingtu Housewares','SZHT':'Hetai Electric (SZ)','YWLX':'Lanxin Textile','DGRF':'Ruifeng Silicone','FSMJ':'Mingjia Ceramics','XMYD':'Yuanda Bamboo','NBQS':'Qisheng Stainless','HZTY':'Tianyi Glassware'}
qbn={r['Vendor'] for r in QB}; assert all(v in qbn for v in SUP.values())
tx([{"e":["supplier/code",c],"a":"quickbooks/vendor","v":v} for c,v in SUP.items()],'quickbooks/vendors.csv',0.9)
tx([{"e":["quickbooks/vendor",r['Vendor']],"a":"quickbooks/vendor","v":r['Vendor']} for r in QB if r['Vendor'] not in SUP.values()],'quickbooks/vendors.csv')
# --- hubs: sku/code + upc (barcode)
H=[]
for v in vs: H.append({"e":["sku/code",hub(v['sku'])],"a":"sku/upc","v":v['barcode']})
tx(H,'shopify/products.jsonl',1)
# --- shopify variants onto hubs, by tier
ex=[];nm=[]
for v in vs:
    f={"e":["sku/code",hub(v['sku'])],"a":"shopify/variant_id","v":gid(v['id'])}
    (ex if hub(v['sku'])==v['sku'] else nm).append(f)
tx(ex,'shopify/products.jsonl',1); tx(nm,'shopify/products.jsonl',0.9)
# --- 3pl items via UPC (exact)
upc={v['barcode']:hub(v['sku']) for v in vs}
tp=list(csv.DictReader(open(W+'3pl/inventory_snapshot.csv')))
tx([{"e":["sku/code",upc[r['UPC']]],"a":"tpl/item_code","v":r['Item Code']} for r in tp],['3pl/inventory_snapshot.csv','shopify/products.jsonl'],1)
# --- amazon listings
inv=list(csv.DictReader(open(W+'amazon/fba_inventory.txt'),delimiter='\t'))
hubs={hub(v['sku']) for v in vs}
ex=[];nm=[];seen=set()
for r in inv:
    s=r['sku']; h=s if s in hubs else re.sub(r'-FBA$','',s)
    assert h in hubs and h not in seen,s; seen.add(h)
    g=[{"e":["amazon/seller_sku",s],"a":"listing/sku","v":["sku/code",h]},
       {"e":["amazon/seller_sku",s],"a":"listing/asin","v":["amazon/asin",r['asin']]},
       {"e":["amazon/seller_sku",s],"a":"amazon/fnsku","v":r['fnsku']}]
    (ex if s==h else nm).append(g)
for grp,c in ((ex,1),(nm,0.9)): tx([f for g in grp for f in g],'amazon/fba_inventory.txt',c)
# --- factory crosswalk
tit={hub(v['sku']):norm(prod[v['__parentId']]['title']+' '+v['title']) for v in vs}
F=[];used={}
for k,v in sorted(items().items()):
    d=norm(list(v['desc'])[0]); m=[h for h,t in tit.items() if t==d]
    assert len(m)==1 and m[0] not in used,(k,d,m); used[m[0]]=k
    assert len(v['hs'])==1
    sup=k.split(':')[0]
    F+=[{"e":["sku/code",m[0]],"a":"factory/item_code","v":k},{"e":["sku/code",m[0]],"a":"sku/supplier","v":["supplier/code",sup]},{"e":["sku/code",m[0]],"a":"sku/hs_code","v":list(v['hs'])[0]}]
    docs_=sorted(v['docs'])
    tx(F[-3:],['supplier_docs/%s.pdf'%x for x in docs_],0.7)
print(len(used),'hubs with factory code; without:',hubs-set(used))
