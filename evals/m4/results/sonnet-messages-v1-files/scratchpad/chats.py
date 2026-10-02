import json,re,store
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
D=store.load()
pi2po={v['pi']:k for k,v in D['po'].items()}
docs=[d for d in json.load(open('docs.json')) if d['kind']=='chat']
CN=ZoneInfo('Asia/Shanghai')
def next_date(mo,dy,utc):
    t=datetime.fromisoformat(utc).astimezone(CN).date()
    for y in (t.year,t.year+1):
        c=date(y,mo,dy)
        if c>=t: return c
shipbycont={s['cont']:s for s in D['ship'].values() if s['cont']}
out=[];last_pi={}
for d in docs:
    sup=d['file'].split('_')[0]; t=d['text'].strip()
    m=re.search(r'\[文件\] (\S+)\.pdf',t)
    if m:
        nm=m.group(1)
        if nm in pi2po: last_pi[sup]=pi2po[nm]
        continue
    r=None
    date_m=re.search(r'(?:ETD(?: around| for [\w-]+ will be)?|交期(?:要推迟到)?)\s*(\d{1,2})/(\d{1,2})',t) or re.search(r'(\d{1,2})月(\d{1,2})号',t) or re.search(r'预计(\d{1,2})/(\d{1,2})出货',t)
    if re.search(r'ETD|交期|出货',t) and date_m and '放假' not in t and '休息' not in t:
        g=date_m.groups()
        if '月' in date_m.group(0): mo,dy=int(g[0]),int(g[1])
        else: mo,dy=int(g[0]),int(g[1])
        po=None;how=None
        m1=re.search(r'PO-\d{4}-\d{4}',t)
        if m1: po,how=m1.group(0),'po'
        else:
            for pi,p in pi2po.items():
                if pi in t: po,how=p,'pi'
        if not po and sup in last_pi: po,how=last_pi[sup],'prev_pi'
        kind='slip' if re.search(r'推迟|晚一点|will be|大货要晚',t) else 'pi_etd'
        out.append(dict(doc=d,kind=kind,sup=sup,po=po,how=how,etd=str(next_date(mo,dy,d['utc'])),text=t))
        continue
    m=re.search(r'\b([A-Z]{4}\d{7})\b',t)
    if m and re.search(r'loaded|装柜',t):
        out.append(dict(doc=d,kind='container',sup=sup,cont=m.group(1),text=t))
json.dump([{k:v for k,v in e.items()} for e in out],open('chat_events.json','w'),default=str,ensure_ascii=False,indent=0)
if __name__=='__main__':
    import collections
    print(collections.Counter(e['kind'] for e in out))
    for e in out:
        d=e['doc']
        if e['kind']=='container':
            s=shipbycont.get(e['cont']);print('C',d['file'][:4],d['utc'][:10],e['cont'],s and s['hbl'])
        else:
            cur=D['po'].get(e['po'],{}).get('etd')
            print(e['kind'],d['file'][:4],d['utc'][:10],e['po'],e['how'],e['etd'],'store',cur,'' if str(cur)==e['etd'] else '<<<DIFF','|',e['text'][:60].replace('\n',' '))
