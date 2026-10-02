import factstore
def q(s): return factstore.query(s).rows
def load():
    D={}
    D['ship']={r[1]:dict(e=r[0],hbl=r[1],vessel=r[2],cont=r[3],o=r[4],d=r[5]) for r in q('''select h.e,h.v,v.v,c.v,o.v,d.v from "shipment/hbl" h left join "shipment/vessel" v using(e) left join "shipment/container_no" c using(e) left join "shipment/origin" o using(e) left join "shipment/destination" d using(e)''')}
    # lines: shipment hbl, po number, po line key, item code, qty, cartons
    D['lines']=q('''select sh.v hbl, pl.v plkey, po.v po, fi.v item, sq.v qty, sc.v ctn, k.v lkey
      from "shipment_line/key" k join "core/part_of" p using(e) join "shipment/hbl" sh on sh.e=p.v
      join "shipment_line/po_line" l on l.e=k.e join "po_line/key" pl on pl.e=l.v
      join "core/part_of" pp on pp.e=l.v join "po/number" po on po.e=pp.v
      join "po_line/sku" ps on ps.e=l.v join "factory/item_code" fi on fi.e=ps.v
      join "shipment_line/quantity" sq on sq.e=k.e join "shipment_line/cartons" sc on sc.e=k.e''')
    D['po']={r[0]:dict(etd=r[1],pi=r[2],sup=r[3]) for r in q('''select p.v,e.v,pi.v,sc.v from "po/number" p join "po/etd" e using(e) join "po/pi_number" pi using(e) join "po/supplier" s using(e) join "supplier/code" sc on sc.e=s.v''')}
    return D
