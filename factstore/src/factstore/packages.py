"""Vocabulary packages (design §8): an attribute set, the packages it builds on, and its skills.

A package is a directory holding manifest.json:

    {
      "name": "factstore-ecom-ops",
      "version": "0.1.0",
      "doc": "One line on what the vocabulary covers.",
      "license": "MIT",
      "depends_on": ["factstore-core"],
      "skills": [],
      "attributes": [
        {"ident": "po/number", "type": "string", "cardinality": "one", "unique": "identity",
         "doc": "Our purchase order number, e.g. PO-2026-0007."},
        ...
      ]
    }

Each attribute is a register_attribute spec, distinct_from included: where the kernel finds a near
match in the package or in a package it depends on, the manifest names it, as an agent would.
`skills` are paths of skill files in the package's directory. `license` is optional: an SPDX
expression, such as "MIT", for a package copied or published apart from its repository.

admin.install registers the attributes a store lacks in one transaction, written by an actor named
after the package, so the log says which package registered what. A new version may also make the
changes the kernel allows to an attribute it already has (cardinality one to many, uniqueness none
to identity), in a transaction of their own before the registration. Nothing else is written and the
kernel learns no names. Installing again writes nothing.
"""

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import fs
from .errors import FactstoreError

MANIFEST = "manifest.json"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
REQUIRED = {"name", "version", "doc", "attributes"}
OPTIONAL = {"license", "depends_on", "skills"}


