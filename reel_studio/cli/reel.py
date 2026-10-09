"""`reel`: the command line (render arrives in STEP-02, make in STEP-03)."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="reel", description="Turn a folder of food clips into an Instagram Reel."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
