"""Bundles the vocabulary packages and their skills, which the repository keeps beside the kernel.

A build from the repository takes them from ../packages and ../factstore-skills. An sdist carries
them under vocab/, so a wheel built from it takes them from there. The wheel puts them under
factstore/vocab/, where packages.bundled() finds them.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

SOURCES = {"core": "../packages/core", "ecom-ops": "../packages/ecom-ops",
           "ecom-index": "../packages/ecom-index", "factstore-skills": "../factstore-skills"}


class BundleHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        prefix = "factstore/vocab" if self.target_name == "wheel" else "vocab"
        for name, source in SOURCES.items():
            path = root / source if (root / source).is_dir() else root / "vocab" / name
            if not (path / "manifest.json").is_file():
                raise FileNotFoundError(f"no package to bundle at {path}")
            build_data["force_include"][str(path)] = f"{prefix}/{name}"
