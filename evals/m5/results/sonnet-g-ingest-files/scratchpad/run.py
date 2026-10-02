import sys, pickle
from engine import *
import engine

P = pdf_docs(); C = chat_docs(); E = [parse_email(d) for d in email_docs()]
pi_po = {d['name'][:-4]: d['po'] for d in P if d['kind'] == 'pi'}
# container message -> PO via the next CI file in the same chat naming that container
ci_by_container = {}
byfile = collections.defaultdict(list)
for c in C: byfile[c['file']].append(c)
for fn, msgs in byfile.items():
    for i, c in enumerate(msgs):
        m = re.search(r'[Cc]ontainer(?: loaded:)? (\w{4}\d{7})', c['body'])
        if m and not c['ours']:
            for c2 in msgs[i+1:]:
                m2 = re.match(r'\[文件\] CI-PL_(\S+)_' + m[1] + r'\.pdf', c2['body'])
                if m2:
                    ci_by_container[(fn, m[1], c['issued'])] = pi_po.get(m2[1]); break
allD = P + C + E
rk = {'pi': 0, 'qc': 1, 'ci': 2, 'chat': 3, 'email': 4}
allD.sort(key=lambda d: (d['issued'].astimezone(dt.timezone.utc), rk[d['kind']]))
for d in allD:
    k = d['kind']
    if k == 'pi': do_pi(d)
    elif k == 'qc': do_qc(d)
    elif k == 'ci': do_ci(d)
    elif k == 'email': do_email(d)
    else: do_chat(d, pi_po, ci_by_container)
print('tx', len(TX), dict(CNT))
for k, v in LOG.items():
    print('##', k, len(v))
    for x in v[:40]: print('   ', x)
print(collections.Counter(po_status.values()))
pickle.dump(None, open('/dev/null', 'wb'))
if len(sys.argv) > 1:
    for p, s in sorted(po_status.items()):
        if s != 'received': print(p, s, po_etd.get(p), [(x['booking'], x['hbl'], x['status'], x['prealert'], x['ci']) for x in carrying(p)])
    print('--- shipments')
    for x in shipments:
        print(x['booking'], x['hbl'], x['container'], x['status'], x['delivered'], x['entry'], sorted(x['pos']))
    print('--- etd chat changes')
    for t in TX:
        if t['topic'] in ('chat-etd','chat-container'):
            print(t['doc']['url'], t['conf'], [ (f['e'],f['v']) for f in t['facts'] if f['a'] in ('po/etd','shipment/container_no')])
