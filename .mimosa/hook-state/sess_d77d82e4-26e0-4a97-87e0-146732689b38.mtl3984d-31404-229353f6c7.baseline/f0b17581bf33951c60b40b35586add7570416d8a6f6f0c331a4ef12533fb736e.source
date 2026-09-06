from __future__ import annotations

import argparse
from pathlib import Path

from five_sector_momentum.settings import Settings
from five_sector_momentum.workflow_v4 import run_v4_research


def main() -> None:
    parser = argparse.ArgumentParser(description="运行预注册的五板块动量 v4 周期研究")
    parser.add_argument(
        "--config", default="configs/five_sector_momentum_v4.yaml",
        help="v4 配置文件；不得传入 v2/v3 配置",
    )
    args = parser.parse_args()
    root = run_v4_research(Settings.load(Path(args.config).resolve()))
    print(f"v4 complete: {root}", flush=True)


if __name__ == "__main__":
    main()
