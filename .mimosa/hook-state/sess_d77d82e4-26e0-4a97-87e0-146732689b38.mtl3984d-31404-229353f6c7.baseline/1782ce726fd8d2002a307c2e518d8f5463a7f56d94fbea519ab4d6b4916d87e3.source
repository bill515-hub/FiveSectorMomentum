from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="运行并保存v3完整测试日志")
    parser.add_argument("--output", required=True, help="test_results_v3.txt输出路径")
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(project / "src"), str(project / "tests")]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=project,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")
    print(output, end="")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
