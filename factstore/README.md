# factstore

The kernel from [the design](../factstore-design.md): facts, registered attributes and transactions on Postgres. This is build plan milestone M1, the write path. `query`, `stats` and the MCP server come in M2.

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
.venv/bin/factstore init demo
.venv/bin/factstore actor demo "catalogue agent"     # prints the actor ID and its credential
```

```python
import factstore

store = factstore.connect("<credential from above>")
store.register_attribute({"ident": "shopify/order_id", "type": "string", "cardinality": "one",
                          "unique": "identity", "doc": "Shopify's ID for an order."})
store.transact([{"e": ["shopify/order_id", "1234"], "a": "shopify/order_id", "v": "1234"}])
```

With `FACTSTORE_DSN` set, the same calls work at module level: `factstore.transact([...])`.

## Layout

| File | What |
|---|---|
| `schema.sql` | Tables, roles, and the triggers that enforce the invariants in Postgres |
| `kernel.py` | The writer lock, schema loading, allocation, and applying changes to the log and derived tables |
| `store.py` | `transact`, `register_attribute`, `search_attributes`, `excise` |
| `admin.py`, `cli.py` | Creating stores, actors and credentials |
| `tools.py` | MCP tool descriptions and input schemas: the model-facing documentation |
| `fs.py` | The kernel's own `fs/` attributes |
| `tests/reference.py` | The reference reader: a naive fold over the log, used as the test oracle |

## How the invariants are enforced

Postgres enforces them, not just the Python code:

- **Immutability.** Writers have `INSERT` and `SELECT` on the `fact` table, and nothing else. Triggers refuse `UPDATE`, `TRUNCATE`, and any `DELETE` outside `fs_excise()`, even from the owner.
- **The kernel says who wrote.** A credential is a Postgres login. A trigger sets each transaction's actor from `session_user` and its time from the clock, overwriting anything the client sends. Only the kernel's own functions can write `fs/actor`, `fs/at` and `fs/excised_*` facts.
- **Registered, typed attributes.** Every fact must name a registered attribute (enforced by a foreign key), and a trigger checks its value has that attribute's type. Another trigger stops attributes changing in the wrong direction (a type change, many to one, removing uniqueness).
- **Commit order.** Each write takes one advisory lock per store and allocates its transaction ID inside it. The trigger takes the same lock again and refuses an ID that isn't after the latest.

## Decisions made while building

- **Extra `fs/` attributes.** Besides the ones the design lists, the kernel uses:
  - `fs/ident` for an attribute's name;
  - `fs/name` for an actor's display name;
  - `fs/excised_entity` and `fs/excised_attribute` to record an excision.
- **Cardinality one is enforced at write time.** Asserting a new value writes an explicit retraction of the old one to the log. Current state is then a plain fold over assertions and retractions, whatever an attribute's cardinality was at the time.
- **Redundant writes are dropped.** Asserting a value the entity already has, or retracting one it doesn't have, is reported as unchanged and not logged. A call that changes nothing writes no transaction, so re-running an ingestion leaves the log alone.
- **Lookups create only from assertions.** A lookup that finds nothing creates the entity when the call asserts something. If the lookup is used only to retract, the call is an error.
- **Near-match thresholds.** These are a first calibration on sample attributes, set at the top of `store.py`; `tests/test_register.py` records the cases they were checked against. The "attributes registered" measure in M5 is what tunes them.
