from parse import *
from zoneinfo import ZoneInfo
NY=ZoneInfo('America/New_York'); CN=ZoneInfo('Asia/Shanghai')
SUP={'DGRF':'DGRF','FSMJ':'FSMJ','HZTY':'HZTY','NBBW':'NBBW','NBQS':'NBQS','SZHT':'SZHT','XMYD':'XMYD','YWLX':'YWLX'}
pis={d['po']:d for d in docs if d['kind']=='PI'}
pi_by_no={d['pi'].replace('-','').upper():d for d in docs if d['kind']=='PI'}
def nextdate(m,d,after):
    y=after.year
    for yy in (y,y+1):
        try:
            c=datetime(yy,m,d).date()
        except ValueError: continue
        if c>=after.date(): return c
cm=[]
for c in chats:
    c['sup']=c['file'].split('_')[0]
    c['dt']=datetime.strptime(c['ts'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
    c['cn']=c['dt'].astimezone(CN)
    b=c['body']; c['mine']=c['sender'].startswith('Maya')
    k=None
    if c['mine']:
        m=re.search(r'(PO-\d{4}-\d{4})',b)
        if m and not b.startswith('[文件]') and (re.search(r'new PO|here\'s PO|PO PO-',b)):
            k='po_sent'; c['po']=m.group(1)
        elif m and 'deposit' in b: k='deposit'; c['po']=m.group(1)
    else:
        m=re.search(r'ETD for (PO-\d{4}-\d{4}) will be (\d+)/(\d+)',b)
        if m: k='etd_named'; c['po']=m.group(1); c['md']=(int(m.group(2)),int(m.group(3)))
        m2=re.search(r'(PO-\d{4}-\d{4})交期要推迟到(\d+)月(\d+)号',b)
        if m2: k='etd_named'; c['po']=m2.group(1); c['md']=(int(m2.group(2)),int(m2.group(3)))
        m3=re.search(r'Hi, (\S+) 大货要晚一点.*预计(\d+)/(\d+)出货',b)
        if m3:
            k='etd_named'; c['pino']=m3.group(1); c['po']=pi_by_no[m3.group(1).replace('-','').upper()]['po']; c['md']=(int(m3.group(2)),int(m3.group(3)))
        if not k:
            m=re.fullmatch(r'ETD (\d+)/(\d+)',b) or re.fullmatch(r'交期(\d+)月(\d+)号左右(?:，ETD around (\d+)/(\d+))?',b) or re.fullmatch(r'交期(\d+)月(\d+)号左右，ETD around (\d+)/(\d+)',b)
            if m: k='etd_unnamed'; c['md']=(int(m.group(1)),int(m.group(2)))
            elif re.fullmatch(r'ETD around (\d+)/(\d+)',b): pass
        if not k:
            m=re.search(r'Container (\w{4}\d{7}) loaded today',b) or re.search(r'container loaded: (\w{4}\d{7}) seal',b)
            if m: k='container'; c['container']=m.group(1)
        if not k and ('定金收到了，马上安排生产' in b): k='ack_prod'
        if not k and b=='收到，谢谢': k='ack_recv'
        if not k and b=='大货生产中': k='in_prod'
    c['k']=k
    if 'md' in c: c['etd']=nextdate(*c['md'],c['cn'])
if __name__=='__main__':
    from collections import Counter
    print(Counter(c['k'] for c in chats))
    # unnamed ETD resolution preview
    for c in chats:
        if c['k']=='etd_unnamed':
            cands=[d for d in pis.values() if d['name_cn'] and False]
            print(c['url'],c['ts'],c['body'],c['etd'])
