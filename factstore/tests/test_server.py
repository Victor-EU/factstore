"""The MCP server, end to end over stdio, as a client sees it."""

import asyncio
import json
import os
import shutil
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from conftest import attr

SERVER = shutil.which("factstore-mcp") or os.path.join(os.path.dirname(sys.executable), "factstore-mcp")


def session(env: dict, calls):
    """Start the server with `env`, run `calls(session)` and return what it returns."""
    async def main():
        params = StdioServerParameters(command=SERVER, env={**os.environ, **env})
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            return await calls(s)
    return asyncio.run(main())


def payload(result):
    return json.loads(result.content[0].text)


def test_tools_and_a_write_round_trip(store, writer):
    store.register_attribute(attr("supplier/code", "string", unique="identity", doc="Short code we use for a supplier."))

    async def calls(s):
        names = [t.name for t in (await s.list_tools()).tools]
        written = await s.call_tool("transact", {"facts": [{"e": ["supplier/code", "NBBW"], "a": "supplier/code", "v": "NBBW"}]})
        found = await s.call_tool("search_attributes", {"text": "supplier code"})
        stats = await s.call_tool("stats", {})
        return names, written, found, stats

    names, written, found, stats = session({"FACTSTORE_DSN": writer.dsn}, calls)
    assert "excise" not in names
    assert {"transact", "query", "stats", "search_attributes", "register_attribute"} <= set(names)
    assert not written.is_error and payload(written)["tx"]
    assert payload(found)[0]["ident"] == "supplier/code"
    assert payload(stats)["signatures"][0]["attributes"] == ["supplier/code"]


def test_rejections_come_back_as_tool_errors_listing_every_problem(writer):
    async def calls(s):
        return await s.call_tool("transact", {"facts": [{"e": "tmp:a", "a": "nope/one", "v": "x"},
                                                        {"e": "tmp:b", "a": "fs/at", "v": "2026-01-01T00:00:00Z"}]})
    result = session({"FACTSTORE_DSN": writer.dsn}, calls)
    assert result.is_error
    body = payload(result)
    assert body["error"].startswith("transaction rejected")
    assert len(body["problems"]) == 2


def test_excise_is_offered_only_with_an_excision_credential(store_name, writer):
    from factstore import admin
    from conftest import ADMIN_DSN
    excise = admin.create_credential(ADMIN_DSN, store_name, writer.actor, excise=True)

    async def calls(s):
        return [t.name for t in (await s.list_tools()).tools]
    assert "excise" in session({"FACTSTORE_DSN": writer.dsn, "FACTSTORE_EXCISE_DSN": excise.dsn}, calls)
