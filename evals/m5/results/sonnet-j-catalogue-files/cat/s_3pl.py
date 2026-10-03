from lib import *
rc=list(csv.DictReader(open(EX+'3pl/receipts.csv')))
facts=[];bad=collections.Counter()
for r in rc:
    R=["tpl/receipt_no",r['Receipt #']]
    l=["tpl/receipt_line",r['Receipt #']+'/'+r['Item Code']]
    facts+=[f(R,"tpl/receipt_no",r['Receipt #']),f(l,"core/part_of",R),f(l,"line/sku",["tpl/item_code",r['Item Code']])]
    for p in filter(None,[x.strip() for x in r['Reference'].split('/')]):
        if re.fullmatch(r'PO-\d{4}-\d{4}',p): facts.append(f(R,"receipt/po",["po/number",p]))
        else: bad[p]+=1
print('bad PO refs',bad)
write(facts,'3pl/receipts.csv',label='receipts')
ob=[];
for r in csv.DictReader(open(EX+'3pl/outbound.csv')):
    ref=r['Order Reference']
    if ref.startswith('#'): w=["shopify/order_name",ref]
    elif re.fullmatch(r'FBA\w{9}',ref): w=["amazon/fba_shipment_id",ref]
    else: print('odd',ref);continue
    l=["tpl/outbound_line",ref+'/'+r['Item Code']]
    ob+=[f(l,"core/part_of",w),f(l,"line/sku",["tpl/item_code",r['Item Code']])]
write(ob,'3pl/outbound.csv',label='outbound')
