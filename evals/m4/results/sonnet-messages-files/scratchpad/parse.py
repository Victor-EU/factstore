import mailbox, re, hashlib, glob, os, datetime as dt, json
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m4-messages-vjmnybn1/work/exports'
NY=ZoneInfo('America/New_York'); SH=ZoneInfo('Asia/Shanghai')

def emails():
    raw=open(f'{EX}/email/ops_inbox.mbox','rb').read()
    parts=re.split(rb'(?m)^(?=From )',raw)
    parts=[p for p in parts if p.strip()]
    out=[]
    for p in parts:
        # raw bytes from the From line to the end of the message; strip the separator blank line
        body=p
        import email
        m=email.message_from_bytes(p.split(b'\n',1)[1])
        mid=m['Message-ID'].strip('<>')
        txt=m.get_payload(decode=True).decode('utf8')
        out.append(dict(kind='email',raw=p,hash=hashlib.sha256(p[:-1] if p.endswith(b'\n\n') else p).hexdigest(),url='mid:'+mid,
            subject=m['Subject'],date=parsedate_to_datetime(m['Date']),text=txt,sender=m['From']))
    return out

HDR=re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$')
def chats():
    out=[]
    for f in sorted(glob.glob(f'{EX}/wechat/*.txt')):
        name=os.path.basename(f)
        lines=open(f,encoding='utf8').read().split('\n')
        msgs=[];cur=None
        for ln in lines:
            m=HDR.match(ln)
            if m: cur=[ln];msgs.append(cur)
            elif cur is not None:
                if ln=='' : cur=None
                else: cur.append(ln)
        for n,c in enumerate(msgs,1):
            m=HDR.match(c[0]); text='\n'.join(c)
            ts=dt.datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            out.append(dict(kind='chat',file=name,n=n,hash=hashlib.sha256(text.encode()).hexdigest(),
                url=f'wechat/{name}#{n}',date=ts,sender=m.group(2),text='\n'.join(c[1:]),full=text))
    return out
