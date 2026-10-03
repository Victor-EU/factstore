import re,glob,os,hashlib
from zoneinfo import ZoneInfo
from datetime import datetime
NY=ZoneInfo('America/New_York')
H=re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$')
def parse(path):
    lines=open(path,encoding='utf-8').read().split('\n')
    msgs=[];cur=None
    for ln in lines:
        m=H.match(ln)
        if m:
            cur={'ts':m.group(1),'who':m.group(2),'lines':[ln],'text':[]};msgs.append(cur)
        elif cur is not None:
            if ln=='' : cur=None
            else: cur['lines'].append(ln);cur['text'].append(ln)
    out=[]
    for i,m in enumerate(msgs,1):
        raw='\n'.join(m['lines'])
        dt=datetime.strptime(m['ts'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
        out.append(dict(n=i,file=os.path.basename(path),dt=dt,who=m['who'],text='\n'.join(m['text']),hash=hashlib.sha256(raw.encode()).hexdigest(),url=f"wechat/{os.path.basename(path)}#{i}",us=m['who'].startswith('Maya')))
    return out
