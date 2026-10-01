"""Value types: checking what callers pass, and canonical keys for identity attributes."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

TYPES = ("string", "decimal", "boolean", "date", "instant", "ref")

COLUMN = {
    "string": "v_string",
    "decimal": "v_decimal",
    "boolean": "v_boolean",
    "date": "v_date",
    "instant": "v_instant",
    "ref": "v_ref",
}

# Identity values are index keys; identifiers are short.
MAX_KEY_LENGTH = 512


class BadValue(Exception):
    """A value that does not fit its attribute's type."""


def coerce(type_: str, raw):
    """Return `raw` as the Python value for `type_`, or raise BadValue. Not for refs."""
    if type_ == "string":
        if not isinstance(raw, str):
            raise BadValue(f"expected a string, got {_kind(raw)}")
        return raw
    if type_ == "decimal":
        return _decimal(raw)
    if type_ == "boolean":
        if not isinstance(raw, bool):
            raise BadValue(f"expected true or false, got {_kind(raw)}")
        return raw
    if type_ == "date":
        return _date(raw)
    if type_ == "instant":
        return _instant(raw)
    raise AssertionError(f"coerce() does not handle {type_}")


def key(type_: str, value) -> str:
    """Canonical text of a value, equal for equal values: the identity index key."""
    if type_ == "string":
        return value
    if type_ == "decimal":
        return "0" if value == 0 else format(value.normalize(), "f")
    if type_ == "date":
        return value.isoformat()
    if type_ == "instant":
        return value.astimezone(timezone.utc).isoformat()
    if type_ == "ref":
        return str(value)
    raise AssertionError(f"{type_} values have no identity key")


def to_json(value):
    """A value as JSON: decimals as strings so they stay exact, dates and instants as ISO 8601."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _decimal(raw) -> Decimal:
    if isinstance(raw, bool):
        raise BadValue("expected a decimal, got a boolean")
    if isinstance(raw, float):
        raise BadValue("decimals are never floats; pass a string such as \"99.50\"")
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, str):
        try:
            value = Decimal(raw.strip())
        except InvalidOperation:
            raise BadValue(f"{raw!r} is not a decimal") from None
    else:
        raise BadValue(f"expected a decimal as a string, got {_kind(raw)}")
    if not value.is_finite():
        raise BadValue(f"{raw!r} is not a finite decimal")
    return value


def _date(raw) -> date:
    if isinstance(raw, datetime):
        raise BadValue("expected a calendar date, got a date and time; use an instant attribute for points in time")
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise BadValue(f"{raw!r} is not a date (YYYY-MM-DD)") from None
    raise BadValue(f"expected a date as YYYY-MM-DD, got {_kind(raw)}")


def _instant(raw) -> datetime:
    if isinstance(raw, str):
        try:
            raw = datetime.fromisoformat(raw)
        except ValueError:
            raise BadValue(f"{raw!r} is not an ISO 8601 date and time") from None
    elif not isinstance(raw, datetime):
        raise BadValue(f"expected an ISO 8601 date and time with a timezone, got {_kind(raw)}")
    if raw.tzinfo is None or raw.utcoffset() is None:
        raise BadValue(f"{raw.isoformat()} has no timezone; instants need one, e.g. +08:00 or Z")
    return raw


def _kind(raw) -> str:
    return "null" if raw is None else type(raw).__name__
