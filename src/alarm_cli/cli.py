"""The argparse surface: parse, delegate, format, set the exit code.

Nothing imports this module. The commands themselves arrive in M3; for now the
surface exists so that packaging and the console script are real.

Exit codes: 0 success, 1 a handled error, 2 an argparse usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from alarm_cli import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm",
        description="Set a one-off alarm for a clock time and get interrupted when it fires.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # No subcommands yet (M3). Invoked bare, the only useful thing to do is say so.
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
