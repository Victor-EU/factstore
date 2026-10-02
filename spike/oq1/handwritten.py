"""Hand-written reference queries for the ten questions, one set per candidate. They prove each
question can be asked in each language, and that the engines answer correctly."""

from questions import JULY_1_TX

SQL = {
    1: ("""
select b.v, st.v, eta.v, sum(q.v)
from "sku/code" k
join "po_line/sku" pl on pl.v = k.e
join "shipment_line/po_line" sl on sl.v = pl.e
join "shipment_line/quantity" q on q.e = sl.e
join "core/part_of" p on p.e = sl.e
join "shipment/status" st on st.e = p.v
join "shipment/booking_no" b on b.e = p.v
join "shipment/eta" eta on eta.e = p.v
where k.v = 'AH-KTL-0001-BLK' and st.v in ('departed', 'arrived')
group by 1, 2, 3""", None),
    2: ("""
with first as (
  select distinct on (e) e, v from history."po/etd" where op = 'assert' order by e, tx)
select n.v, first.v, etd.v
from "supplier/code" s
join "po/supplier" ps on ps.v = s.e
join "po/number" n on n.e = ps.e
join "po/etd" etd on etd.e = ps.e
join first on first.e = ps.e
where s.v = 'NBBW' and etd.v > first.v""", None),
    3: ("""
select b.v, st.v, eta.v
from "shipment/status" st
join "shipment/booking_no" b using (e)
join "shipment/eta" eta using (e)
where st.v in ('departed', 'arrived')""", JULY_1_TX),
    4: ("""
select count(*), sum(ev.v), sum(d.v), sum(f.v)
from "customs/filed_on" filed
join "customs/entered_value" ev using (e)
join "customs/duty" d using (e)
join "customs/fees" f using (e)
where filed.v between '2026-04-01' and '2026-06-30'""", None),
    5: ("""
select s.v, r.v, count(*)
from "qc/inspected_on" d
join "qc/result" r using (e)
join "qc/po" qp using (e)
join "po/supplier" ps on ps.e = qp.v
join "supplier/code" s on s.e = ps.v
where d.v >= '2026-01-01'
group by 1, 2""", None),
    6: ("""
select k.v, sv.v, fn.v, ss.v, tpl.v, fac.v, sup.v
from "amazon/asin" asin
join "sku/code" k using (e)
join "shopify/variant_id" sv using (e)
join "amazon/fnsku" fn using (e)
join "amazon/seller_sku" ss using (e)
join "tpl/item_code" tpl using (e)
join "factory/item_code" fac using (e)
join "sku/supplier" ks using (e)
join "supplier/code" sup on sup.e = ks.v
where asin.v = 'B0BVUGZ3AT'""", None),
    7: ("""
select s.v, cur.v, sum(q.v * p.v)
from "po/status" st
join "po/supplier" ps using (e)
join "supplier/code" s on s.e = ps.v
join "core/currency" cur on cur.e = st.e
join "core/part_of" line on line.v = st.e
join "po_line/quantity" q on q.e = line.e
join "po_line/unit_price" p on p.e = line.e
where st.v not in ('shipped', 'received')
group by 1, 2""", None),
    8: ("""
with recursive up(account, root) as (
  select e, e from "shopify/customer_id"
  union
  select up.account, s.v from up join "core/same_as" s on s.e = up.root
),
roots as (
  select account, root from up where root not in (select e from "core/same_as")
),
person as (
  select r2.account from "shopify/customer_id" c
  join roots r1 on r1.account = c.e
  join roots r2 on r2.root = r1.root
  where c.v = '8995877069469'
)
select count(distinct person.account), count(o.e)
from person left join "order/customer" o on o.v = person.account""", None),
    9: ("""
select name.v, etd.tx, at.v
from "po/number" n
join "po/etd" etd using (e)
join "fs/actor" actor on actor.e = etd.tx
join "fs/name" name on name.e = actor.v
join "fs/at" at on at.e = etd.tx
where n.v = 'PO-2026-0023'""", None),
    10: ("""
select lc.v, lk.v, q.v
from "sku/code" k
join "inventory/sku" i on i.v = k.e
join "inventory/location" il on il.e = i.e
join "inventory/quantity" q on q.e = i.e
join "location/code" lc on lc.e = il.v
join "location/kind" lk on lk.e = il.v
where k.v = 'AH-TWL-0007-NAT' and lk.v in ('factory', 'in_transit')""", None),
}

