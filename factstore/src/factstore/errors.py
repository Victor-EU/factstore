"""Errors. Each carries everything wrong with a call, not just the first problem, so an
agent can fix a batch in one retry."""


class FactstoreError(Exception):
    pass


class TransactError(FactstoreError):
    """A transact call was rejected. Nothing was written.

    `errors` holds one dict per problem: `index` (the input fact, or None for the
    batch as a whole) and `message`.
    """

    def __init__(self, errors: list[dict]):
        self.errors = errors
        lines = [f"fact {e['index']}: {e['message']}" if e["index"] is not None else e["message"]
                 for e in errors]
        super().__init__("transaction rejected:\n" + "\n".join(lines))


class RegistrationRefused(FactstoreError):
    """register_attribute was refused. Nothing was registered.

    `near_matches` maps each refused ident to the existing attributes it resembles;
    `errors` lists any other problems, one dict per problem with `index` and `message`.
    """

    def __init__(self, near_matches: dict[str, list], errors: list[dict]):
        self.near_matches = near_matches
        self.errors = errors
        lines = [f"attribute {e['index']}: {e['message']}" for e in errors]
        for ident, matches in near_matches.items():
            names = ", ".join(m.ident for m in matches)
            lines.append(f"{ident} resembles {names}: reuse one, or list them in distinct_from")
        super().__init__("registration refused:\n" + "\n".join(lines))


class ExcisionError(FactstoreError):
    pass


class PermissionDenied(FactstoreError):
    pass
