from pathlib import Path

import yaml

from five_sector_momentum.v6.registry import load_registry, resolved_config, validate_resolved_config


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    registry_path = root / "docs/v6_20260905_research_and_test_plan/V6_MACHINE_REGISTRY.yaml"
    registry = load_registry(registry_path)
    config = resolved_config(registry, registry_path)
    target = root / "configs/five_sector_momentum_v6.yaml"
    target.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    validate_resolved_config(yaml.safe_load(target.read_text(encoding="utf-8")), registry)


if __name__ == "__main__":
    main()