DATALOG = {
    1: ("""
[:find ?booking ?status ?eta (sum ?qty)
 :with ?sl
 :where [?sku :sku/code "AH-KTL-0001-BLK"]
        [?pl :po_line/sku ?sku]
        [?sl :shipment_line/po_line ?pl]
        [?sl :shipment_line/quantity ?qty]
        [?sl :core/part_of ?s]
        [?s :shipment/status ?status]
        [(contains? #{"departed" "arrived"} ?status)]
        [?s :shipment/booking_no ?booking]
        [?s :shipment/eta ?eta]]""", None),
    2: ("""
[:find ?n ?first ?current
 :where [?sup :supplier/code "NBBW"]
        [?po :po/supplier ?sup]
        [?po :po/number ?n]
        [?po :po/etd ?current]
        [?po :po/etd ?first ?tx true]
        (not-join [?po ?tx]
          [?po :po/etd _ ?earlier true]
          [(< ?earlier ?tx)])
        [(> ?current ?first)]]""", None),
    3: ("""
[:find ?booking ?status ?eta
 :where [?s :shipment/status ?status]
        [(contains? #{"departed" "arrived"} ?status)]
        [?s :shipment/booking_no ?booking]
        [?s :shipment/eta ?eta]]""", JULY_1_TX),
    4: ("""
[:find (count ?e) (sum ?value) (sum ?duty) (sum ?fees)
 :with ?e
 :where [?e :customs/filed_on ?d]
        [(>= ?d "2026-04-01")]
        [(<= ?d "2026-06-30")]
        [?e :customs/entered_value ?value]
        [?e :customs/duty ?duty]
        [?e :customs/fees ?fees]]""", None),
    5: ("""
[:find ?code ?result (count ?qc)
 :where [?qc :qc/inspected_on ?d]
        [(>= ?d "2026-01-01")]
        [?qc :qc/result ?result]
        [?qc :qc/po ?po]
        [?po :po/supplier ?s]
        [?s :supplier/code ?code]]""", None),
    6: ("""
[:find ?code ?variant ?fnsku ?seller ?tpl ?factory ?supplier
 :where [?k :amazon/asin "B0BVUGZ3AT"]
        [?k :sku/code ?code]
        [?k :shopify/variant_id ?variant]
        [?k :amazon/fnsku ?fnsku]
        [?k :amazon/seller_sku ?seller]
        [?k :tpl/item_code ?tpl]
        [?k :factory/item_code ?factory]
        [?k :sku/supplier ?s]
        [?s :supplier/code ?supplier]]""", None),
    7: ("""
[:find ?code ?currency (sum ?value)
 :with ?line
 :where [?po :po/status ?status]
        [(not= ?status "shipped")]
        [(not= ?status "received")]
        [?po :po/supplier ?s]
        [?s :supplier/code ?code]
        [?po :core/currency ?currency]
        [?line :core/part_of ?po]
        [?line :po_line/quantity ?q]
        [?line :po_line/unit_price ?p]
        [(* ?q ?p) ?value]]""", None),
    8: ("""
[:find (count-distinct ?account) (count-distinct ?order)
 :in $ %
 :where [?c :shopify/customer_id "8995877069469"]
        (root ?c ?r)
        (root ?account ?r)
        [?order :order/customer ?account]]
[[(root ?a ?r) [?a :shopify/customer_id _] (not [?a :core/same_as _]) [(identity ?a) ?r]]
 [(root ?a ?r) [?a :core/same_as ?b] (root ?b ?r)]]""", None),
    9: ("""
[:find ?name ?tx ?at
 :where [?po :po/number "PO-2026-0023"]
        [?po :po/etd _ ?tx]
        [?tx :fs/actor ?actor]
        [?actor :fs/name ?name]
        [?tx :fs/at ?at]]""", None),
    10: ("""
[:find ?loc ?kind ?q
 :where [?k :sku/code "AH-TWL-0007-NAT"]
        [?p :inventory/sku ?k]
        [?p :inventory/location ?l]
        [?l :location/kind ?kind]
        [(contains? #{"factory" "in_transit"} ?kind)]
        [?l :location/code ?loc]
        [?p :inventory/quantity ?q]]""", None),
}

