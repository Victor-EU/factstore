import re,glob,os,hashlib
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-l-_p6upixp/ingest/work/exports/wechat/'
def load(f):
    lines=open(W+f,encoding='utf-8').read().split('\n')
    msgs=[];cur=None
    for l in lines:
        if re.match(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ',l):
            cur=[l];msgs.append(cur)
        elif cur is not None:
            if l.strip()=='' : cur=None  # blank ends msg
            else: cur.append(l)
    out=[]
    for i,m in enumerate(msgs,1):
        ts,sender=m[0][:19],m[0][20:]
        out.append(dict(file=f,n=i,ts=ts,sender=sender,text='\n'.join(m[1:]),hash=hashlib.sha256('\n'.join(m).encode()).hexdigest(),url=f'wechat/{f}#{i}'))
    return out
