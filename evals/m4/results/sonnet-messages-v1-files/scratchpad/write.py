import sys,json,re,factstore
from datetime import datetime
from emails import events,D,inst,shipbyvessel,shipbycont,TZ
import chats
DRY='--commit' not in sys.argv
def tx(doc,conf,facts):
    h=['document/hash',doc['hash']]
    f=[dict(e=h,a='document/url',v=doc['url']),dict(e='tmp:tx',a='core/evidence',v=h),dict(e='tmp:tx',a='core/confidence',v=conf)]
    f+=[dict(e=e,a=a,v=v) for e,a,v in facts]
    return f
plan=[]  # (utc, label, facts)
sob={}
for e in events:
    d=e['doc'];k=e['kind'];u=d['utc']
    if k=='booking':
        s=shipbyvessel.get(e['vessel'])
        lab=e['so']
        body=[(['shipment/booking_no',e['so']],'shipment/mode',e['mode']),(['shipment/booking_no',e['so']],'shipment/vessel',e['vessel']),
              (['shipment/booking_no',e['so']],'shipment/origin',e['o']),(['shipment/booking_no',e['so']],'shipment/destination',e['d']),
              (['shipment/booking_no',e['so']],'shipment/etd',inst(e['etd'],e['o'])),(['shipment/booking_no',e['so']],'shipment/eta',inst(e['eta'],e['d'])),
              (['shipment/booking_no',e['so']],'shipment/status','booked')]
        if s:
            sob[e['so']]=s['hbl']
            loose=any(not re.fullmatch(r'PO[-#]\d{4}-\d{4}',x) for x in e['rawpos'])
            plan.append((u,'booking-link '+lab,tx(d,'0.9' if loose else '1',[(['shipment/hbl',s['hbl']],'shipment/booking_no',e['so'])])))
            plan.append((u,'booking '+lab,tx(d,'1',body[1:] if False else body)))
        else:
            plan.append((u,'booking-new '+lab,tx(d,'1',body)))
    elif k=='roll':
        b=['shipment/booking_no',e['so']]
        o=[x for x in events if x['kind']=='booking' and x['so']==e['so']][0]
        plan.append((u,'roll '+e['so'],tx(d,'1',[(b,'shipment/etd',inst(e['etd'],o['o'])),(b,'shipment/eta',inst(e['eta'],o['d']))])))
    elif k=='prealert':
        s=D['ship'][e['hbl']];b=['shipment/hbl',e['hbl']]
        fs=[(b,'shipment/etd',inst(e['atd'],s['o'])),(b,'shipment/eta',inst(e['eta'],s['d'])),(b,'shipment/status','departed')]
        if e['cont']: fs.insert(0,(b,'shipment/container_no',e['cont']))
        plan.append((u,'prealert '+e['hbl'],tx(d,'1',fs)))
    elif k=='eta':
        s=D['ship'][e['hbl']]
        plan.append((u,'eta '+e['hbl'],tx(d,'1',[(['shipment/hbl',e['hbl']],'shipment/eta',inst(e['eta'],s['d']))])))
    elif k=='arrival':
        b=['shipment/hbl',e['hbl']]
        plan.append((u,'arrival '+e['hbl'],tx(d,'1',[(b,'shipment/status','arrived'),(b,'shipment/eta',inst(e['date'],e['port']))])))
    elif k=='entry':
        r=e['ref']; hbl=r if r in D['ship'] else shipbycont[r]['hbl']
        en=['customs/entry_no',e['entry']]
        filed=datetime.strptime(d['date'][5:25],'%d %b %Y %H:%M:%S').date().isoformat()
        plan.append((u,'entry '+e['entry'],tx(d,'1',[(en,'customs/shipment',['shipment/hbl',hbl]),(en,'customs/filed_on',filed),(en,'customs/entered_value','%.2f'%e['val']),(en,'customs/duty','%.2f'%e['duty']),(en,'customs/fees','%.2f'%e['fees']),(en,'core/currency','USD')])))
    elif k=='receipt':
        r=e['ref']; hbl=r if r in D['ship'] else shipbycont[r]['hbl']; b=['shipment/hbl',hbl]
        dt=datetime.strptime(d['date'][5:31],'%d %b %Y %H:%M:%S %z').isoformat()
        plan.append((u,'receipt '+e['rcv'],tx(d,'0.9',[(b,'shipment/status','delivered'),(b,'shipment/delivered_at',dt)])))
for c in chats.out:
    if c['kind']=='slip':
        plan.append((c['doc']['utc'],'slip '+c['po'],tx(c['doc'],'0.9',[(['po/number',c['po']],'po/etd',c['etd'])])))
plan.sort(key=lambda p:p[0])
print(len(plan),'transactions')
ok=0
for u,lab,f in plan:
    r=factstore.transact(f,dry_run=DRY)
    ok+=1
    if DRY and ok<=3 or '--v' in sys.argv: print(lab,r)
print('done',ok)
