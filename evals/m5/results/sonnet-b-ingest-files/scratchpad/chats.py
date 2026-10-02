import re,hashlib,datetime as dt,glob,os
from model import *
WC='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-b-sr5iskv6/ingest/work/exports/wechat'
def yearless(m,d,after_cn_date):
    for y in (after_cn_date.year,after_cn_date.year+1):
        try: c=dt.date(y,m,d)
        except ValueError: continue
        if c>=after_cn_date: return c
def chat_messages():
    out=[]
    for f in sorted(glob.glob(WC+'/*.txt')):
        base=os.path.basename(f); sup=base.split('_')[0]
        t=open(f,encoding='utf-8').read()
        msgs=re.split(r'\n\n(?=\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )',t)[1:]
        for n,m in enumerate(msgs,1):
            m=m.rstrip('\n')
            hdr,_,body=m.partition('\n')
            ts=dt.datetime.strptime(hdr[:19],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            sender=hdr[20:]
            out.append(dict(file=base,sup=sup,n=n,ts=ts,sender=sender,body=body,mine=sender.startswith('Maya'),
               hash=hashlib.sha256(m.encode('utf-8')).hexdigest(),url=f'wechat/{base}#{n}'))
    return out
def chat_events():
    ev=[];ctx={}
    for m in chat_messages():
        sup=m['sup'];b=m['body'];cn=m['ts'].astimezone(CN).date()
        c=ctx.setdefault(sup,dict(po=None,dep=None))
        mf=re.match(r'\[文件\] (.+?)(?:\.pdf)?$',b)
        if mf:
            k=mf.group(1)
            if k in PIBYNUM: c['po']=PIBYNUM[k]['po']
            continue
        md=re.search(r'Deposit paid today, (USD|CNY) ([\d,.]+)',b)
        md2=re.search(r'sent the deposit for (PO-\d{4}-\d{4}) \((USD|CNY) ([\d,.]+)\)',b)
        if md or md2:
            if md: po=c['po'];named=False;amt=md.group(2)
            else: po=md2.group(1);named=True;amt=md2.group(3)
            c['dep']=dict(po=po,named=named,amt=amt,n=m['n'])
            continue
        if b in ('Received, thank you','收到，谢谢') and not m['mine'] and c.get('dep') and not c['dep'].get('acked'):
            c['dep']['acked']=True
            ev.append(dict(kind='deposit_ack',msg=m,po=c['dep']['po'],named=c['dep']['named'],amt=c['dep']['amt']))
            continue
        if b=='大货生产中':
            ev.append(dict(kind='in_production',msg=m,po=c['po']));continue
        mm=re.fullmatch(r'ETD (\d+)/(\d+)',b) or re.search(r'ETD around (\d+)/(\d+)',b) or re.fullmatch(r'交期(\d+)月(\d+)号左右',b)
        if mm and not m['mine']:
            ev.append(dict(kind='etd_pi',msg=m,po=c['po'],date=yearless(int(mm.group(1)),int(mm.group(2)),cn)));continue
        mm=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',b)
        if mm:
            ev.append(dict(kind='etd_slip',msg=m,po=mm.group(1),named='po',date=yearless(int(mm.group(2)),int(mm.group(3)),cn)));continue
        mm=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',b)
        if mm:
            ev.append(dict(kind='etd_slip',msg=m,po=mm.group(1),named='po',date=yearless(int(mm.group(2)),int(mm.group(3)),cn)));continue
        mm=re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',b)
        if mm:
            ev.append(dict(kind='etd_slip',msg=m,po=PIBYNUM[mm.group(1)]['po'],named='pi',date=yearless(int(mm.group(2)),int(mm.group(3)),cn)));continue
        mm=re.search(r'(?:container loaded: |Container )([A-Z]{4}\d{7})',b)
        if mm:
            ev.append(dict(kind='container',msg=m,container=mm.group(1)));continue
    return ev
if __name__=='__main__':
    from collections import Counter
    ev=chat_events();print(Counter(e['kind'] for e in ev))
    for e in ev:
        m=e['msg']
        if e['kind']=='etd_pi':
            p=PIS.get(e['po'])
            if not p or p['etd']!=e['date'].isoformat(): print('PI-ETD DIFF',m['url'],m['body'],e['po'],e['date'],p and p['etd'])
        if e['kind']=='etd_slip': print('SLIP',m['url'],e['po'],e['named'],e['date'],PIS.get(e['po'],{}).get('etd'))
        if e['kind']=='deposit_ack': print('ACK',m['url'],e['po'],e['named'],e['amt'])
        if e['kind']=='in_production': print('PROD',m['url'],e['po'])
