from __future__ import annotations

import argparse
from pathlib import Path

from .data_pipeline import normalize_and_build
from .data_source import TushareFuturesSource
from .reports import write_engine_report
from .settings import Settings
from .workflow import run_research


DEFAULT_CONFIG = "configs/five_sector_momentum.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fsm")
    subparsers = parser.add_subparsers(dest="group", required=True)

    data = subparsers.add_parser("data")
    data_sub = data.add_subparsers(dest="action", required=True)
    download = data_sub.add_parser("download")
    download.add_argument("--config", default=DEFAULT_CONFIG)
    download.add_argument("--skip-settlements", action="store_true")
    download.add_argument("--skip-limits", action="store_true")
    build = data_sub.add_parser("build")
    build.add_argument("--config", default=DEFAULT_CONFIG)
    repair = data_sub.add_parser("repair")
    repair.add_argument("--config", default=DEFAULT_CONFIG)

    backtest = subparsers.add_parser("backtest")
    backtest_sub = backtest.add_subparsers(dest="action", required=True)
    run = backtest_sub.add_parser("run")
    run.add_argument("--config", default=DEFAULT_CONFIG)
    run.add_argument("--rebuild-data", action="store_true")

    report = subparsers.add_parser("report")
    report_sub = report.add_subparsers(dest="action", required=True)
    engine = report_sub.add_parser("engine")
    engine.add_argument("--config", default=DEFAULT_CONFIG)
    engine.add_argument("--output", default="docs/BACKTEST_ENGINE_REPORT.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load(args.config)
    if args.group == "data" and args.action == "download":
        result = TushareFuturesSource(settings).download(
            include_settlements=not args.skip_settlements,
            include_limits=not args.skip_limits,
        )
        print(f"Downloaded {len(result.bars):,} bars; warnings={len(result.manifest['warnings'])}")
        return 0
    if args.group == "data" and args.action == "build":
        result = normalize_and_build(settings)
        print(f"Built {len(result.adjusted_prices):,} adjusted-price rows")
        return 0
    if args.group == "data" and args.action == "repair":
        result = TushareFuturesSource(settings).repair_missing_bars()
        print(result)
        return 0
    if args.group == "backtest" and args.action == "run":
        if settings.raw.get("version") == "v3":
            if args.rebuild_data:
                raise ValueError("v3 reuses the frozen v2 normalized data; do not use --rebuild-data")
            from .workflow_v3 import run_v3_research

            output = run_v3_research(settings)
        else:
            output = run_research(settings, rebuild_data=args.rebuild_data)
        print(output)
        return 0
    if args.group == "report" and args.action == "engine":
        output = write_engine_report(settings, args.output)
        print(output)
        return 0
    raise RuntimeError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
