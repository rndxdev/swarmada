"""
Web/desktop entry point.

pygbag (the WebAssembly packager) looks for `main.py` and runs it as an async
program in the browser. The real game lives in swarmada.py; this launches its
async main loop — and if anything fails at startup, it paints the traceback
onto the canvas (browsers hide Python errors, so this makes them visible).

Works on desktop too: `python main.py`.
"""

import asyncio
import traceback


async def _run():
    try:
        from swarmada import main
        await main()
    except Exception:
        err = traceback.format_exc()
        print(err)
        try:
            import pygame
            pygame.init()
            scr = pygame.display.get_surface() or pygame.display.set_mode((960, 600))
            scr.fill((25, 12, 14))
            font = pygame.font.SysFont("monospace", 13)
            y = 12
            for line in err.replace("\t", "  ").splitlines()[-32:]:
                scr.blit(font.render(line[:118], True, (255, 170, 170)), (10, y))
                y += 16
            pygame.display.flip()
        except Exception:
            pass
        while True:
            await asyncio.sleep(0.3)


asyncio.run(_run())
