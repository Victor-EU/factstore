from common import *
sys.path.insert(0,'.')
from items import items
import glob
var=shopify_products()
prods={r['id']:r for r in [json.loads(l) for l in open(X+'shopify/products.jsonl')]}
# supplier hubs + quickbooks vendors
QB={'Mingtu Housewares':'NBBW','Hetai Electric (SZ)':'SZHT','Lanxin Textile':'YWLX','Ruifeng Silicone':'DGRF','Mingjia Ceramics':'FSMJ','Yuanda Bamboo':'XMYD','Qisheng Stainless':'NBQS','Tianyi Glassware':'HZTY'}
vend=list(csv.DictReader(open(X+'quickbooks/vendors.csv')))
f=[]; f2=[]
for v in vend:
    nm=v['Vendor']
    if nm in QB: f.append({'e':['supplier/code',QB[nm]],'a':'quickbooks/vendor','v':nm})
    else: f2.append({'e':['quickbooks/vendor',nm],'a':'quickbooks/vendor','v':nm})
write(f,['quickbooks/vendors.csv'],0.9,label='supplier<->qb vendor (legal name equals factory docs)')
write(f2,['quickbooks/vendors.csv'],None,label='other qb vendors')
# SKU hubs
def vid(v): return v['id'].split('/')[-1]
exact=[];norm=[]
tpl={r['UPC']:r['Item Code'] for r in lines('3pl/inventory_snapshot.csv')}
for v in var:
    h=hubcode(v['sku']); e=['sku/code',h]
    fs=[{'e':e,'a':'shopify/variant_id','v':vid(v)},{'e':e,'a':'sku/upc','v':v['barcode']},{'e':e,'a':'tpl/item_code','v':tpl[v['barcode']]}]
    (exact if v['sku']==h else norm).extend(fs)
rels=['shopify/products.jsonl','3pl/inventory_snapshot.csv']
write(exact,rels,1,label='hubs exact (shopify sku = hub code; upc = 3pl upc)')
write(norm,rels,0.9,label='hubs normalized (shopify sku misspelt)')
# listings
am=list(csv.DictReader(open(X+'amazon/fba_inventory.txt'),delimiter='\t'))
ex=[];nm=[]
for r in am:
    s=r['sku']; h=re.sub(r'-FBA$','',s); e=['amazon/seller_sku',s]
    fs=[{'e':e,'a':'listing/sku','v':['sku/code',h]},{'e':e,'a':'listing/asin','v':['amazon/asin',r['asin']]},{'e':e,'a':'amazon/fnsku','v':r['fnsku']}]
    (ex if s==h else nm).extend(fs)
write(ex,['amazon/fba_inventory.txt'],1,label='listings exact')
write(nm,['amazon/fba_inventory.txt'],0.9,label='listings -FBA suffix')
# factory crosswalk by description
def toks(s): return set(re.findall(r'[a-z0-9]+',s.lower()))
cand={}
for v in var:
    p=prods[v['__parentId']]; cand[hubcode(v['sku'])]=toks(p['title']+' '+v['title'])
fs=[];rels=set()
for k,d in items.items():
    desc=sorted(d['desc'])[0]; dt=toks(desc)
    hits=[h for h,t in cand.items() if t==dt]
    assert len(hits)==1,(k,hits)
    e=['sku/code',hits[0]]; sup=k.split(':')[0]
    assert len(d['hs'])==1
    fs+=[{'e':e,'a':'factory/item_code','v':k},{'e':e,'a':'sku/supplier','v':['supplier/code',sup]},{'e':e,'a':'sku/hs_code','v':sorted(d['hs'])[0]}]
    rels|={'supplier_docs/'+x.replace('.pdf.txt','.pdf') for x in d['f']}
rels=sorted(rels)
print(len(rels),'docs')
write(fs,rels+[],0.7,chunk=100000,label='factory codes by description')
