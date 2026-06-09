# Swarmada

A tiny **alien-swarm survival** game in pygame: you're the last Vanguard pilot
holding the line against an endless alien Tide. Procedural bitmap art and
synthesized audio (no third-party assets → copyright-safe), an endless scrolling
world, silent escalating waves, bosses (including the mega **OMEGA**), upgrades,
and a **replay-verified** global leaderboard.

## Play (desktop — Windows / Mac / Linux)
```bash
pip install -r requirements.txt
python swarmada.py        # or: python main.py
```

## Play in a browser (share a link — any OS, no install)
The game also compiles to WebAssembly with [pygbag], so anyone can play it from
a URL on any computer — no Python, no download.

```bash
pip install pygbag
./build_web.sh                  # output -> build/web/
```
Then host the **contents of `build/web/`** anywhere static:
- **itch.io** (easiest link): zip the files inside `build/web/`, create a new
  project, set "Kind of project = HTML", upload the zip, tick "play in browser",
  and set the viewport to **960 x 600**. Share the page URL.
- **GitHub Pages**: copy `build/web/` into a `docs/` folder (or a `gh-pages`
  branch), enable Pages, and share the published URL.

Test it locally first: `python -m pygbag main.py` then open http://localhost:8000.

Notes for the web version: the local leaderboard and autosave/resume persist via
the browser's localStorage (survive reloads). The global leaderboard isn't
submitted from the browser sandbox (no-ops safely); audio falls back to silent if
the browser can't synthesize it. The core game plays fully. It runs a bit slower
than native, especially in late waves.

[pygbag]: https://github.com/pygame-web/pygbag

## Photosensitivity warning
This game contains flashing lights and rapid visual effects. A small percentage
of people may experience seizures when exposed to flashing lights or patterns.
If you or anyone in your family has an epileptic condition, consult a doctor
before playing. The game shows this warning at startup.

## Credits & license
- Built with **[pygame](https://www.pygame.org/)** (LGPL) on **SDL2** (zlib). pygame
  is dynamically imported (not modified or statically bundled), so the game can be
  licensed freely; attribution is given here and on the title screen.
- All sprites (`make_assets.py`) and sound/music (synthesized at runtime) are
  original to this project — no third-party art or audio assets.
- Web export by **[pygbag](https://github.com/pygame-web/pygbag)**.
**Controls:** WASD/arrows move · 1/2/3 pick upgrade · P pause (autosaves) ·
M music · R restart · Esc pause/quit.

Assets auto-generate on first run. To regenerate the art:
```bash
./.venv/bin/python make_assets.py
```

## Files
- `swarmada.py` — the game (deterministic, fixed-timestep sim).
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
# optional: SWARMADA_HOST / SWARMADA_PORT env vars
```
Keep the server's `swarmada.py` **identical** to the players' copy — the
simulation and `SIM_VERSION` must match or valid replays get rejected. Bump
`SIM_VERSION` whenever gameplay math changes (old replays then stop validating).

Run it persistently (example systemd unit):
```ini
[Unit]
Description=Swarmada leaderboard
After=network.target
[Service]
WorkingDirectory=/opt/swarmada
ExecStart=/usr/bin/python3 leaderboard_server.py
Restart=always
Environment=SWARMADA_PORT=8000
[Install]
WantedBy=multi-user.target
```
Put it behind nginx/caddy for TLS if you want `https://`.

### Point the game at it
```bash
SWARMADA_SERVER=http://YOUR_VPS_IP:8000 ./.venv/bin/python swarmada.py
```
On death the run is submitted; the leaderboard screen then shows the verified
**global** board. Without `SWARMADA_SERVER` set, it just uses the local board.

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
