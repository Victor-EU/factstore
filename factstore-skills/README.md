# factstore-skills

Build plan M4. The procedures of design Part III, for agents. Neither adds kernel code.

| Skill | What it does |
|---|---|
| [`factstore-catalogue`](catalogue/SKILL.md) | Indexes a company's systems (design §6), from exports. Each record is indexed under its own system's ID, with refs to the records it names. It resolves the same thing across systems and records which system owns which field. Identifiers and join keys only, per open question 2. |
| [`factstore-ontology`](ontology/SKILL.md) | Reads `stats`, groups attribute signatures into shapes, and proposes names to a person (design §7). It records the names they confirm. |

The ingestion skill for supplier documents belongs to its vocabulary: [`ecom-ops-ingest-documents`](../packages/ecom-ops/ingest-documents/SKILL.md) in factstore-ecom-ops.

## Format

Each skill is an [Agent Skill](https://agentskills.io): a directory holding `SKILL.md`, with a `name` and a `description` in its frontmatter. Agents load it by that description.
- **Claude Code:** copy or link the directory into `.claude/skills/`.
- **Other agents:** read `SKILL.md` as instructions.

Either way, the agent also needs the factstore MCP server. The catalogue and ingestion skills also need a shell with Python and the SDK for bulk writes.

## The shape vocabulary

This directory is also a package, [`manifest.json`](manifest.json). It holds the vocabulary the ontology skill records shapes with:

| Attribute | |
|---|---|
| `shape/name` | Identity. The name a person confirmed, such as "Purchase order". |
| `shape/signature` | Ref, many. Each attribute every entity of the shape carries, as the attribute's own entity. |
| `shape/doc` | One line on what the shape's entities are. |

A shape's members are derived, not stored: they are the entities that carry every attribute in its signature. Only the name is declared, and the transaction that records it says on whose behalf.

Install it like any package:

```bash
factstore install STORE factstore-skills
```

Its near-match check works as M3 found for the other packages. Name variants such as `shape/shape_name`, `entity_type/name` and `shape/attributes` are refused. Synonyms such as `shape/label` and `shape/description` pass.

## Measured

[evals/m4](../evals/m4/README.md) runs each skill on the fixture's exports and scores it against the fixture's ground truth. With Sonnet:
- **Catalogue:**
  - precision and recall 1.0 for every SKU's ID in nine systems;
  - duplicate customers at precision 1.0 and recall 0.89;
  - no personal data written;
  - a second run created nothing.
- **Ontology:** all 18 of the fixture's shapes.

The skills' text changed four times on the way. Each change came from a run's failure, and the eval's README lists them.
