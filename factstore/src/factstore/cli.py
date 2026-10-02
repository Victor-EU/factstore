"""factstore admin commands. The admin DSN is a superuser connection string."""

import argparse
import os
import sys

from . import admin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factstore")
    parser.add_argument("--admin-dsn", default=os.environ.get("FACTSTORE_ADMIN_DSN"),
                        help="superuser connection string (default: $FACTSTORE_ADMIN_DSN)")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a store")
    init.add_argument("store")

    actor = commands.add_parser("actor", help="create an actor and print its credential")
    actor.add_argument("store")
    actor.add_argument("name")
    actor.add_argument("--excise", action="store_true", help="an excision credential instead of a writer one")

    credential = commands.add_parser("credential", help="print a new credential for an existing actor")
    credential.add_argument("store")
    credential.add_argument("actor", type=int)
    credential.add_argument("--excise", action="store_true")

    upgrade = commands.add_parser("upgrade", help="rebuild a store's read-side views from this version")
    upgrade.add_argument("store")

    drop = commands.add_parser("drop", help="drop a store and its roles, irreversibly")
    drop.add_argument("store")
    drop.add_argument("--yes", action="store_true", help="confirm")

    args = parser.parse_args(argv)
    if not args.admin_dsn:
        parser.error("give --admin-dsn or set FACTSTORE_ADMIN_DSN")

    if args.command == "init":
        admin.init_store(args.admin_dsn, args.store)
        print(f"created store {args.store}")
    elif args.command == "actor":
        cred = admin.create_actor(args.admin_dsn, args.store, args.name, excise=args.excise)
        print(f"actor {cred.actor}\n{cred.dsn}")
    elif args.command == "credential":
        cred = admin.create_credential(args.admin_dsn, args.store, args.actor, excise=args.excise)
        print(cred.dsn)
    elif args.command == "upgrade":
        admin.upgrade_views(args.admin_dsn, args.store)
        print(f"rebuilt the views of {args.store}")
    elif args.command == "drop":
        if not args.yes:
            parser.error(f"dropping {args.store} deletes it permanently; add --yes to confirm")
        admin.drop_store(args.admin_dsn, args.store)
        print(f"dropped store {args.store}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