JSON = {
    1: ("""
{"where": {"?s": {"shipment/status": {"value": "?status", "in": ["departed", "arrived"]},
                  "shipment/booking_no": "?booking",
                  "shipment/eta": "?eta",
                  "^core/part_of": {"shipment_line/quantity": "?qty",
                                    "shipment_line/po_line": {"po_line/sku": {"sku/code": "AH-KTL-0001-BLK"}}}}},
 "select": ["?booking", "?status", "?eta", {"sum": "?qty"}]}""", None),
    2: ("""
{"where": [{"id": "?po", "po/supplier": {"supplier/code": "NBBW"}, "po/number": "?n", "po/etd": "?current"},
           {"id": "?po", "po/etd": {"value": "?first", "tx": "?tx", "op": "assert", "log": true},
            "not": {"po/etd": {"tx": {"lt": "?tx"}, "op": "assert", "log": true}}}],
 "filter": [[">", "?current", "?first"]],
 "select": ["?n", "?first", "?current"]}""", None),
    3: ("""
{"where": {"?s": {"shipment/status": {"value": "?status", "in": ["departed", "arrived"]},
                  "shipment/booking_no": "?booking", "shipment/eta": "?eta"}},
 "select": ["?booking", "?status", "?eta"]}""", JULY_1_TX),
    4: ("""
{"where": {"?e": {"customs/filed_on": {"gte": "2026-04-01", "lte": "2026-06-30"},
                  "customs/entered_value": "?value", "customs/duty": "?duty", "customs/fees": "?fees"}},
 "select": [{"count": "?e"}, {"sum": "?value"}, {"sum": "?duty"}, {"sum": "?fees"}]}""", None),
    5: ("""
{"where": {"?qc": {"qc/inspected_on": {"gte": "2026-01-01"}, "qc/result": "?result",
                   "qc/po": {"po/supplier": {"supplier/code": "?code"}}}},
 "select": ["?code", "?result", {"count": "?qc"}]}""", None),
    6: ("""
{"where": {"?k": {"amazon/asin": "B0BVUGZ3AT", "sku/code": "?code", "shopify/variant_id": "?variant",
                  "amazon/fnsku": "?fnsku", "amazon/seller_sku": "?seller", "tpl/item_code": "?tpl",
                  "factory/item_code": "?factory", "sku/supplier": {"supplier/code": "?supplier"}}},
 "select": ["?code", "?variant", "?fnsku", "?seller", "?tpl", "?factory", "?supplier"]}""", None),
    7: ("""
{"where": {"?po": {"po/status": {"not_in": ["shipped", "received"]},
                   "po/supplier": {"supplier/code": "?code"}, "core/currency": "?currency"},
           "?line": {"core/part_of": "?po", "po_line/quantity": "?q", "po_line/unit_price": "?p"}},
 "let": {"?value": ["*", "?q", "?p"]},
 "select": ["?code", "?currency", {"sum": "?value"}]}""", None),
    8: ("""
{"where": {"?c": {"shopify/customer_id": "8995877069469", "core/same_as*": "?root"},
           "?root": {"core/same_as": {"missing": true}},
           "?account": {"core/same_as*": "?root", "shopify/customer_id": "?id"},
           "?order": {"order/customer": "?account"}},
 "select": [{"count_distinct": "?account"}, {"count_distinct": "?order"}]}""", None),
    9: ("""
{"where": {"?po": {"po/number": "PO-2026-0023", "po/etd": {"tx": "?tx"}},
           "?tx": {"fs/actor": {"fs/name": "?name"}, "fs/at": "?at"}},
 "select": ["?name", "?tx", "?at"]}""", None),
    10: ("""
{"where": {"?p": {"inventory/sku": {"sku/code": "AH-TWL-0007-NAT"}, "inventory/quantity": "?q",
                  "inventory/location": {"location/kind": {"value": "?kind", "in": ["factory", "in_transit"]},
                                         "location/code": "?loc"}}},
 "select": ["?loc", "?kind", "?q"]}""", None),
}

ALL = {"sql": SQL, "datalog": DATALOG, "json": JSON}
