"""python -m pcagent -> CLI (см. pcagent/cli.py)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from pcagent.cli import main as cli_main

    return int(cli_main(sys.argv[1:] if argv is None else argv) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
