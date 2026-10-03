from lib import *
fi=list(csv.DictReader(open(EX+'amazon/fba_inventory.txt'),delimiter='\t'))
hubs={r['sku'] for r in fi}
ident=[];t1=[];t9=[]
for r in fi:
    s=r['sku'];L=["amazon/seller_sku",s]
    ident+= [f(L,"amazon/fnsku",r['fnsku']),f(L,"listing/asin",["amazon/asin",r['asin']])]
    c=s[:-4] if s.endswith('-FBA') else s
    assert re.fullmatch(r'AH-[A-Z]{3}-\d{4}-[A-Z]{3}',c),c
    (t1 if s==c else t9).append(f(L,"listing/sku",["sku/code",c]))
write(ident,'amazon/fba_inventory.txt',label='listings')
write(t1,'amazon/fba_inventory.txt',1,label='listing exact')
write(t9,'amazon/fba_inventory.txt',0.9,label='listing -FBA')
