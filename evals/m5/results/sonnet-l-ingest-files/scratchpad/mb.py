import re,hashlib,email.utils
raw=open('/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-l-_p6upixp/ingest/work/exports/email/ops_inbox.mbox','rb').read()
parts=re.split(rb'(?m)^(?=From \S+ \w{3} \w{3} +\d+ )',raw)
msgs=[]
for p in parts:
    if not p.strip(): continue
    t=p.decode('utf-8')
    hdr,_,body=t.partition('\n\n')
    h=dict(re.findall(r'(?m)^([A-Za-z-]+): (.*)$',hdr))
    p=p.rstrip(b'\n')+b'\n'
    msgs.append(dict(raw=p,hash=hashlib.sha256(p).hexdigest(),subj=h['Subject'],date=h['Date'],mid=h['Message-ID'].strip('<>'),body=body,dt=email.utils.parsedate_to_datetime(h['Date'])))
