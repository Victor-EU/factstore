import re,glob,hashlib,os,datetime as dt
from zoneinfo import ZoneInfo
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-d-qzl8j1ow/ingest/work/exports/wechat/'
NY=ZoneInfo('America/New_York'); CN=ZoneInfo('Asia/Shanghai')
CODE={'XMYD':'XMYD','DGRF':'DGRF','NBBW':'NBBW','NBQS':'NBQS','FSMJ':'FSMJ','HZTY':'HZTY','YWLX':'YWLX','SZHT':'SZHT'}
def load():
    out=[]
    for f in sorted(glob.glob(W+'*.txt')):
        fn=os.path.basename(f); sup=fn.split('_')[0]
        blocks=open(f,encoding='utf-8',newline='').read().split('\n\n')
        n=0
        for b in blocks[1:]:
            b=b.strip('\n')
            if not b: continue
            n+=1
            ls=b.split('\n'); m=re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$',ls[0])
            ts=dt.datetime.strptime(m[1],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            out.append(dict(file=fn,sup=sup,n=n,ts=ts,sender=m[2],text='\n'.join(ls[1:]),
              hash=hashlib.sha256(b.encode('utf-8')).hexdigest(),url=f'wechat/{fn}#{n}',ours=m[2].endswith('Acme Hearth')))
    return out
def next_date(m,d,after):
    """next occurrence of month/day on or after `after` (a date)."""
    for y in (after.year,after.year+1):
        try: c=dt.date(y,m,d)
        except ValueError: continue
        if c>=after: return c
if __name__=='__main__':
    ms=load(); print(len(ms))
    import collections
    c=collections.Counter()
    for m in ms:
        k=re.sub(r'\d+','9',m['text'])[:60]; c[k]+=1
    for k,v in c.most_common(): print(v,k)
