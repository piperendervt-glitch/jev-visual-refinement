"""Launch one approved live run or replay one saved run on loopback."""
from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import sys

from .batch import BatchManager
from .controller import LiveController
from .jev_client import JevEvaluator, load_dedicated_key
from .ledger import BudgetLedger
from .ownership import WriterLease
from .server import LiveServer
from .store import RUNS_ROOT

APPROVAL_PROFILE = RUNS_ROOT / "approved_profile.json"
LANE_PROFILES = {"S": ("S",), "SAB": ("S", "A", "B"),
                 "SABC": ("S", "A", "B", "C")}


def _approved_video(video: Path) -> dict:
    if not APPROVAL_PROFILE.is_file():
        raise ValueError("all_remaining_profile_not_approved")
    profile = json.loads(APPROVAL_PROFILE.read_text(encoding="utf-8"))
    if profile.get("status") != "APPROVED" or Path(profile.get("video", "")).resolve() != video.resolve():
        raise ValueError("video_outside_approved_profile")
    return profile


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Four-lane visual refinement on one approved video")
    parser.add_argument("--video", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--open-existing", action="store_true")
    parser.add_argument("--profile", choices=tuple(LANE_PROFILES), default="SABC")
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--bucket", choices=("VALIDATION", "NORMAL"), default="NORMAL")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if args.open_existing == bool(args.video):
        parser.error("specify exactly one of --video and --open-existing")
    if args.open_existing and args.jev:
        parser.error("saved runs are read-only")
    profile = _approved_video(args.video) if args.video else None
    if args.jev and (profile is None or not profile.get("jev_send_approved")):
        parser.error("Jev transmission requires the approved profile")
    if args.jev:
        load_dedicated_key()

    lease = WriterLease() if args.video else None
    ledger = None
    controller = None
    manager = None
    server = None
    if lease:
        lease.acquire()
    try:
        ledger = BudgetLedger() if args.video else None
        controller = LiveController(
            video=args.video, run_id=args.run_id,
            lanes=LANE_PROFILES[args.profile], open_existing=args.open_existing,
            experiment={"profile": args.profile, "bucket": args.bucket,
                        "jev": bool(args.jev), "origin": "REAL"} if args.video else None,
            job_ledger=ledger, bucket=args.bucket)
        if args.jev:
            controller.evaluator = JevEvaluator(
                controller.store, ledger, bucket=args.bucket,
                is_current=lambda fid: controller.accepting and
                not controller.cancel.is_set() and
                controller.frame_generations.get(fid) == controller.generation)
        manager = BatchManager(args.video, ledger, main_controller=controller) if (
            args.video and profile.get("jev_send_approved")) else None
        server = LiveServer(controller, ("127.0.0.1", args.port), batch_manager=manager)
        print(f"LIVE_READY http://127.0.0.1:{server.server_port}/ run={args.run_id}", flush=True)
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
    finally:
        try:
            if manager:
                manager.close()
        finally:
            try:
                if controller:
                    result = controller.close()
                    print(f"LIVE_STOP normal={result['normal']} business={result['business']}", flush=True)
            finally:
                try:
                    if ledger:
                        ledger.close()
                finally:
                    if lease:
                        lease.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
