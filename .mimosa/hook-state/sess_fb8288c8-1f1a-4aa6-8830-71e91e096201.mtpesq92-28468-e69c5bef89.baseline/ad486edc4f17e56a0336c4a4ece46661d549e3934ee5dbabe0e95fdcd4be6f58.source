from __future__ import annotations

import argparse
from pathlib import Path

from five_sector_momentum.settings import Settings
from five_sector_momentum.workflow_v4_1 import run_v4_1


def main() -> None:
    parser=argparse.ArgumentParser(description="运行锁定的五板块动量v4.1研究")
    parser.add_argument("--config",default="configs/five_sector_momentum_v4_1.yaml")
    parser.add_argument("--resume",default=None,help="仅用于从同一v4.1失败审计目录继续；已保存场景不会重跑")
    args=parser.parse_args()
    root=run_v4_1(Settings.load(Path(args.config).resolve()),Path(args.resume) if args.resume else None)
    print(f"v4.1 complete: {root}",flush=True)


if __name__=="__main__":
    main()
