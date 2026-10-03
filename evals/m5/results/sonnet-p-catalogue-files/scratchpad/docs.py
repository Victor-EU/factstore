import glob,re,os,collections as C,json
PFX={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
def items():
    out=C.defaultdict(lambda:{'desc':set(),'hs':set(),'docs':set()})
    for f in sorted(glob.glob(S+'/txt/*.txt')):
        b=os.path.basename(f)[:-4]
        if b.startswith('LCI'): continue
        pre=b.replace('CI-PL_','')[:2]
        sup=PFX[pre]
        L=open(f).read().split('\n')
        for i,l in enumerate(L):
            m=re.match(r'^(\S+) ([a-z][a-z0-9 ,.\-]+)$',l)
            if m and i+1<len(L) and re.search(r'[一-鿿]',L[i+1]) and not l.startswith('Item'):
                k=sup+':'+m.group(1)
                out[k]['desc'].add(m.group(2).strip()); out[k]['docs'].add(b)
                h=re.search(r'\d{4}\.\d{2}\.\d{4}',L[i+2]) if i+2<len(L) else None
                if h: out[k]['hs'].add(h.group(0))
    return out
S='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-p-v76cz30z-catalogue-work/3729562d-84d8-4aa2-a3cf-5ed2509853ea/scratchpad'
if __name__=='__main__':
    it=items()
    for k,v in sorted(it.items()): print(k,v['desc'],v['hs'],len(v['docs']))
    print(len(it))
