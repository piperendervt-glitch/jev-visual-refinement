"""C0専用stdin制御。HTTP認証・会話イベントとは独立したrunの終了処理。"""
from datetime import datetime, timezone
import json
import os
import sys
import threading
import uuid


class StopRequest:
    def __init__(self, run_id):
        self.run_id = run_id
        self.accepted = False

    def accept(self, line):
        if self.accepted or line.strip() != f"stop {self.run_id}":
            return False
        self.accepted = True
        return True


def serve_controlled(server, control=None, output=None):
    """stdin所有者だけが制御。EOFも親の消滅として同じ終了経路へ入る。"""
    control = sys.stdin if control is None else control
    output = sys.stdout if output is None else output
    run_id = uuid.uuid4().hex  # 公開の取り違え防止ID。HTTP tokenではない。
    request = StopRequest(run_id)
    failures = []

    def record(stage, **values):
        print(json.dumps(dict(stage=stage, run_id=run_id, pid=os.getpid(),
                              utc=datetime.now(timezone.utc).isoformat(), **values)),
              file=output, flush=True)

    def serve():
        try:
            server.serve_forever(poll_interval=0.05)
        except BaseException as error:
            failures.append(error)
        finally:
            record("loop_ended", failed=bool(failures))

    worker = threading.Thread(target=serve, name="c0-http-loop", daemon=False)
    worker.start()
    try:
        record("ready", port=server.server_port, stop_command=f"stop {run_id}")
        while True:
            line = control.readline(128)
            if not line:
                record("stop_accepted", reason="stdin_eof")
                break
            if len(line) == 128 and not line.endswith("\n"):
                raise ValueError("C0_control_line_too_long")
            if request.accept(line):
                record("stop_accepted", reason="run_command")
                break
            record("stop_rejected")  # 入力内容は記録しない。
    except KeyboardInterrupt:
        record("stop_accepted", reason="keyboard_interrupt")
    finally:
        try:
            # serve_foreverはworker。shutdownはmainから呼ぶ。
            server.shutdown()
            worker.join()
        finally:
            server.server_close()  # 非daemonのrequest workerもjoinする。
        record("cleanup_completed", loop_thread_alive=worker.is_alive())
    if failures:
        raise RuntimeError("C0_serve_loop_failed") from failures[0]
