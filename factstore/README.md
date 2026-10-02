# factstore

The kernel from [the design](../factstore-design.md): facts, registered attributes and transactions on Postgres, the six calls, and the MCP server `factstore`. Build plan milestones M1 (the write path) and M2 (the read path, the MCP server and the SDK), and M3's package installer.

## Run it

```bash
docker compose up -d                      # from the repo root: Postgres 17 on port 54329
cd factstore
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

The tests create and drop a store per test. To use a store yourself:

```bash
export FACTSTORE_ADMIN_DSN=postgresql://postgres:postgres@localhost:54329/postgres
.venv/bin/factstore init demo                        # with factstore-core installed
.venv/bin/factstore install demo ../packages/ecom-ops ../factstore-skills
.venv/bin/factstore actor demo "catalogue agent"     # prints the actor ID and its credential
```

[`packages/`](../packages/README.md) describes the package format and the packages. A new version of a package registers what it adds. It may also make an attribute many or identity, the two changes the kernel allows. [`factstore-skills/`](../factstore-skills/README.md) holds the catalogue and ontology skills (M4).

```python
import factstore

store = factstore.connect("<credential from above>")
store.register_attribute({"ident": "shopify/order_id", "type": "string", "cardinality": "one",
                          "unique": "identity", "doc": "Shopify's ID for an order."})
store.transact([{"e": ["shopify/order_id", "1234"], "a": "shopify/order_id", "v": "1234"}])
store.query('select e, v from "shopify/order_id"').rows
```

With `FACTSTORE_DSN` set, the same calls work at module level: `factstore.transact([...])`, `factstore.query(...)`.

## The MCP server

`factstore-mcp` serves the calls as tools over stdio. The credential comes from its environment, never from a tool call:

```json
{"mcpServers": {"factstore": {"command": "/path/to/.venv/bin/factstore-mcp",
                              "env": {"FACTSTORE_DSN": "<credential>"}}}}
```

`excise` is listed only when `FACTSTORE_EXCISE_DSN` holds an excision credential as well. The tool descriptions in `tools.py` are the documentation models read.

## Layout

| File | What |
|---|---|
| `schema.sql` | Tables, roles, and the triggers that enforce the invariants in Postgres |
| `kernel.py` | The writer lock, schema loading, allocation, and applying changes to the log and derived tables |
| `store.py` | The calls: `transact`, `query`, `stats`, `register_attribute`, `search_attributes`, `excise` |
| `read.py` | Running one read safely: read-only, rolled back, one statement, a timeout, a row cap |
| `stats.py` | Attribute usage, signatures and ref connectivity |
| `server.py` | The MCP server |
| `admin.py`, `cli.py` | Creating stores, actors and credentials; installing packages |
| `packages.py` | Package manifests, and the order to install them in |
| `tools.py` | MCP tool descriptions and input schemas: the model-facing documentation |
| `fs.py` | The kernel's own `fs/` attributes |
| `tests/reference.py` | The reference reader: a naive fold over the log, used as the test oracle |

## How the invariants are enforced

Postgres enforces them, not just the Python code:

- **Immutability.** Writers have `INSERT` and `SELECT` on the `fact` table, and nothing else. Triggers refuse `UPDATE`, `TRUNCATE`, and any `DELETE` outside `fs_excise()`, even from the owner.
- **The kernel says who wrote.** A credential is a Postgres login. A trigger sets each transaction's actor from `session_user` and its time from the clock, overwriting anything the client sends. Only the kernel's own functions can write `fs/actor`, `fs/at` and `fs/excised_*` facts.
- **Registered, typed attributes.** Every fact must name a registered attribute (enforced by a foreign key), and a trigger checks its value has that attribute's type. Another trigger stops attributes changing in the wrong direction (a type change, many to one, removing uniqueness).
- **Commit order.** Each write takes one advisory lock per store and allocates its transaction ID inside it. The trigger takes the same lock again and refuses an ID that isn't after the latest.

## Reading

`query` takes one SQL statement over views (design open question 1, decided by the [spike](../spike/oq1/README.md)):
- Every attribute is a view named after it: `"po/status"(e, v, tx)` in schema `current`, and `history."po/status"(e, v, tx, op)` over the whole log.
- Registration creates the views with a trigger.
- An as-of read sets `factstore.as_of`, which every view honours.

A model writes the SQL, so `read.py` runs it on a separate connection:
- inside a `READ ONLY` transaction that is always rolled back, which undoes anything the statement changes, `SET ROLE` included;
- prepared, so Postgres refuses a second statement;
- with a 10 s timeout and a 1,000-row cap.

Advisory locks survive a rollback, so they are released after every read; a query can never hold the writer lock.

`stats` groups entities by **signature**, the exact set of attributes each one carries, and counts refs between signatures. That is co-occurrence in the form the ontology skill needs: a kind of thing is usually one signature, or a few that differ by optional attributes.

## Decisions made while building

- **Cardinality one is enforced at write time.** Asserting a new value writes an explicit retraction of the old one to the log. Current state is then a plain fold over assertions and retractions, whatever an attribute's cardinality was at the time.
- **Redundant writes are dropped.** Asserting a value the entity already has, or retracting one it doesn't have, is reported as unchanged and not logged. A call that changes nothing writes no transaction, so re-running an ingestion leaves the log alone.
- **Lookups create only from assertions.** A lookup that finds nothing creates the entity when the call asserts something. If the lookup is used only to retract, the call is an error.
- **String equality has a hash index.** The btree on string values indexes their first 200 characters, so long values never break an insert. Equality goes through a hash index on the whole value, which `v = 'x'` on any view can use.
- **Kernel tests run on bare stores.** `init` installs factstore-core, but the kernel's tests pass `core=False`: the kernel knows no names, so its tests shouldn't depend on core's. The packages have their own tests.
- **Near-match thresholds.** These are a first calibration on sample attributes, set at the top of `store.py`; `tests/test_register.py` records the cases they were checked against. The "attributes registered" measure in M5 is what tunes them.
