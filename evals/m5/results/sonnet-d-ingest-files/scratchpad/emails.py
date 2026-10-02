import mailbox,re,hashlib,email.utils,datetime as dt
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-d-qzl8j1ow/ingest/work/exports/'
def raw_messages():
    data=open(W+'email/ops_inbox.mbox','rb').read()
    parts=re.split(rb'(?m)^(?=From )',data)
    return [p for p in parts if p.strip()]
def load():
    out=[]
    for raw in raw_messages():
        # strip trailing blank line separator? keep as stored
        msg=mailbox.mboxMessage(raw.split(b'\n',1)[1]) if False else None
        import email
        m=email.message_from_bytes(raw.split(b'\n',1)[1])
        body=m.get_payload()
        out.append(dict(raw=raw,hash=hashlib.sha256(raw).hexdigest(),
            mid=m['Message-ID'].strip('<>'),subj=m['Subject'],
            date=email.utils.parsedate_to_datetime(m['Date']),frm=m['From'],body=body))
    return out
if __name__=='__main__':
    e=load(); print(len(e)); print(repr(e[0]['raw'][:80])); print(repr(e[0]['raw'][-60:])); print(repr(e[1]['raw'][:30]))