class PackageError(FactstoreError):
    """A manifest is malformed, or its packages cannot be installed. `problems` lists every one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("package refused:\n" + "\n".join(problems))


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    doc: str
    depends_on: tuple[str, ...]
    skills: tuple[str, ...]
    attributes: tuple[dict, ...]
    path: Path
    license: str | None = None


@dataclass(frozen=True)
class InstallResult:
    package: str
    version: str
    tx: int | None  # the registration transaction; None when the store already had every attribute
    registered: list[str]
    existing: list[str]
    evolved: list[str] = field(default_factory=list)  # attributes made many or identity by this version
    evolve_tx: int | None = None


def load(path) -> Package:
    """Read and check the package at `path`: its directory, or its manifest.json."""
    path = Path(path)
    directory = path.parent if path.name == MANIFEST else path
    try:
        raw = json.loads((directory / MANIFEST).read_text())
    except FileNotFoundError:
        raise PackageError([f"no {MANIFEST} in {directory}"]) from None
    except json.JSONDecodeError as e:
        raise PackageError([f"{directory / MANIFEST} is not JSON: {e}"]) from None
    if not isinstance(raw, dict):
        raise PackageError([f"{directory / MANIFEST} must be a JSON object"])

    problems = []
    if missing := REQUIRED - raw.keys():
        problems.append(f"missing keys {sorted(missing)}")
    if extra := raw.keys() - REQUIRED - OPTIONAL:
        problems.append(f"unexpected keys {sorted(extra)}")
    name, version, doc = raw.get("name"), raw.get("version"), raw.get("doc")
    depends_on, skills, attributes = raw.get("depends_on", []), raw.get("skills", []), raw.get("attributes", [])
    if not isinstance(name, str) or not NAME_RE.match(name):
        problems.append(f"name must be lowercase words joined by hyphens, like factstore-ecom-ops, not {name!r}")
    if not isinstance(version, str) or not version.strip():
        problems.append("version must be a non-empty string")
    if "license" in raw and (not isinstance(raw["license"], str) or not raw["license"].strip()):
        problems.append('license must be an SPDX expression, such as "MIT"')
    if not isinstance(doc, str) or not doc.strip() or "\n" in doc:
        problems.append("doc must be one non-empty line")
    if not isinstance(depends_on, list) or not all(isinstance(d, str) and NAME_RE.match(d) for d in depends_on):
        problems.append("depends_on must be a list of package names")
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        problems.append("skills must be a list of paths in the package's directory")
    else:
        for s in skills:
            target = (directory / s).resolve()
            if not target.is_relative_to(directory.resolve()) or not target.is_file():
                problems.append(f"skill {s} is not a file in {directory}")
    if not isinstance(attributes, list) or not attributes:
        problems.append("attributes must be a non-empty list of register_attribute specs")
    else:
        seen = set()
        for i, spec in enumerate(attributes):
            ident = spec.get("ident") if isinstance(spec, dict) else None
            if not isinstance(ident, str):
                problems.append(f"attribute {i} has no ident")
            elif ident in seen:
                problems.append(f"{ident} appears twice")
            seen.add(ident)
    if problems:
        raise PackageError([f"{directory / MANIFEST}: {p}" for p in problems])
    return Package(name, version, doc.strip(), tuple(depends_on), tuple(skills), tuple(attributes), directory,
                   raw.get("license"))


# The packages a release carries, by name, and where the repository keeps each. The wheel carries
# them under factstore/vocab/, each in a directory named after its directory here.
BUNDLED = {"factstore-core": "packages/core", "factstore-ecom-ops": "packages/ecom-ops",
           "factstore-ecom-index": "packages/ecom-index", "factstore-skills": "factstore-skills"}


def bundled() -> dict[str, Path]:
    """The directory of each package this release carries: in the wheel, or in a source checkout."""
    wheel = resources.files("factstore") / "vocab"
    repo = Path(__file__).resolve().parents[3]
    out = {}
    for name, source in BUNDLED.items():
        inside = wheel / Path(source).name
        out[name] = Path(str(inside)) if inside.joinpath(MANIFEST).is_file() else repo / source
    return out


def find(ref: str) -> Package:
    """A package by its directory, or by the name of one this release carries: factstore-ecom-ops,
    or ecom-ops."""
    if Path(ref).exists():
        return load(ref)
    named = bundled()
    name = ref if ref in named else f"factstore-{ref}"
    if name not in named:
        raise PackageError([f"{ref} is neither a package's directory nor a package this release carries "
                            f"({', '.join(sorted(named))})"])
    return load(named[name])


def with_dependencies(pkgs: list[Package]) -> list[Package]:
    """The packages, with each package they depend on that this release carries."""
    out, named, todo = {p.name: p for p in pkgs}, bundled(), list(pkgs)
    while todo:
        for dep in todo.pop().depends_on:
            if dep not in out and dep in named:
                out[dep] = load(named[dep])
                todo.append(out[dep])
    return list(out.values())


def core() -> Package:
    """factstore-core, which init installs."""
    return load(bundled()["factstore-core"])


def installed(conn) -> set[str]:
    """Names of the actors that have registered attributes outside fs/. A package's installer is
    named after it."""
    return {row[0] for row in conn.execute(
        "select distinct n.v_string from fact i join tx on tx.id = i.tx"
        " join cur n on n.e = tx.actor and n.a = %s"
        " where i.a = %s and i.op and not starts_with(i.v_string, 'fs/')", (fs.NAME, fs.IDENT))}


def install_order(packages: list[Package], already: set[str]) -> list[Package]:
    """`packages` with each after the ones it depends on. Refused if a dependency is neither in
    `already` nor among `packages`, or if dependencies form a cycle."""
    by_name = {p.name: p for p in packages}
    problems = [f"{p.name} depends on {d}, which is neither installed nor being installed"
                for p in packages for d in p.depends_on if d not in by_name and d not in already]
    if len(by_name) < len(packages):
        problems.append("the same package is given twice")
    if problems:
        raise PackageError(problems)
    order: list[Package] = []
    visiting: set[str] = set()

    def visit(p: Package) -> None:
        if any(o.name == p.name for o in order):
            return
        if p.name in visiting:
            raise PackageError([f"{p.name} depends on itself through {' -> '.join(sorted(visiting))}"])
        visiting.add(p.name)
        for d in p.depends_on:
            if d in by_name:
                visit(by_name[d])
        visiting.discard(p.name)
        order.append(p)

    for p in packages:
        visit(p)
    return order
