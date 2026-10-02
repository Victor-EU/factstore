import re,json,hashlib,glob,os,email
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m4-messages-1ef64f6u/work/exports'
NY=ZoneInfo('America/New_York')
docs=[]
# chats
hdr=re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.+)$')
for f in sorted(glob.glob(X+'/wechat/*.txt')):
    name=os.path.basename(f)
    lines=open(f,encoding='utf-8').read().split('\n')
    msgs=[];cur=None
    for l in lines:
        m=hdr.match(l)
        if m: cur=[l];msgs.append(cur)
        elif cur is not None:
            if l=='' : cur=None if False else cur
            cur.append(l)
    for n,c in enumerate(msgs,1):
        while c and c[-1]=='': c.pop()
        txt='\n'.join(c)
        m=hdr.match(c[0])
        dt=datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
        docs.append(dict(kind='chat',file=name,n=n,url=f'wechat/{name}#{n}',hash=hashlib.sha256(txt.encode()).hexdigest(),
          utc=dt.astimezone(timezone.utc).isoformat(),sender=m.group(2),text='\n'.join(c[1:])))
# emails
raw=open(X+'/email/ops_inbox.mbox','rb').read()
parts=re.split(rb'(?m)^(?=From )',raw)
parts=[p for p in parts if p]
for p in parts:
    b=p
    if b.endswith(b'\n\n'): b=b[:-1]
    msg=email.message_from_bytes(b.split(b'\n',1)[1])
    mid=msg['Message-ID'].strip('<>')
    dt=email.utils.parsedate_to_datetime(msg['Date'])
    docs.append(dict(kind='email',url='mid:'+mid,hash=hashlib.sha256(b).hexdigest(),utc=dt.astimezone(timezone.utc).isoformat(),
      subject=msg['Subject'],sender=msg['From'],text=msg.get_payload(decode=True).decode(),mid=mid,date=msg['Date']))
json.dump(docs,open(os.path.dirname(__file__)+'/docs.json','w'),ensure_ascii=False,indent=0)
print(len(docs),sum(d['kind']=='chat' for d in docs),sum(d['kind']=='email' for d in docs))
