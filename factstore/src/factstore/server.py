"""The MCP server `factstore`: the kernel's calls as tools, over stdio.

The writer credential comes from the server's config (FACTSTORE_DSN), never from a tool call,
so every transaction is stamped with the actor it belongs to. `excise` is listed only when the
server is also given an excision credential (FACTSTORE_EXCISE_DSN).
"""

import asyncio
import dataclasses
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import tools
from .errors import FactstoreError, RegistrationRefused, TransactError
from .read import BeforeFirstTransaction
from .store import Store, connect


def build(store: Store, exciser: Store | None = None) -> Server:
    specs = [t for t in tools.TOOLS if t["name"] != "excise" or exciser is not None]
    names = {t["name"] for t in specs}
    lock = asyncio.Lock()  # one call at a time on the store's connections

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name=t["name"], description=t["description"], input_schema=t["inputSchema"]) for t in specs])

    async def call_tool(ctx, params):
        if params.name not in names:
            return _error({"error": f"unknown tool {params.name}"})
        try:
            async with lock:
                result = await asyncio.to_thread(dispatch, store, exciser, params.name, params.arguments or {})
        except TransactError as exc:
            return _error({"error": "transaction rejected; nothing was written", "problems": exc.errors})
        except RegistrationRefused as exc:
            return _error({"error": "registration refused; nothing was registered",
                           "near_matches": {k: [plain(m) for m in v] for k, v in exc.near_matches.items()},
                           "problems": exc.errors,
                           "next": REFUSAL_NEXT if exc.near_matches else None})
        except BeforeFirstTransaction as exc:
            return _error({"error": str(exc), "next": tools.WHAT_WAS_KNOWN})
        except (FactstoreError, TypeError, ValueError) as exc:
            return _error({"error": str(exc)})
        text = json.dumps(result, default=str, ensure_ascii=False)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    return Server("factstore", instructions=INSTRUCTIONS, on_list_tools=list_tools, on_call_tool=call_tool)


REFUSAL_NEXT = (
    "Existing attributes look like what you need. Use one of them if its doc fits, putting the value on "
    "the entity it describes. Register again with distinct_from only if they mean something different; "
    "distinct_from is recorded as your judgement that they do.")

INSTRUCTIONS = """\
A store of facts with provenance. Search attributes before registering one; query and stats \
read, transact writes. Every write is stamped with your credential's actor and its time.

What goes in, from any source:
- Identifiers, the refs between records, and the values someone will look up, such as a date, a \
quantity, a status or a deal number. Not copies of text: a message's body, a summary or a note \
stays in its document.
- No personal data. A person's name, email address, phone number and postal address stay in the \
source. Name a record by its system's ID, and a document by its URL.
- Each document once, however many copies of it you are given: one entity, identified by \
document/hash, with document/url and document/issued_at.
- Every fact you read from a document cites it: {"e": "tmp:tx", "a": "core/evidence", "v": \
<the document>} in the same transaction."""


def dispatch(store: Store, exciser: Store | None, name: str, args: dict):
    if name == "transact":
        return plain(store.transact(args["facts"], dry_run=args.get("dry_run", False)))
    if name == "query":
        return plain(store.query(args["sql"], as_of=args.get("as_of")))
    if name == "stats":
        return plain(store.stats(**args))
    if name == "search_attributes":
        return [plain(a) for a in store.search_attributes(args["text"], limit=args.get("limit", 10))]
    if name == "register_attribute":
        return plain(store.register_attribute(args["attributes"]))
    if name == "excise":
        tx = exciser.excise(args["entity"], args.get("attributes"))
        return {"tx": tx}
    raise ValueError(f"unknown tool {name}")


def plain(x):
    """Results as JSON: decimals as strings so they stay exact, dates and instants as ISO 8601."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: plain(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, timedelta):
        return str(x)
    return x


def _error(payload: dict) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload, default=str))],
                                is_error=True)


async def serve(dsn: str, excise_dsn: str | None = None) -> None:
    store = connect(dsn)
    exciser = connect(excise_dsn) if excise_dsn else None
    server = build(store, exciser)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> int:
    dsn = os.environ.get("FACTSTORE_DSN")
    if not dsn:
        raise SystemExit("set FACTSTORE_DSN to a factstore credential")
    asyncio.run(serve(dsn, os.environ.get("FACTSTORE_EXCISE_DSN")))
    return 0
