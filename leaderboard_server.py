"""
Replay-verified global leaderboard server for Swarmada.

Runs on your VPS with just Python 3 + pygame (no display needed). Every
submitted score is re-simulated from its seed + recorded inputs; if the
recomputed score doesn't match the claim, it's rejected. That makes forged
scores impractical — a fake number won't reproduce.

    pip install pygame
    python leaderboard_server.py            # listens on 0.0.0.0:8000

Then on the player's machine, point the game at it:
    SWARMADA_SERVER=http://YOUR_VPS_IP:8000 python swarmada.py

IMPORTANT: keep this server's copy of swarmada.py identical to the
players' copy — the simulation (and SIM_VERSION) must match, or valid
replays will be rejected.
"""

import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import swarmada as hs

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leaderboard.json")
MAX_BODY = 8 * 1024 * 1024        # 8 MB cap on a submission
MAX_STEPS = 300_000              # ~80 min of play; bounds verify CPU cost
TOP_N = 100
RATE_PER_MIN = 20               # max submissions per IP per minute

_lock = threading.Lock()
_rate = {}                      # ip -> [timestamps]


def _load():
    try:
        with open(DB_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _public(board):
    """Board view without the private owner hashes."""
    return [{k: v for k, v in e.items() if k != "owner"} for e in board[:TOP_N]]


def _store(entry, owner):
    """Name ownership: a name belongs to the token that first claimed it. Returns
    the public board, or None if the name is owned by a different player."""
    with _lock:
        board = _load()
        name_l = entry["name"].lower()
        existing = next((e for e in board if str(e.get("name", "")).lower() == name_l), None)
        if existing is not None:
            owned_by = existing.get("owner")
            if owned_by and owned_by != owner:
                return None                      # taken by someone else
            entry["owner"] = owned_by or owner
            if entry["score"] <= existing.get("score", 0):
                existing["owner"] = entry["owner"]   # keep their better score
            else:
                board.remove(existing)
                board.append(entry)
        else:
            entry["owner"] = owner
            board.append(entry)
        board.sort(key=lambda e: e.get("score", 0), reverse=True)
        board = board[:TOP_N]
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(board, f)
        os.replace(tmp, DB_FILE)        # atomic write
        return _public(board)


def _rate_ok(ip):
    now = time.time()
    with _lock:
        hits = [t for t in _rate.get(ip, []) if now - t < 60]
        if len(hits) >= RATE_PER_MIN:
            _rate[ip] = hits
            return False
        hits.append(now)
        _rate[ip] = hits
        return True


def _clean_name(name):
    name = "".join(c for c in str(name)[:12] if c.isalnum() or c == " ").strip()
    return name or "PLAYER"


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):                        # CORS preflight (belt-and-suspenders)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/leaderboard":
            self._json(200, {"leaderboard": _public(_load())})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/submit":
            return self._json(404, {"error": "not found"})
        # Behind nginx the socket IP is 127.0.0.1; use the real client from XFF.
        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        if not _rate_ok(ip):
            return self._json(429, {"error": "rate limited"})
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {"error": "bad size"})
        try:
            replay = json.loads(self.rfile.read(length))
        except ValueError:
            return self._json(400, {"error": "bad json"})

        if len(replay.get("steps") or []) > MAX_STEPS:
            return self._json(400, {"error": "replay too long"})

        ok, recomputed = hs.verify_replay(replay)
        if not ok:
            # Didn't reproduce a real run that ended in death -> reject.
            return self._json(403, {"ok": False, "error": "verification failed"})

        name = hs.sanitize_name(replay.get("name"))
        if hs.is_bad_name(name):
            return self._json(400, {"ok": False, "error": "name not allowed"})

        owner = hashlib.sha256(str(replay.get("token", "")).encode()).hexdigest()
        entry = {"name": name, "score": int(recomputed),
                 "round": int(replay.get("round", 0)),
                 "kills": int(replay.get("kills", 0)),
                 "time": int(replay.get("time", 0)),
                 "date": time.strftime("%Y-%m-%d")}
        board = _store(entry, owner)
        if board is None:
            return self._json(409, {"ok": False, "error": "name is taken by another player"})
        self._json(200, {"ok": True, "leaderboard": board})

    def log_message(self, *args):
        pass        # quiet


def main():
    host = os.environ.get("SWARMADA_HOST", "0.0.0.0")
    port = int(os.environ.get("SWARMADA_PORT", "8000"))
    print(f"Swarmada leaderboard server on {host}:{port}  (sim v{hs.SIM_VERSION})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
