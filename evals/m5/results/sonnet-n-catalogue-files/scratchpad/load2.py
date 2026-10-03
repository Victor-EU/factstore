import json,csv,re,glob,os,collections as C
from pypdf import PdfReader
exec(open('load.py').read().split("if STEP=='hubs'")[0].replace("STEP=sys.argv[1]","STEP=''"))
# ---- suppliers via QuickBooks
QB={'Mingtu Housewares':'NBBW','Hetai Electric (SZ)':'SZHT','Lanxin Textile':'YWLX','Ruifeng Silicone':'DGRF','Mingjia Ceramics':'FSMJ','Yuanda Bamboo':'XMYD','Qisheng Stainless':'NBQS','Tianyi Glassware':'HZTY'}
fs=[];other=[]
for r in csv.DictReader(open(EX+'quickbooks/vendors.csv')):
    v=r['Vendor']
    if v in QB: fs+=[F(["supplier/code",QB[v]],"quickbooks/vendor",v)]
    else: other.append(F(["quickbooks/vendor",v],"quickbooks/vendor",v))
write(fs,'quickbooks/vendors.csv',0.9); write(other,'quickbooks/vendors.csv',1)
# ---- factory item codes / HS from commercial invoices
FAM={'enamel stovetop kettle':'KTL','enamel saucepan':'SAU','enamel casserole':'CSR','electric gooseneck kettle':'EKT','hand mixer':'HMX','milk frother':'MLK','waffle tea towels':'TWL','linen apron':'APR','quilted oven mitt':'MIT','silicone spatula':'SPT','silicone baking mat':'BMT','silicone stretch lids':'LID','stoneware mug':'MUG','stoneware dinner plate':'PLT','stoneware bowl':'BWL','bamboo cutting board':'CTB','bamboo utensil':'UTN','bamboo serving tray':'TRY','insulated tumbler':'TMB','insulated bottle':'BTL','stainless lunch box':'LBX','glass storage jar':'JAR','glass teapot':'TPT','glass canister':'CNR'}
COL=['speckled white','half sheet','quarter sheet','bamboo lid','steel lid','black','cream','sage','red','white','grey','silver','natural','charcoal','rust','navy','slate','clay','clear','small','large','sand']
CC={'speckled white':'SPW','half sheet':'HLF','quarter sheet':'QTR','bamboo lid':'BAM','steel lid':'STL','black':'BLK','cream':'CRM','sage':'SGE','red':'RED','white':'WHT','grey':'GRY','silver':'SLV','natural':'NAT','charcoal':'CHR','rust':'RST','navy':'NVY','slate':'SLT','clay':'CLY','clear':'CLR','small':'SML','large':'LRG','sand':'SND'}
NUM={}
for l in open(EX+'shopify/products.jsonl'):
    r=json.loads(l)
    if 'sku' in r: NUM[canon(r['sku'])]=1
PRE={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
items={};files=C.defaultdict(set)
for f in sorted(glob.glob(EX+'supplier_docs/CI-PL*.pdf')):
    rel='supplier_docs/'+os.path.basename(f)
    sup=PRE[os.path.basename(f).split('CI-PL_')[1][:2]]
    L='\n'.join(p.extract_text() for p in PdfReader(f).pages).split('\n')
    for i,l in enumerate(L):
        m=re.match(r'^(\S+)\s+(.*[a-z].*)$',l)
        if m and i+2<len(L) and re.match(r'^\d{4}\.\d{2}\.\d{4}',L[i+2]):
            d=m[2].strip(); hs=L[i+2][:12]
            fam=[k for k in FAM if d.startswith(k)]; col=[c for c in COL if d.endswith(c)][:1]
            assert len(fam)==1 and len(col)==1,d
            sku=f"AH-{FAM[fam[0]]}-"; 
            fk=FAM[fam[0]]
            cand=[s for s in NUM if s.startswith(f"AH-{fk}-") and s.endswith('-'+CC[col[0]])]
            if len(cand)!=1: print('NO MATCH',d,cand); continue
            key=(sup,m[1]); v=(cand[0],hs)
            assert items.setdefault(key,v)==v,(key,v)
            files[rel].add(key)
byfile=C.defaultdict(list); written=set()
for rel,keys in files.items():
    for key in sorted(keys):
        if key in written: continue
        written.add(key); sku,hs=items[key]
        S=["sku/code",sku]
        byfile[rel]+=[F(S,"factory/item_code",f"{key[0]}:{key[1]}"),F(S,"sku/supplier",["supplier/code",key[0]]),F(S,"sku/hs_code",hs)]
print(len(written),len({v[0] for v in items.values()}))
for rel,fs in byfile.items(): write(fs,rel,0.7)
