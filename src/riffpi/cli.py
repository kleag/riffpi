#!/usr/bin/env python3
"""Command-line entry point for the `riffpi` console script."""
import argparse

from .daemon import run as run_daemon
from .service import install_service, uninstall_service


def main():
    parser = argparse.ArgumentParser(
        prog="riffpi", description="RiffPi guitar multi-effect pedal daemon."
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="Run the RiffPi daemon (default if no command is given)")
    subparsers.add_parser(
        "install-service", help="Install, enable, and start the riffpi systemd --user service"
    )
    subparsers.add_parser(
        "uninstall-service", help="Stop, disable, and remove the riffpi systemd --user service"
    )

    args = parser.parse_args()

    if args.command in (None, "run"):
        run_daemon()
    elif args.command == "install-service":
        install_service()
    elif args.command == "uninstall-service":
        uninstall_service()


if __name__ == "__main__":
    main()
