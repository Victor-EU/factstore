import pytest

import reference
from conftest import attr
from factstore import RegistrationRefused


def test_registration_is_a_transaction_of_schema_facts(store, writer):
    result = store.register_attribute(attr("supplier/payment_terms", "string",
                                           doc="Agreed payment terms with a supplier, e.g. 30% deposit."))
    e = reference.attr_id(store.conn, "supplier/payment_terms")
    assert reference.value(store.conn, e, "fs/type") == {"string"}
    assert reference.value(store.conn, e, "fs/cardinality") == {"one"}
    assert reference.value(store.conn, result.tx, "fs/actor") == {writer.actor}


def test_registering_the_same_definition_again_changes_nothing(store):
    spec = attr("supplier/currency", "string", doc="Currency a supplier invoices in, as an ISO 4217 code.")
    store.register_attribute(spec)
    again = store.register_attribute(spec)
    assert again.tx is None and again.existing == ["supplier/currency"]


def test_a_different_definition_under_the_same_name_is_refused(store):
    store.register_attribute(attr("supplier/currency", "string", doc="Currency a supplier invoices in."))
    with pytest.raises(RegistrationRefused, match="already registered as string"):
        store.register_attribute(attr("supplier/currency", "ref", doc="Currency a supplier invoices in."))


def test_a_batch_registers_all_or_nothing(store):
    with pytest.raises(RegistrationRefused):
        store.register_attribute([attr("po/number", "string", doc="Purchase order number as printed."),
                                  attr("po/total", "float", doc="Purchase order total.")])
    assert store.search_attributes("po/number") == []


def test_the_fs_namespace_is_reserved(store):
    with pytest.raises(RegistrationRefused, match="reserved for the kernel"):
        store.register_attribute(attr("fs/colour", "string"))


def test_distinct_from_must_name_real_attributes(store):
    with pytest.raises(RegistrationRefused, match="distinct_from names po/nothing"):
        store.register_attribute(attr("po/number", "string", doc="Purchase order number.",
                                      distinct_from=["po/nothing"]))


def test_near_matches_inside_one_batch_need_distinct_from(store):
    window = [attr("core/valid_from", "date", doc="First date on which this holds."),
              attr("core/valid_to", "date", doc="Last date on which this holds.")]
    with pytest.raises(RegistrationRefused) as refused:
        store.register_attribute(window)
    assert "core/valid_to" in refused.value.near_matches

    window[1]["distinct_from"] = ["core/valid_from"]
    assert store.register_attribute(window).registered == ["core/valid_from", "core/valid_to"]


@pytest.mark.parametrize("existing, new, near", [
    (("customer/email", "Email address of a customer."), ("contact/email", "Email address of a contact person."), True),
    (("customer/email", "Email address of a customer."), ("customer/email_address", "Where we email the customer."), True),
    (("customer/email", "Email address of a customer."), ("customer/name", "Full name of a customer."), False),
    (("customer/name", "Full name of a customer."), ("supplier/name", "Legal name of a supplier company."), False),
    (("shipment/status", "Where a shipment is: booked, at sea, at port, delivered."),
     ("po/status", "Where a purchase order is: draft, sent, confirmed, shipped, closed."), False),
])
def test_near_match_calibration(store, existing, new, near):
    store.register_attribute(attr(existing[0], "string", doc=existing[1]))
    if near:
        with pytest.raises(RegistrationRefused):
            store.register_attribute(attr(new[0], "string", doc=new[1]))
    else:
        store.register_attribute(attr(new[0], "string", doc=new[1]))


def test_search_matches_names_and_docs(store):
    store.register_attribute([
        attr("supplier/payment_terms", "string", doc="Agreed payment terms with a supplier, e.g. 30% deposit."),
        attr("shipment/eta", "instant", doc="Expected arrival time at the destination port."),
    ])
    assert store.search_attributes("payment terms")[0].ident == "supplier/payment_terms"
    assert store.search_attributes("arrival")[0].ident == "shipment/eta"
    assert all(not a.ident.startswith("fs/") for a in store.search_attributes("name"))
