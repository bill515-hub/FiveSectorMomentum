"""Preserve the initial field-classification review before re-evaluation."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'outputs/v4_2_20260903_091241'
target=root/'gate_field_classification_attempt_01'
target.mkdir(exist_ok=False)
for stem in ['reproduction_and_repair_gate_v4_2','calendar_repair_differences_v4_2']:
    for ext in ['csv','pkl']:
        source=root/f'{stem}.{ext}';(target/source.name).write_bytes(source.read_bytes())
(target/'README.md').write_text('# 首次字段分类核验保留\n\n没有现金/持仓/成交/费用差异超出容差。比较器最初把daily_equity中的pending_orders和diversification_multiplier视作实际账户字段，导致拒绝。两者实际是末日待执行目标的调度/风险诊断，符合授权修复的末端目标变化解释。保留首次全部差异，不删行，不改变金额容差，不重跑G1；修正分类后重新对已保存的同一结果核验。\n',encoding='utf-8')
