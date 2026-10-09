"""Opt-in live benchmark for SC-001 to SC-003 (not part of the automated suite or CI).

Usage:
    uv run python tests/benchmark/run_benchmark.py [--urls tests/benchmark/urls.json]
        [--out specs/001-multi-strategy-web-fetch/benchmark.md] [--rounds 3]

It runs the real server stack against live sites using a throwaway store, then reports:
  SC-001  share of fetchable pages that returned usable content with strategy=auto
  SC-002  share of warmed-up fetches whose first attempted strategy succeeded
  SC-003  speed-up of repeat fetches for sites that needed a heavier strategy
Live sites change, so treat the numbers as a snapshot and review failures by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path
from statistics import mean

from webfetch2000.config import Settings
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.server import build_app


async def run(urls: list[dict], rounds: int) -> list[dict]:
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        app = build_app(Settings(data_dir=tmp, timeout_s=60))
        try:
            for r in range(rounds):
                for item in urls:
                    t0 = time.monotonic()
                    try:
                        res = await app.router.fetch(FetchRequest(url=item["url"], cache="bypass"))
                        row = {
                            "round": r + 1,
                            **item,
                            "ok": True,
                            "strategy": res.strategy_used,
                            "first_try": res.attempts[0].outcome == "success"
                            if res.attempts
                            else True,
                            "attempts": [a.strategy for a in res.attempts],
                        }
                    except FetchError as e:
                        row = {
                            "round": r + 1,
                            **item,
                            "ok": False,
                            "error": e.code,
                            "attempts": [a.strategy for a in e.attempts],
                            "first_try": False,
                            "strategy": None,
                        }
                    row["seconds"] = round(time.monotonic() - t0, 2)
                    rows.append(row)
                    print(
                        f"round {r + 1} {item['url']}: {row['ok']} {row['strategy']} {row['seconds']}s"
                    )
        finally:
            await app.close()
    return rows


def report(rows: list[dict], rounds: int) -> str:
    required = [r for r in rows if not r.get("optional")]
    first = [r for r in required if r["round"] == 1]
    sc1 = mean(r["ok"] for r in first) if first else 0.0
    warm = [r for r in required if r["round"] >= 3 and r["ok"]] if rounds >= 3 else []
    sc2 = mean(r["first_try"] for r in warm) if warm else float("nan")

    speedups = []
    for url in {r["url"] for r in required}:
        mine = sorted(
            (r for r in required if r["url"] == url and r["ok"]), key=lambda r: r["round"]
        )
        if len(mine) >= 3 and mine[0]["strategy"] != "http":
            speedups.append(1 - mine[-1]["seconds"] / max(mine[0]["seconds"], 0.01))
    sc3 = mean(speedups) if speedups else float("nan")

    lines = [
        "# Live benchmark snapshot",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} with {rounds} rounds per URL.",
        "",
        f"- **SC-001** usable content on first visit: {sc1:.0%} (target >= 90%)",
        f"- **SC-002** first strategy succeeded after warm-up: {sc2:.0%} (target >= 90%)",
        f"- **SC-003** repeat-fetch speed-up for sites needing a heavier strategy: {sc3:.0%} "
        "(target >= 50%)",
        "",
        "| round | url | kind | ok | strategy | attempts | seconds |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['round']} | {r['url']} | {r['kind']}{' (optional)' if r.get('optional') else ''} "
            f"| {r['ok']} | {r['strategy'] or r.get('error')} | {' > '.join(r['attempts'])} "
            f"| {r['seconds']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", default=str(here / "urls.json"))
    ap.add_argument("--out", default="specs/001-multi-strategy-web-fetch/benchmark.md")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    urls = json.loads(Path(args.urls).read_text())
    rows = asyncio.run(run(urls, args.rounds))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(rows, args.rounds))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
