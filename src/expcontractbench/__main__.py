from __future__ import annotations

import argparse
import json
from pathlib import Path

from .generator import generate_benchmark
from .metrics import compute_metrics
from .phase1e import evaluate_dev_matrix, prelock_check, run_locked_matrix
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
    pre = sub.add_parser("phase1e-prelock")
    pre.add_argument("--repo-root", type=Path, required=True)
    pre.add_argument("--root", type=Path, required=True)
    pre.add_argument("--evaluator-sha", required=True)
    locked = sub.add_parser("phase1e-locked")
    locked.add_argument("--repo-root", type=Path, required=True)
    locked.add_argument("--root", type=Path, required=True)
    locked.add_argument("--evaluator-sha", required=True)
    locked.add_argument("--run-id", required=True)
    locked.add_argument("--locked", action="store_true", help="显式确认执行唯一正式 locked matrix")
    args = parser.parse_args()
    if args.command == "generate":
        print(generate_benchmark(args.output))
    elif args.command == "validate":
        print(json.dumps(validate_benchmark(args.root), ensure_ascii=False, sort_keys=True, indent=2))
    elif args.command == "evaluate-dev":
        validate_benchmark(args.root)
        reports = evaluate_dev_matrix(args.root, output_dir=args.root / "reports")
        for name, report in reports.items():
            print(json.dumps({"adapter": name, "metrics": report["metrics"], "repair": report["repair"]}, ensure_ascii=False, sort_keys=True))
    elif args.command == "phase1e-prelock":
        print(json.dumps(prelock_check(args.repo_root, args.root, args.evaluator_sha), ensure_ascii=False, sort_keys=True, indent=2))
    else:
        if not args.locked:
            parser.error("phase1e-locked 必须显式提供 --locked；默认不会运行 locked split")
        print(json.dumps(run_locked_matrix(args.repo_root, args.root, args.evaluator_sha, args.run_id, locked=True), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
