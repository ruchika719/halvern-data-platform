"""Command-line entry point for ``halvern-gen``.

The ``init``, ``day`` and ``range`` commands arrive in HDP-4.
"""

import argparse

from halvern_gen import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="halvern-gen",
        description="Generate synthetic landing data for the Halvern Data Platform.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("halvern-gen: no commands yet (added in HDP-4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
