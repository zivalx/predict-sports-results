"""worldcup CLI.

Subcommands:
  refresh         Run a single pipeline refresh (analog of POSTing /refresh, but no server).
  export-static   Render the dashboard + JSON API to a directory (for CF Pages etc).
  serve           Convenience: launch uvicorn (for local dev).
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worldcup")
    subs = parser.add_subparsers(dest="command", required=True)

    p_refresh = subs.add_parser("refresh", help="Run one pipeline refresh and exit.")
    p_refresh.add_argument("--trigger", default="manual",
                           help="Snapshot trigger label (default: manual).")

    p_export = subs.add_parser("export-static",
                               help="Render dashboard + API to a directory.")
    p_export.add_argument("--output-dir", required=True, type=Path,
                          help="Destination directory (created if missing).")
    p_export.add_argument("--base-url", default="",
                          help="Base URL embedded in rendered links (e.g. https://worldcup.zivalx.com).")

    p_serve = subs.add_parser("serve", help="Run uvicorn locally.")
    p_serve.add_argument("--port", default=8765, type=int)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "refresh":
        return asyncio.run(_run_refresh(args.trigger))
    if args.command == "export-static":
        return asyncio.run(_run_export_static(args.output_dir, args.base_url))
    if args.command == "serve":
        return _run_serve(args.host, args.port, args.reload)
    return 1


async def _run_refresh(trigger: str) -> int:
    from worldcup.api.app import _default_clients
    from worldcup.jobs.refresh import run_refresh

    football, poly, gnews, reddit, claude = _default_clients()
    try:
        snap = await run_refresh(
            trigger=trigger,
            football_client=football,
            poly_collector=poly,
            gnews_collector=gnews,
            reddit_collector=reddit,
            claude_client=claude,
            as_of=datetime.now(timezone.utc),
        )
        print(f"refresh ok — snapshot_id={snap.id}")
        return 0
    finally:
        if hasattr(football, "aclose"):
            await football.aclose()


async def _run_export_static(output_dir: Path, base_url: str) -> int:
    from worldcup.render.static_export import export_static
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = await export_static(output_dir=output_dir, base_url=base_url)
    print(f"export ok — {summary}")
    return 0


def _run_serve(host: str, port: int, reload: bool) -> int:
    import uvicorn
    uvicorn.run("worldcup.api.app:app", host=host, port=port, reload=reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
