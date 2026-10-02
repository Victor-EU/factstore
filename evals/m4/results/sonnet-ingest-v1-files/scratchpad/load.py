import json,sys,datetime,factstore
D=json.load(open('docs.json'))
DRY=len(sys.argv)>1 and sys.argv[1]=='dry'
sup={r[0]:r[1] for r in factstore.query('select c.v,e from "supplier/code" c').rows} if False else None
q=lambda s:factstore.query(s).rows
sup={c:e for e,c in q('select e,v from "supplier/code"')}
supinfo={c:dict(name_cn=a,address=b,incoterm=i,pay=p) for c,a,b,i,p in q('select c.v,n.v,a.v,i.v,p.v from "supplier/code" c join "supplier/name_cn" n using(e) join "supplier/address" a using(e) join "supplier/incoterm" i using(e) join "supplier/payment_terms" p using(e)')}
hs={c:h for c,h in q('select f.v,h.v from "factory/item_code" f join "sku/hs_code" h using(e)')}
order={'pi':0,'qc':1,'cipl':2}
D.sort(key=lambda d:(d['date'],order[d['kind']],d['file']))
done=lambda h:q(f"select count(*) from \"core/evidence\" ev join \"document/hash\" h on h.e=ev.v where h.v='{h}'")[0][0]>0
lines={}  # po -> {item:(key)}
cur={'RMB':'CNY','USD':'USD'}
rep={'hs':[],'skipped':[],'supdiff':[]}
cnt={'pi':0,'cipl':0,'qc':0}
def tx(d,facts):
    h=d['hash']
    f=[{'e':['document/hash',h],'a':'document/url','v':d['url']},
       {'e':'tmp:tx','a':'core/evidence','v':['document/hash',h]},
       {'e':'tmp:tx','a':'core/confidence','v':'1'}]+facts
    r=factstore.transact(f,dry_run=DRY)
    return r
for d in D:
    if done(d['hash']): rep['skipped'].append(d['file']); continue
    p=d.get('po')
    if d['kind']=='pi':
        ci=d['sup']; po=['po/number',p]
        etd=datetime.datetime.strptime(d['etd'],'%b %d, %Y').date().isoformat()
        f=[{'e':po,'a':'po/pi_number','v':d['pi']},{'e':po,'a':'po/supplier','v':sup[ci]},
           {'e':po,'a':'po/etd','v':etd},{'e':po,'a':'core/currency','v':cur[d['cur']]},
           {'e':po,'a':'po/status','v':'confirmed'}]
        s=supinfo[ci]
        if s['incoterm']!=d['inco'] or s['pay']!=d['pay']: rep['supdiff'].append((d['file'],s['incoterm'],d['inco'],s['pay'],d['pay']))
        lines[p]={}
        for n,(item,qty,price,amt,ctn) in enumerate(d['rows'],1):
            k=f'{p}/{n}'; lines[p][item]=k
            f+=[{'e':['po_line/key',k],'a':'core/part_of','v':po},
                {'e':['po_line/key',k],'a':'po_line/sku','v':['factory/item_code',f'{ci}:{item}']},
                {'e':['po_line/key',k],'a':'po_line/quantity','v':str(qty)},
                {'e':['po_line/key',k],'a':'po_line/unit_price','v':price}]
        tx(d,f)
    elif d['kind']=='qc':
        e=['qc/report_no',d['report']]
        tx(d,[{'e':e,'a':'qc/po','v':['po/number',p]},{'e':e,'a':'qc/inspected_on','v':d['date']},
              {'e':e,'a':'qc/result','v':d['result']},{'e':e,'a':'qc/inspector','v':d['agency'].title()},
              {'e':e,'a':'qc/sample_size','v':str(d['n'])}])
    else:
        sh=['shipment/hbl',d['hbl']]; ci=d['sup']
        f=[{'e':sh,'a':'shipment/vessel','v':d['vessel']},{'e':sh,'a':'shipment/origin','v':d['origin']},
           {'e':sh,'a':'shipment/destination','v':d['dest']}]
        if d['container']!='LCL': f.append({'e':sh,'a':'shipment/container_no','v':d['container']})
        for item,hsc,qty,_ in d['rows']:
            code=f'{ci}:{item}'
            if hs[code]!=hsc: rep['hs'].append((d['file'],code,hs[code],hsc))
            pk=lines[p][item]; k=f"{d['hbl']}/{pk}"; l=['shipment_line/key',k]
            f+=[{'e':l,'a':'core/part_of','v':sh},{'e':l,'a':'shipment_line/po_line','v':['po_line/key',pk]},
                {'e':l,'a':'shipment_line/quantity','v':str(qty)},{'e':l,'a':'shipment_line/cartons','v':str(d['pl'][item])}]
        tx(d,f)
    cnt[d['kind']]+=1
print(cnt); print(json.dumps(rep,indent=0)[:3000])
