# Horde Survival

A tiny space-themed Vampire-Survivors-style game in pygame. Procedural bitmap
art and synthesized audio (no third-party assets → copyright-safe), an endless
scrolling world, silent escalating waves, bosses (including the mega **OMEGA**),
upgrades, and a **replay-verified** global leaderboard.

## Play
```bash
./.venv/bin/python horde_survival.py
```
**Controls:** WASD/arrows move · 1/2/3 pick upgrade · P pause (autosaves) ·
M music · R restart · Esc pause/quit.

Assets auto-generate on first run. To regenerate the art:
```bash
./.venv/bin/python make_assets.py
```

## Files
- `horde_survival.py` — the game (deterministic, fixed-timestep sim).
- `make_assets.py` — generates `assets/*.png` pixel-art.
- `leaderboard_server.py` — replay-verifying global leaderboard server.
- `assets/` — generated sprites. `scores.json` / `savegame.json` are created at runtime.

## Global leaderboard (replay-verified)

A client can't be made unspoofable, so the score is **never trusted** — the
game records the RNG seed + your inputs each tick, and the server **re-runs the
exact simulation** to recompute the score. A forged number won't reproduce and
is rejected.

### Run the server on your VPS
```bash
pip install pygame                      # only dependency (no display needed)
python leaderboard_server.py            # listens on 0.0.0.0:8000
# optional: HORDE_HOST / HORDE_PORT env vars
```
Keep the server's `horde_survival.py` **identical** to the players' copy — the
simulation and `SIM_VERSION` must match or valid replays get rejected. Bump
`SIM_VERSION` whenever gameplay math changes (old replays then stop validating).

Run it persistently (example systemd unit):
```ini
[Unit]
Description=Horde leaderboard
After=network.target
[Service]
WorkingDirectory=/opt/horde
ExecStart=/usr/bin/python3 leaderboard_server.py
Restart=always
Environment=HORDE_PORT=8000
[Install]
WantedBy=multi-user.target
```
Put it behind nginx/caddy for TLS if you want `https://`.

### Point the game at it
```bash
HORDE_SERVER=http://YOUR_VPS_IP:8000 ./.venv/bin/python horde_survival.py
```
On death the run is submitted; the leaderboard screen then shows the verified
**global** board. Without `HORDE_SERVER` set, it just uses the local board.

### Endpoints
- `POST /submit` — body is a replay JSON; verifies + stores; returns `{ok, leaderboard}`.
- `GET /leaderboard` — top scores.

Built-in safeguards: per-IP rate limit, body-size cap, max replay length, atomic
DB writes, version pinning.

### Honest caveat
Verification re-simulates with floating-point math. On the **same** CPython it's
exact; across very different platforms a rare last-bit difference could cause a
false rejection. Running the server on a typical Linux VPS and playing on
Mac/Windows is fine in practice; if you ever see valid runs rejected, run the
verifier on the same OS/Python as players.
