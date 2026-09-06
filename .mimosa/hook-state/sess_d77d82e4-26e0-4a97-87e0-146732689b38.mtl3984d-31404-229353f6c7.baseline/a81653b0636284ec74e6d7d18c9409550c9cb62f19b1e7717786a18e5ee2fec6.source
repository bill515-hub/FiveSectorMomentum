from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from five_sector_momentum.analytics_v4_1 import bootstrap_summaries
from five_sector_momentum.data_pipeline import load_bundle
from five_sector_momentum.engine_v4_1 import COST_SPECS
from five_sector_momentum.reports_v4_1 import write_reports_v4_1
from five_sector_momentum.settings import Settings
from five_sector_momentum.workflow_v4_1 import (
    V4_DIRS, _both, _load_result, _sleeve_netting, _tests,
    _version_comparison,
)


def main() -> None:
    parser=argparse.ArgumentParser(description="只重建v4.1分析表和报告，不运行交易引擎")
    parser.add_argument("root")
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    root=(project/args.root).resolve() if not Path(args.root).is_absolute() else Path(args.root).resolve()
    if root.parent != (project/"outputs").resolve() or not root.name.startswith("v4_1_"):
        raise ValueError("root must be a v4.1 output directory")
    settings=Settings.load(project/"configs/five_sector_momentum_v4_1.yaml")
    _tests(project,root)

    sleeves={}
    sleeve_dirs=sorted(root.glob("04_corrected_sleeve__*")) or sorted(root.glob("03_sleeve__*"))
    for directory in sleeve_dirs:
        label=directory.name.split("__",1)[1]
        sleeves[label]=_load_result(directory)
    internal=pd.read_pickle(root/"sleeve_internal_targets_v4_1.pkl")
    data=load_bundle(settings)
    _both(_sleeve_netting(internal,sleeves,data.bars),root/"sleeve_netting_v4_1")

    source=project/settings.section("v4_1_research")["source_v4_output"]
    source_results={label:_load_result(source/path) for label,path in V4_DIRS.items()}
    _both(_version_comparison(project,source_results,sleeves,settings),root/"v3_v4_v4_1_comparison")

    draws=pd.read_pickle(root/"bootstrap_strategy_draws_v4_1.pkl")
    ranks=pd.read_pickle(root/"bootstrap_ranks_full_v4_1.pkl")
    summary,paired,paired_summary,stability,mean_winner=bootstrap_summaries(draws,ranks)
    _both(summary,root/"bootstrap_strategy_summary_v4_1"); _both(paired,root/"bootstrap_paired_differences_v4_1")
    _both(paired_summary,root/"bootstrap_paired_summary_v4_1"); _both(stability,root/"bootstrap_rank_stability_v4_1"); _both(mean_winner,root/"bootstrap_mean_winner_v4_1")

    matrix=pd.read_pickle(root/"cost_response_matrix_v4_1.pkl")
    unique=matrix.drop_duplicates(["strategy","cost_code"])
    registry=[]
    for label in ["reference_v3_252","single_180_skip5","multi_all_raw","multi_fast_scaled"]:
        registry.append({"stage":"reproduction_gate","identity":f"gate_{label}","strategy":label,"cost_code":"C3","engine_run":True,"source_kind":"v4_1_run","source_path":str(root/f'00_gate__gate_{label}')})
    for label in V4_DIRS:
        if label!="reference_v3_252": registry.append({"stage":"same_path_addback","identity":label,"strategy":label,"cost_code":None,"engine_run":False,"source_kind":"v4_frozen_path","source_path":str(source/V4_DIRS[label])})
    for _,row in unique.iterrows():
        registry.append({"stage":"cost_counterfactual","identity":f"{row.strategy}_{row.cost_code}","strategy":row.strategy,"cost_code":row.cost_code,"engine_run":row.source_kind=="new","source_kind":row.source_kind,"source_path":row.source_path})
    corrected=bool(list(root.glob("04_corrected_sleeve__*")))
    if corrected:
        for directory in sorted(root.glob("03_sleeve__*")):
            label=directory.name.split("__",1)[1]
            registry.append({"stage":"invalidated_initial_sleeve","identity":f"invalidated_{label}","strategy":label,"cost_code":"C7" if "fixed_3tick" in label else "C3","engine_run":True,"source_kind":"v4_1_invalidated_run","source_path":str(directory)})
    for label in sleeves:
        prefix="04_corrected_sleeve" if corrected else "03_sleeve"
        registry.append({"stage":"corrected_strategy_sleeve" if corrected else "strategy_sleeve","identity":label,"strategy":label,"cost_code":"C7" if "fixed_3tick" in label else "C3","engine_run":True,"source_kind":"v4_1_corrected_run" if corrected else "v4_1_run","source_path":str(root/f'{prefix}__{label}')})
    registry=pd.DataFrame(registry); _both(registry,root/"scenario_registry_v4_1")
    params=[]
    for code,spec in COST_SPECS.items(): params.append({"cost_code":code,**vars(spec)})
    _both(pd.DataFrame(params),root/"scenario_parameters_v4_1")

    bars=data.bars.dropna(subset=["open","tick_size"]).copy(); ratio=bars.open/bars.tick_size; bad=(ratio-np.round(ratio)).abs()>1e-7
    anomalies=bars.loc[bad,["date","ts_code","instrument","open","tick_size"]].copy(); anomalies["issue"]="开盘价不在当前元数据tick网格"; anomalies["used_action"]="不修改历史缓存；C0实际成交必须通过零记录滑点断言"; _both(anomalies,root/"data_quality_anomalies_v4_1")
    limitations=pd.DataFrame([
        {"category":"手续费","status":"继承v3历史表，部分日期为明确proxy","conclusion_limit":"不能还原每家期货公司真实账单"},
        {"category":"滑点","status":"固定tick、换月tick、参与率冲击均为代理","conclusion_limit":"不能描述为逐笔真实成交成本"},
        {"category":"日线执行","status":"无盘口、排队、夜盘内路径和集合竞价细节","conclusion_limit":"不能验证极端流动性容量"},
        {"category":"验证期","status":"2022—2026已被v4用于候选比较","conclusion_limit":"不是干净未触碰样本外"},
        {"category":"2026年度","status":"仅截至2026-08-31","conclusion_limit":"不得与完整自然年直接比较"},
        {"category":"Bootstrap","status":"20日移动区块、21策略探索性多重比较","conclusion_limit":"不能创造新市场状态或证明未来显著优胜"},
    ]); _both(limitations,root/"limitations_v4_1")
    coverage=pd.read_csv(source/"fee_rule_coverage.csv") if (source/"fee_rule_coverage.csv").exists() else pd.DataFrame()
    if not coverage.empty: _both(coverage,root/"inherited_fee_rule_coverage_v4_1")
    modified=pd.DataFrame({"path":["configs/five_sector_momentum_v4_1.yaml","V4_1_EXPERIMENT_REGISTRY.md","src/five_sector_momentum/engine_v4_1.py","src/five_sector_momentum/analytics_v4_1.py","src/five_sector_momentum/workflow_v4_1.py","src/five_sector_momentum/reports_v4_1.py","tests/test_v4_1.py","scripts/run_v4_1.py","scripts/finalize_v4_1_outputs.py","scripts/correct_v4_1_sleeves.py"],"change_type":"v4.1新增或仅v4.1修订"}); _both(modified,root/"modified_files_v4_1")
    protected=[]
    for p in [project/"configs/five_sector_momentum_v4.yaml",project/"V4_EXPERIMENT_REGISTRY.md",project/"src/five_sector_momentum/engine_v4.py",project/"src/five_sector_momentum/workflow_v4.py",project/"outputs/v3_20260902_001129/manifest.json",project/"outputs/v4_20260902_102628/manifest.json"]:
        protected.append({"path":str(p.relative_to(project)),"last_write_time":pd.Timestamp(p.stat().st_mtime,unit="s"),"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"audit_note":"只读；时间戳早于v4.1注册与运行"})
    _both(pd.DataFrame(protected),root/"protected_artifact_audit_v4_1")

    write_reports_v4_1(settings,root)
    pairs=[]
    for p in root.rglob("*.pkl"): pairs.append({"pickle":str(p.relative_to(root)),"csv":str(p.with_suffix('.csv').relative_to(root)),"paired":p.with_suffix('.csv').exists()})
    _both(pd.DataFrame(pairs),root/"pickle_csv_traceability_v4_1")
    inventory=[]
    for p in sorted(root.rglob("*")):
        if p.is_file(): inventory.append({"relative_path":str(p.relative_to(root)),"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    _both(pd.DataFrame(inventory),root/"file_inventory_v4_1")
    print(f"v4.1 analytical outputs finalized without engine runs: {root}")


if __name__=="__main__":
    main()
