from build import *
# 3. ETD txs
for t in W.txs:
    if t['label'].startswith('ETD'): print(t['doc']['issued'].strftime('%Y-%m-%d'),t['label'])
# 5. PI-time chat ETD vs PI
for d in chats:
    if d['ours']: continue
    t=d['text'].strip()
    m=re.match(r'^(?:交期(\d+)月(\d+)号左右(?:，ETD around \d+/\d+)?|ETD (?:around )?(\d+)/(\d+))$',t)
    if m:
        mo,dd=[int(x) for x in m.groups() if x][:2]
        # nearest PI of supplier within 3 days before
        c=[p for p in pis if p['sup_code']==d['sup'] and abs((p['issued']-d['issued']).days)<=3]
        ok=[p for p in c if p['etd'].month==mo and p['etd'].day==dd]
        if not ok: print('PI-time ETD mismatch',d['url'],t,[ (p['pi_no'],p['etd']) for p in c])
print('--- PO qty vs shipped')
for po,p in sorted(W.po.items()):
    carriers=[s for s in W.ship if po in s['pos'] or any(v[0]==po for v in s['lines'].values())]
    tot=collections.defaultdict(D)
    for s in carriers:
        for k,(pp,line,q) in s['lines'].items():
            if pp==po: tot[line]+=q
    diff=[(l,q,tot[l]) for l,q in p['line_qty'].items() if tot[l]!=q]
    print(po,p['status'],len(carriers),'etd',p['etd'],'DIFF' if diff else '', diff[:3] if diff else '')
