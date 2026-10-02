import json,sys,datetime
import factstore
docs=json.load(open('docs.json'))
DRY=len(sys.argv)<2 or sys.argv[1]=='dry'; PROBE=len(sys.argv)>1 and sys.argv[1]=='probe'
sup={'NINGBO MINGTU HOUSEWARES CO., LTD.':'NBBW','SHENZHEN HETAI ELECTRIC APPLIANCE CO., LTD.':'SZHT','YIWU LANXIN TEXTILE CO., LTD.':'YWLX','DONGGUAN RUIFENG SILICONE PRODUCTS CO., LTD.':'DGRF','FOSHAN MINGJIA CERAMICS CO., LTD.':'FSMJ','XIAMEN YUANDA BAMBOO PRODUCTS CO., LTD.':'XMYD','NINGBO QISHENG STAINLESS STEEL CO., LTD.':'NBQS','HANGZHOU TIANYI GLASSWARE CO., LTD.':'HZTY'}
supid={'NBBW':1109,'SZHT':1110,'YWLX':1111,'DGRF':1112,'FSMJ':1113,'XMYD':1114,'NBQS':1115,'HZTY':1116}
order={'PI':0,'QC':1,'CI':2}
docs.sort(key=lambda d:(d['date'] if d['kind']!='PI' else d['date'],order[d['kind']],d['file']))
RANK={s:i for i,s in enumerate(['draft','sent','confirmed','in_production','ready','shipped','received'])}
status={}; poinfo={}; shipped_qty={}
def adv(po,new,facts):
    if RANK[new]>RANK.get(status.get(po),-1):
        status[po]=new; facts.append({'e':['po/number',po],'a':'po/status','v':new})
mon={m:i+1 for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}
def pdate(s):
    m,d,y=s.replace(',','').split(); return f"{y}-{mon[m]:02d}-{int(d):02d}"
def run(d,facts,nconf='1'):
    pre=[{'e':['document/hash',d['hash']],'a':'document/url','v':'supplier_docs/'+d['file']},
         {'e':'tmp:tx','a':'core/evidence','v':['document/hash',d['hash']]},
         {'e':'tmp:tx','a':'core/confidence','v':nconf}]
    return pre+facts
log=[]
for d in docs:
    f=[]
    if d['kind']=='PI':
        s=sup[d['supplier_en']]; po=['po/number',d['po']]
        cur=d['items'][0]['cur']; cur={'RMB':'CNY'}.get(cur,cur)
        f+=[{'e':po,'a':'po/pi_number','v':d['pi']},{'e':po,'a':'po/supplier','v':supid[s]},
            {'e':po,'a':'po/etd','v':pdate(d['etd'])},{'e':po,'a':'core/currency','v':cur}]
        poinfo[d['po']]={'s':s,'lines':{}}
        for n,i in enumerate(d['items'],1):
            key=f"{d['po']}/{n}"; lk=['po_line/key',key]
            poinfo[d['po']]['lines'][i['code']]=(key,float(i['qty']))
            f+=[{'e':lk,'a':'core/part_of','v':po},{'e':lk,'a':'po_line/sku','v':['factory/item_code',f"{s}:{i['code']}"]},
                {'e':lk,'a':'po_line/quantity','v':i['qty']},{'e':lk,'a':'po_line/unit_price','v':i['price']}]
        e=supid[s]
        f+=[{'e':e,'a':'supplier/name_cn','v':d['cn']},{'e':e,'a':'supplier/address','v':d['addr']},
            {'e':e,'a':'supplier/incoterm','v':d['incoterm']},{'e':e,'a':'supplier/payment_terms','v':d['pay']}]
        adv(d['po'],'confirmed',f)
    elif d['kind']=='QC':
        q=['qc/report_no',d['report']]
        f+=[{'e':q,'a':'qc/po','v':['po/number',d['po']]},{'e':q,'a':'qc/inspected_on','v':d['date']},
            {'e':q,'a':'qc/result','v':d['result']},{'e':q,'a':'qc/inspector','v':d['agency'].title()},
            {'e':q,'a':'qc/sample_size','v':d['sample']}]
        if d['result']=='PASS': adv(d['po'],'ready',f)
    else:
        sh=['shipment/hbl',d['hbl']]; p=poinfo[d['po']]
        if d['container']!='LCL': f.append({'e':sh,'a':'shipment/container_no','v':d['container']})
        f+=[{'e':sh,'a':'shipment/vessel','v':d['vessel']},{'e':sh,'a':'shipment/origin','v':d['origin']},{'e':sh,'a':'shipment/destination','v':d['dest']}]
        for r in d['rows']:
            key,oq=p['lines'][r['code']]; lk=['shipment_line/key',f"{d['hbl']}/{key}"]
            f+=[{'e':lk,'a':'core/part_of','v':sh},{'e':lk,'a':'shipment_line/po_line','v':['po_line/key',key]},
                {'e':lk,'a':'shipment_line/quantity','v':r['qty']},{'e':lk,'a':'shipment_line/cartons','v':d['pl'][r['code']]['ctns']}]
            shipped_qty[key]=shipped_qty.get(key,0)+float(r['qty'])
        if all(shipped_qty.get(k,0)>=q for k,q in p['lines'].values()): adv(d['po'],'shipped',f)
    tx=run(d,f)
    if DRY: log.append((d['file'],len(tx)))
    elif PROBE and len(log)>=4: break
    else:
        r=factstore.transact(tx,dry_run=PROBE); log.append((d['file'],str(r)[:120]))
print(len(log)); print(log[:3]); print(log[-2:])
json.dump(status,open('status.json','w'))
