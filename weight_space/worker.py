"""Retired Python submission worker. It never loads submitted source."""

from .security import CODE_DISABLED


def evaluate(directory, result_path):
    raise ValueError(CODE_DISABLED)


if __name__ == "__main__":
    import sys

    print(CODE_DISABLED, file=sys.stderr)
    raise SystemExit(2)
