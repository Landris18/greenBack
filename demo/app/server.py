import hashlib
import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))
VARIANT = os.environ.get("VARIANT", "inconnu")
WORK_ROUNDS = int(os.environ.get("WORK_ROUNDS", "12000"))
BALLAST_MB = int(os.environ.get("BALLAST_MB", "0"))

_ballast: list[bytes] = []
_counter = {"requests": 0}
_lock = threading.Lock()


def allocate_ballast() -> None:
    for _ in range(BALLAST_MB):
        _ballast.append(bytes(random.getrandbits(8) for _ in range(1024)) * 1024)


def burn_cpu(rounds: int) -> str:
    digest = b"greensi"
    for _ in range(rounds):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()[:16]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        with _lock:
            _counter["requests"] += 1
            served = _counter["requests"]

        if self.path.startswith("/health"):
            self._send({"status": "ok", "variant": VARIANT})
            return

        started = time.perf_counter()
        signature = burn_cpu(WORK_ROUNDS)
        self._send(
            {
                "variant": VARIANT,
                "signature": signature,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "requests_served": served,
                "ballast_mb": BALLAST_MB,
            }
        )

    def log_message(self, *args) -> None:
        return


if __name__ == "__main__":
    allocate_ballast()
    print(f"demo {VARIANT} en ecoute sur {PORT}, ballast {BALLAST_MB} Mo", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
