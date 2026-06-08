"""
Web/desktop entry point.

pygbag (the WebAssembly packager) looks for `main.py` and runs it as an async
program in the browser. The real game lives in swarmada.py; this just
launches its async main loop. Works on desktop too: `python main.py`.
"""

import asyncio

from swarmada import main

asyncio.run(main())
