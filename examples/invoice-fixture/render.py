"""Shortcut for the installed harness77 Invoice generator."""
import sys

from harness77.cli import main


if __name__ == '__main__':
    raise SystemExit(main(['fixture-render', '--kind', 'invoice', *sys.argv[1:]]))
