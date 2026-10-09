"""`reelctl`: operator commands for the hosted beta (arrive in STEP-07)."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="reelctl", description="Operate the Reel Studio beta: codes, orders, pause."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
