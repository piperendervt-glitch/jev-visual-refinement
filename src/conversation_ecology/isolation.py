"""C0プロセスの能力境界。ホスト全体の通信監査ではない。"""
import os
import sys

FORBIDDEN_IMPORTS = {"context_fields", "torch", "transformers", "faster_whisper", "cv2", "av",
                     "sounddevice", "pyaudio", "ollama", "openai", "anthropic"}


class Boundary:
    def __init__(self):
        self.denied = {"external_socket": 0, "secret_read": 0, "model_import": 0, "subprocess": 0}

    def guard(self, event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            address = args[1] if event == "socket.connect" else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {"127.0.0.1", "::1", "localhost"}:
                self.denied["external_socket"] += 1
                raise PermissionError("C0_external_network_denied")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.fsdecode(args[0]).replace("\\", "/").lower()
            parts = path.split("/")
            if any(p.startswith(".env") or p in {"private", "models", "runs"} for p in parts) or path.startswith("//./"):
                self.denied["secret_read"] += 1
                raise PermissionError("C0_private_input_denied")
        if event == "import" and args[0].split(".")[0] in FORBIDDEN_IMPORTS:
            self.denied["model_import"] += 1
            raise PermissionError("C0_live_import_denied")
        if event in {"subprocess.Popen", "os.system", "os.spawn", "os.exec"}:
            self.denied["subprocess"] += 1
            raise PermissionError("C0_child_process_denied")

    def install(self):
        sys.addaudithook(self.guard)
