from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy.exc import OperationalError

from awas.config import get_settings
from awas.db.session import create_database_engine, create_session_factory
from awas.services.auth import UserInputError, create_user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AWAS administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin = subparsers.add_parser("create-admin", help="create an administrator")
    create_admin.add_argument("--username", help="login name; prompted when omitted")
    create_admin.add_argument("--display-name", help="display name; prompted when omitted")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "create-admin":
        raise SystemExit(create_admin_command(args.username, args.display_name))


def create_admin_command(username_argument: str | None, display_name_argument: str | None) -> int:
    settings = get_settings()
    username = username_argument or input("Benutzername: ").strip()
    display_name = display_name_argument or input("Anzeigename: ").strip()
    password = getpass.getpass("Passwort: ")
    password_confirmation = getpass.getpass("Passwort wiederholen: ")

    engine = create_database_engine(settings.database.url)
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            user = create_user(
                db,
                username=username,
                display_name=display_name,
                password=password,
                password_confirmation=password_confirmation,
                role="admin",
                must_change_password=False,
            )
    except UserInputError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except OperationalError:
        print(
            "Fehler: Die Datenbank ist nicht initialisiert. "
            "Führe zuerst die AWAS-Installation aus.",
            file=sys.stderr,
        )
        return 3
    finally:
        engine.dispose()

    print(f"Administrator '{user.username}' wurde angelegt.")
    return 0


if __name__ == "__main__":
    main()
