"""Launch the finite SC01 fixture UI; no environment file is loaded."""
from argparse import ArgumentParser
from pathlib import Path
import sys

from conversation_ecology.lifecycle import serve_controlled
from .core import FixtureKernel, build_demo
from .server import FixtureServer


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="SC01 fixture-only visual refinement UI")
    parser.add_argument("--root", type=Path, default=Path("runs/sc01-fixture"))
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    kernel = FixtureKernel(root / "state.sqlite3", root / "artifacts")
    try:
        build_demo(kernel)
        server = FixtureServer(kernel, ("127.0.0.1", args.port))
        serve_controlled(server)
        kernel.close_run()
    finally:
        kernel.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
