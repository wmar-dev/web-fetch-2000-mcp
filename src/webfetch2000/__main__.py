"""Entry point: run the MCP server over stdio with graceful shutdown."""

from __future__ import annotations

import os
import signal
import sys

import anyio

from .config import ConfigError, load_settings
from .logging import configure, get_logger
from .server import create_server


async def _run() -> None:
    try:
        loaded = load_settings()
    except ConfigError as e:
        print(f"web-fetch-2000: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    configure(loaded.settings.log_level)
    log = get_logger("main")
    mcp = create_server(loaded.settings, loaded=loaded)
    holder = mcp._holder  # type: ignore[attr-defined]

    async def graceful_exit(sig: int) -> None:
        # The stdio reader blocks in a worker thread that cannot be cancelled, so close
        # browsers and the store explicitly, then leave the process immediately.
        log.info("shutdown requested", extra={"signal": sig})
        app = holder.app
        if app is not None:
            with anyio.CancelScope(shield=True):
                await app.close()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    async with anyio.create_task_group() as tg:

        async def watch_signals() -> None:
            with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as sigs:
                async for sig in sigs:
                    await graceful_exit(int(sig))

        tg.start_soon(watch_signals)
        await mcp.run_stdio_async()  # returns (and the lifespan closes everything) on stdin EOF
        tg.cancel_scope.cancel()


def main() -> None:
    try:
        anyio.run(_run)
    except KeyboardInterrupt:  # pragma: no cover - SIGINT handled in _run
        pass


if __name__ == "__main__":
    main()
