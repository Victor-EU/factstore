import re,hashlib,email
raw=open('/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-a-jtof532b/ingest/work/exports/email/ops_inbox.mbox','rb').read()
parts=re.split(rb'(?m)^(?=From \S+ \w{3} \w{3} \d\d \d\d:\d\d:\d\d \d{4}\r?$)',raw)
msgs=[]
for p in parts:
    if not p.strip(): continue
    m=email.message_from_bytes(p.split(b'\n',1)[1])
    msgs.append(dict(raw=p,hash=hashlib.sha256(p).hexdigest(),mid=m['Message-ID'].strip('<>'),subj=m['Subject'],date=m['Date'],frm=m['From'],body=m.get_payload(decode=True).decode()))
