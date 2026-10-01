"""factstore: the facts component.

    import factstore
    factstore.transact([{"e": "tmp:s", "a": "supplier/name", "v": "Shenzhen Widget Co"}])

The module-level calls use the store at FACTSTORE_DSN. For any other store, use
factstore.connect(dsn) and call the same methods on the Store it returns.
"""

import os

from .errors import ExcisionError, FactstoreError, PermissionDenied, RegistrationRefused, TransactError
from .store import Attribute, Fact, NearMatch, RegisterResult, Store, TransactResult, connect

__all__ = [
    "Attribute", "ExcisionError", "Fact", "FactstoreError", "NearMatch", "PermissionDenied",
    "RegisterResult", "RegistrationRefused", "Store", "TransactError", "TransactResult",
    "connect", "excise", "register_attribute", "search_attributes", "transact",
]

_default: Store | None = None


def _store() -> Store:
    global _default
    if _default is None:
        dsn = os.environ.get("FACTSTORE_DSN")
        if not dsn:
            raise FactstoreError("set FACTSTORE_DSN to a factstore credential, or use factstore.connect(dsn)")
        _default = connect(dsn)
    return _default


def transact(facts: list[dict], *, dry_run: bool = False) -> TransactResult:
    return _store().transact(facts, dry_run=dry_run)


def register_attribute(specs: dict | list[dict]) -> RegisterResult:
    return _store().register_attribute(specs)


def search_attributes(text: str, *, limit: int = 10) -> list[Attribute]:
    return _store().search_attributes(text, limit=limit)


def excise(entity, attributes: list[str] | None = None) -> int:
    return _store().excise(entity, attributes)
