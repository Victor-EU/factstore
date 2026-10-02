"""factstore-fixture: simulate the brand, export its source files, load it into a store, benchmark."""

import argparse
import json
import os
import sys

from factstore import connect

from . import bench
from .exports import export
from .load import load
from .report import realism
from .simulate import Simulation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factstore-fixture")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--scale", type=float, default=1.0, help="demand multiplier; 1 is a ~$4M/year brand")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("report", help="print the realism report")
    p = commands.add_parser("export", help="write source-shaped files and ground truth")
    p.add_argument("outdir")
    p = commands.add_parser("load", help="load the world into a store through transact")
    p.add_argument("dsn", help="a factstore writer credential")
    p.add_argument("--batch", type=int, default=200, help="orders per transaction")
    p = commands.add_parser("bench", help="load throughput by transaction size and writers")
    p.add_argument("--admin-dsn", default=os.environ.get("FACTSTORE_ADMIN_DSN"))
    p.add_argument("--facts", type=int, default=350_000, help="size of the world")
    p.add_argument("--batches", default="1,10,100,1000")
    p.add_argument("--writers", default="1,4")
    p.add_argument("--cap", type=int, default=60_000, help="facts to time per configuration")
    p.add_argument("--out", help="write the table here, and the numbers beside it as JSON")
    p = commands.add_parser("bench-scale", help="load a large world, then time single-order writes against it")
    p.add_argument("--admin-dsn", default=os.environ.get("FACTSTORE_ADMIN_DSN"))
    p.add_argument("--facts", type=int, default=10_000_000)
    p.add_argument("--batch", type=int, default=1000)

    args = parser.parse_args(argv)
    if args.command == "report":
        print(realism(args.seed, args.scale))
    elif args.command == "export":
        print(json.dumps(export(args.outdir, args.seed, args.scale), indent=2))
    elif args.command == "load":
        with connect(args.dsn) as store:
            stats = load(store, Simulation(args.seed, args.scale), batch=args.batch,
                         progress=lambda s: print(f"{s.orders:,} orders", end="\r", flush=True))
        print(f"\n{stats.transactions:,} transactions, {stats.facts:,} facts in {stats.seconds:.0f}s")
    elif args.command == "bench":
        if not args.admin_dsn:
            parser.error("give --admin-dsn or set FACTSTORE_ADMIN_DSN")
        results = []
        for writers in map(int, args.writers.split(",")):
            for batch in map(int, args.batches.split(",")):
                if writers > 1 and batch == 1:
                    continue
                result = bench.run(args.admin_dsn, facts=args.facts, batch=batch, writers=writers,
                                   seed=args.seed, cap_facts=args.cap)
                print(f"batch {batch}, writers {writers}: {result.facts_per_second:,} facts/s", file=sys.stderr)
                results.append(result)
        print(bench.report(results, args.facts, args.out))
    elif args.command == "bench-scale":
        if not args.admin_dsn:
            parser.error("give --admin-dsn or set FACTSTORE_ADMIN_DSN")
        print(json.dumps(bench.scale_run(args.admin_dsn, facts=args.facts, batch=args.batch, seed=args.seed),
                         indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
