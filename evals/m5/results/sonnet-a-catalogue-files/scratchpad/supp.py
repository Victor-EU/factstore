import csv,re,sys,os
from common import *
dry='--go' not in sys.argv
qb=list(csv.DictReader(open(EX+'quickbooks/vendors.csv')))
pref={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
facts=[];svc=[];docs={}
for f in sorted(os.listdir(EX+'supplier_docs')):
    m=re.match(r'CI-PL_([A-Z]+)',f)
    if m: docs.setdefault(m[1],'supplier_docs/'+f)
for q in qb:
    d=re.match(r'sales@([a-z]+)\.example',q['Email'])
    if d:
        code=d[1].upper()
        facts+=[{"e":["supplier/code",code],"a":"supplier/code","v":code},{"e":["supplier/code",code],"a":"quickbooks/vendor_name","v":q['Vendor']}]
    else: svc.append({"e":["quickbooks/vendor_name",q['Vendor']],"a":"quickbooks/vendor_name","v":q['Vendor']})
assert {f['v'] for f in facts if f['a']=='supplier/code'}==set(pref.values())
print(len(facts)//2,len(svc))
rels=['quickbooks/vendors.csv']+sorted(docs.values())
for fs,c in [(facts,1),(svc,1)]:
    for r in write(fs,rels if c==1 and fs is facts else ['quickbooks/vendors.csv'],c,dry): print(r)
