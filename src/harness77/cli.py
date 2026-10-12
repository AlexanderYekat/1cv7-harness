"""One command, with the existing per-operation contracts preserved."""

import argparse
import sys

from . import __version__


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="harness77", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", choices=("lint", "compiler-protocol", "extract", "build"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "lint":
        from .lint77 import main as operation
    elif args.command == "compiler-protocol":
        from .compiler_protocol77 import main as operation
    else:
        from .artifacts import main as artifact_main
        return artifact_main(args.command, args.arguments)
    return operation(args.arguments)
