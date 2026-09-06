from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


SOURCES = [
    {
        "机构": "Tushare", "核查状态": "成功：逐真实合约查询823个映射合约",
        "链接": "https://tushare.pro/document/2?doc_id=141",
        "覆盖/用途": "fut_settle逐日手续费与合约参数；历史规则主数据",
        "限制": "平今字段多数为空；缺日必须标代理",
    },
    {
        "机构": "中国金融期货交易所", "核查状态": "成功：官方收费表",
        "链接": "https://www.cffex.com.cn/cn/zjssf/20240701/39212.html",
        "覆盖/用途": "核对10年期国债T按手收费及平今标准",
        "限制": "单一公告不能证明整个历史区间未变更",
    },
    {
        "机构": "上海期货交易所", "核查状态": "成功：历史调整公告",
        "链接": "https://www.shfe.com.cn/publicnotice/notice/202405/t20240529_801782.html",
        "覆盖/用途": "核对螺纹钢RB成交金额费率及生效时点表达",
        "限制": "早期AL/RB/RU逐日覆盖不足仍标代理",
    },
    {
        "机构": "上海国际能源交易中心", "核查状态": "成功：官方原油手续费公告",
        "链接": "https://www.ine.cn/publicnotice/notice/202606/t20260623_832254.html",
        "覆盖/用途": "核对SC按手收费和平今免收的当前标准",
        "限制": "向更早历史回填平今免收时明确标记最新官方标准代理",
    },
    {
        "机构": "郑州商品交易所", "核查状态": "成功：历史手续费公告",
        "链接": "https://www.czce.com.cn/cn/rootfiles/2018/06/22/1531035551736278-1531035551769551.pdf",
        "覆盖/用途": "核对FG平今可与普通交易费不同，规则必须区分交易类型和生效日",
        "限制": "公告只覆盖指定品种与时点，不能替代完整历史表",
    },
    {
        "机构": "郑州商品交易所", "核查状态": "成功：历史综合调整通知",
        "链接": "https://www.czce.com.cn/cn/rootfiles/2012/04/27/1330429089396685-1330429089398398.pdf",
        "覆盖/用途": "核对MA、CF、SR等按品种调整的历史制度",
        "限制": "早于本回测且仅作制度交叉核查，不据此外推2015年后费率",
    },
    {
        "机构": "大连商品交易所", "核查状态": "官网及历史公告检索已执行；自动访问超时/结果不完整",
        "链接": "https://www.dce.com.cn/",
        "覆盖/用途": "未用无法验证的网页值覆盖Tushare逐合约历史行",
        "限制": "DCE缺失日继续使用明确标记的品种最新标准代理；不得声称完整复原",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成v3官方来源核查清单")
    parser.add_argument("run_root")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    run_root = Path(args.run_root).resolve()
    frame = pd.DataFrame(SOURCES)
    for root, stem in [
        (project / "data" / "v3" / "fees", "official_source_inventory"),
        (run_root, "official_source_inventory_v3"),
    ]:
        root.mkdir(parents=True, exist_ok=True)
        frame.to_csv(root / f"{stem}.csv", index=False, encoding="utf-8-sig")
        frame.to_pickle(root / f"{stem}.pkl")
    print(f"sources={len(frame)}")


if __name__ == "__main__":
    main()
