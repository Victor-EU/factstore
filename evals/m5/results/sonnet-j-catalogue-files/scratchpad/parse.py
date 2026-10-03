import re,glob,os,collections
M={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
rows=collections.defaultdict(set)
for f in sorted(glob.glob('txt/CI-PL_*.txt')):
    pre=os.path.basename(f)[6:8]
    L=open(f).read().split('\n')
    i=0
    while i<len(L):
        m=re.match(r'^((?:[A-Z]{2}-?)?\d+) (.+)$',L[i])
        if m and i+2<len(L):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',L[i+2])
            if h: rows[(M[pre],m.group(1))].add((m.group(2).lower(),h.group(1),os.path.basename(f)))
        i+=1
for k,v in sorted(rows.items()):
    print(k, {x[0] for x in v}, {x[1] for x in v})
print(len(rows))
