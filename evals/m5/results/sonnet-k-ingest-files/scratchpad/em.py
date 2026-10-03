import re,hashlib,json,email.utils,datetime as dt
raw=open('/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-k-mid97be7/ingest/work/exports/email/ops_inbox.mbox','rb').read()
parts=re.split(rb'(?m)^(?=From \S+ \w{3} \w{3} +\d+ )',raw)
parts=[p for p in parts if p.strip()]
out=[]
for p in parts:
    # raw bytes of the message from its From line; strip the trailing blank-line separator
    body=p
    t=p.decode()
    hdr=lambda k: re.search(r'(?m)^%s: (.*)$'%k,t).group(1).strip()
    d=email.utils.parsedate_to_datetime(hdr('Date'))
    out.append(dict(hash=hashlib.sha256(p).hexdigest(),mid=hdr('Message-ID').strip('<>'),subj=hdr('Subject'),date=d.isoformat(),text=t,rawlen=len(p),endsnl=p.endswith(b'\n\n')))
json.dump(out,open('emails.json','w'))
print(len(out), sum(o['endsnl'] for o in out))
