import re,glob,json,collections as C,os
rows=C.defaultdict(set)  # (prefix, item) -> {(desc,hs)}
PRE={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
for f in sorted(glob.glob('txt/CI-PL_*.txt')):
    t=open(f).read().split('\n')
    base=os.path.basename(f)[6:]
    pre=re.match(r'[A-Z]+',base).group()
    for i,l in enumerate(t):
        m=re.match(r'^([A-Z]{2}-?\d{3,5}|\d{3}) (.+)$',l)
        if m and i+2<len(t):
            hs=re.search(r'(\d{4}\.\d{2}\.\d{4})',t[i+2]) or re.search(r'(\d{4}\.\d{2}\.\d{4})',t[i+1])
            if hs: rows[(pre,m.group(1))].add((m.group(2).strip(),hs.group(1)))
for k,v in sorted(rows.items()): print(k,v)
print(len(rows))
