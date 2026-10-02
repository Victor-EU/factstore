import sys,re; sys.path.insert(0,'.')
from parse import *
import factstore
q=lambda s: factstore.query(s).rows
PO=dict((n,e) for e,n in q('select e,v from "po/number"'))
PI={p:n for p,n in q('select p.v,n.v from "po/pi_number" p join "po/number" n using(e)')}
ETD={n:d for n,d in q('select n.v,d.v from "po/etd" d join "po/number" n using(e)')}
ST={n:d for n,d in q('select n.v,d.v from "po/status" d join "po/number" n using(e)')}
CONT={c:h for h,c in q('select h.v,c.v from "shipment/container_no" c join "shipment/hbl" h using(e)')}
def next_date(m,d,after):
    after=after.date()
    for y in (after.year,after.year+1):
        try:
            x=dt.date(y,m,d)
        except ValueError: continue
        if x>=after: return x
def chat_events():
    out=[]; last_po={}
    for c in sorted(chats(),key=lambda c:(c['file'],c['n'])):
        f=c['file']; t=c['text']; cn=c['date'].astimezone(SH)
        mpo=re.search(r'PO-\d{4}-\d{4}',t)
        if mpo and c['sender'].startswith('Maya'): last_po[f]=mpo.group(0)
        if mf:=re.match(r'\[文件\] (.+)\.pdf$',t):
            if mf.group(1) in PI: last_po[f]=PI[mf.group(1)]
        ev=None
        if m:=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',t):
            ev=('etd',m.group(1),next_date(int(m.group(2)),int(m.group(3)),cn),'named')
        elif m:=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',t):
            ev=('etd',m.group(1),next_date(int(m.group(2)),int(m.group(3)),cn),'named')
        elif m:=re.search(r'(\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',t):
            po=PI.get(m.group(1)); ev=('etd',po,next_date(int(m.group(2)),int(m.group(3)),cn),'pi:'+m.group(1))
        elif (m:=re.search(r'^ETD (?:around )?(\d+)/(\d+)',t)) or (m:=re.search(r'^交期(\d+)月(\d+)号左右',t)):
            ev=('etd',last_po.get(f),next_date(int(m.group(1)),int(m.group(2)),cn),'loose')
        elif m:=re.search(r'container loaded: ([A-Z]{4}\d{7})',t):
            ev=('cont',last_po.get(f),m.group(1),'loose')
        elif '大货生产中' in t: ev=('prod',last_po.get(f),None,'loose')
        elif re.search(r'^(Received, thank you|收到，谢谢|定金收到了，马上安排生产)$',t): ev=('ack',last_po.get(f),None,'loose')
        if ev: out.append((c,)+ev)
    return out
if __name__=='__main__':
    for c,k,po,v,how in chat_events():
        if k=='etd':
            print(c['url'],c['date'].strftime('%Y-%m-%d %H:%M'),k,po,v,how,'store:',ETD.get(po),'' if ETD.get(po)==v else '<<DIFF')
        elif k=='cont': print(c['url'],k,po,v,'in store' if v in CONT else 'NOT IN STORE')
        elif k in('prod','ack') and ST.get(po) in ('draft','sent','confirmed'): print(c['url'],c['date'].strftime('%Y-%m-%d'),k,po,ST.get(po),c['text'][:30])
