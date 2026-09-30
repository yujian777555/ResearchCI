from __future__ import annotations

import argparse
import json
from pathlib import Path

from .generator import generate_benchmark
from .metrics import compute_metrics
from .runner import NoCheckAdapter, RuntimeResearchCIAdapter, evaluate_split
from .validator import validate_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(prog="expcontractbench")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--output", type=Path, required=True)
    val = sub.add_parser("validate")
    val.add_argument("--root", type=Path, required=True)
    ev = sub.add_parser("evaluate-dev")
    ev.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        print(generate_benchmark(args.output))
    elif args.command == "validate":
        print(json.dumps(validate_benchmark(args.root), ensure_ascii=False, sort_keys=True, indent=2))
    else:
        validate_benchmark(args.root)
        for adapter in (RuntimeResearchCIAdapter(), NoCheckAdapter()):
            predictions, truth = evaluate_split(args.root, "dev", adapter)
            report = {
                "split": "dev",
                "adapter": adapter.name,
                "metrics": compute_metrics(predictions, truth),
                "predictions": predictions,
            }
            report_path = args.root / "reports" / f"dev_{adapter.name}.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report["metrics"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
