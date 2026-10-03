from lib import *
rc=list(csv.DictReader(open(X+'3pl/receipts.csv')))
ob=list(csv.DictReader(open(X+'3pl/outbound.csv')))
hr,hrf=doc_facts('3pl/receipts.csv'); ho,hof=doc_facts('3pl/outbound.csv'); write(hrf+hof,[])
f=[];bad=set();rpo=C.defaultdict(set)
for r in rc:
    re_=["tpl/receipt_no",r['Receipt #']]
    le=["tpl/receipt_line",f"{r['Receipt #']}/{r['Item Code']}"]
    f+=[{"e":re_,"a":"tpl/receipt_no","v":r['Receipt #']},{"e":le,"a":"core/part_of","v":re_},
        {"e":le,"a":"line/sku","v":["tpl/item_code",r['Item Code']]}]
    for p in re.split(r'\s*/\s*',r['Reference'].strip()):
        if not p: continue
        if re.match(r'^PO-\d{4}-\d{4}$',p): rpo[r['Receipt #']].add(p)
        else: bad.add(p)
print('bad PO refs',bad, 'receipts w/o po',len({r['Receipt #'] for r in rc})-len(rpo))
for k,ps in rpo.items():
    for p in sorted(ps): f.append({"e":["tpl/receipt_no",k],"a":"receipt/po","v":["po/number",p]})
print(write(f,[hr],1))
f=[]
for r in ob:
    ref=r['Order Reference']
    whole=["shopify/order_name",ref] if ref.startswith('#') else ["amazon/fba_shipment_id",ref]
    le=["tpl/outbound_line",f"{ref}/{r['Item Code']}"]
    f+=[{"e":le,"a":"core/part_of","v":whole},{"e":le,"a":"line/sku","v":["tpl/item_code",r['Item Code']]}]
print(write(f,[ho],1))
