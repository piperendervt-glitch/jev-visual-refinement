"""Launch the approved SC02 loopback UI. No .env or old run is read."""
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys

from .controller import RunController
from .server import SC02Server
from .store import REPO


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="SC02 real video, one pinned segmenter")
    parser.add_argument("--video", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--open-existing", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if args.open_existing == bool(args.video):
        parser.error("specify exactly one of --video and --open-existing")
    weight = REPO / "models" / "sc02" / "yolo11n-seg.pt"
    controller = RunController(video=args.video, run_id=args.run_id, weight=weight,
                               open_existing=args.open_existing)
    server = SC02Server(controller, ("127.0.0.1", args.port))
    print(f"SC02_READY http://127.0.0.1:{server.server_port}/ run={args.run_id}", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        print("SC02_STOP", controller.close(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
