import mailbox,re,hashlib,os
from email.utils import parsedate_to_datetime
EXP='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-h-ev4813q6/ingest/work/exports'
MON={m:i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}
def dt(s):
    m=re.match(r'(\d\d) (\w{3}) (\d{4})',s); import datetime
    return datetime.date(int(m.group(3)),MON[m.group(2)],int(m.group(1)))
def parse_all():
    raw=open(EXP+'/email/ops_inbox.mbox','rb').read()
    # split on "From " lines at line start preceded by blank
    import re as _re
    parts=_re.split(rb'(?m)^(?=From (?!:))',raw)
    parts=[p for p in parts if p.strip()]
    out=[]
    for p in parts:
        import email
        msg=email.message_from_bytes(p.split(b'\n',1)[1])
        body=msg.get_payload(decode=True).decode()
        d=dict(raw_hash=hashlib.sha256(p).hexdigest(),subject=msg['Subject'],date=parsedate_to_datetime(msg['Date']),
               mid=msg['Message-ID'].strip('<>'),body=body,frm=msg['From'])
        out.append(d)
    return out
if __name__=='__main__':
    E=parse_all(); print(len(E)); print(E[0]['raw_hash'],E[0]['mid'])
