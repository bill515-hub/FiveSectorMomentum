from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="为v3底层pickle生成同名可审阅CSV")
    parser.add_argument("run_root", help="完整v3运行目录")
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    if not (root / "manifest.json").exists():
        raise FileNotFoundError(f"不是已完成的v3运行目录: {root}")

    rows: list[dict[str, object]] = []
    for source in sorted(root.rglob("*.pkl")):
        target = source.with_suffix(".csv")
        frame = pd.read_pickle(source)
        if not isinstance(frame, pd.DataFrame):
            rows.append({
                "pickle": str(source.relative_to(root)), "csv": "",
                "rows": None, "columns": None, "status": "非DataFrame，保留pickle",
            })
            continue
        if not target.exists():
            frame.to_csv(target, index=False, encoding="utf-8-sig")
        rows.append({
            "pickle": str(source.relative_to(root)),
            "csv": str(target.relative_to(root)),
            "rows": len(frame), "columns": len(frame.columns), "status": "已配对",
        })
    audit = pd.DataFrame(rows)
    audit.to_csv(root / "pickle_csv_traceability_v3.csv", index=False, encoding="utf-8-sig")
    audit.to_pickle(root / "pickle_csv_traceability_v3.pkl")
    print(f"paired={audit['status'].eq('已配对').sum()} files; root={root}")


if __name__ == "__main__":
    main()
