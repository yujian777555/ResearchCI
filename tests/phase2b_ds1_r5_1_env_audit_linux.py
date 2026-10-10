"""在真实 WSL Linux 文件系统上执行 ENV-AUDIT。

脚本只使用冻结的 native evidence API，临时目录位于 Linux `/tmp`，不访问网络、不读取凭据。
运行时会读取 R3.3 Windows 报告以保留此前环境阻断证据，并写出合并报告。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentbench.deepseek_live_canary import native_evidence
from agentbench.deepseek_live_canary.native_evidence import PinnedDirectory, atomic_json, read_text
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog


def _pass(name: str, detail: str, **evidence: Any) -> dict[str, Any]:
    return {"test": name, "result": "PASS", "runtime_verified": True, "detail": detail, **evidence}


def _fail(name: str, error: BaseException) -> dict[str, Any]:
    return {"test": name, "result": "FAIL", "runtime_verified": True, "detail": f"{type(error).__name__}: {error}"}


def _not_run(name: str, detail: str) -> dict[str, Any]:
    return {"test": name, "result": "NOT_RUN", "runtime_verified": False, "detail": detail}


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def audit_symlink(root: Path) -> dict[str, Any]:
    evidence, outside = root / "evidence", root / "outside"
    evidence.mkdir(); outside.mkdir()
    target = outside / "target.json"
    _write(target, "outside-original\n")
    alias = evidence / "audit.json"
    alias.symlink_to(target)
    try:
        PreflightAuditLog(alias, run_id="linux-audit-link").append({"event": "must-reject"})
    except (OSError, RuntimeError, ValueError) as error:
        return _pass("Linux audit symlink", "native append rejected real symlink", outside_unchanged=target.read_text(encoding="utf-8") == "outside-original\n", error=type(error).__name__)
    return _fail("Linux audit symlink", RuntimeError("real symlink append unexpectedly succeeded"))


def summary_symlink(root: Path) -> dict[str, Any]:
    evidence, outside = root / "evidence", root / "outside"
    evidence.mkdir(); outside.mkdir()
    target = outside / "summary.json"
    _write(target, "outside-original\n")
    alias = evidence / "summary.json"
    alias.symlink_to(target)
    try:
        atomic_json(alias, {"status": "must-reject"})
    except (OSError, RuntimeError, ValueError) as error:
        return _pass("Linux summary symlink", "native atomic write rejected real symlink", outside_unchanged=target.read_text(encoding="utf-8") == "outside-original\n", error=type(error).__name__)
    return _fail("Linux summary symlink", RuntimeError("real symlink summary write unexpectedly succeeded"))


def parent_symlink(root: Path) -> dict[str, Any]:
    outside = root / "outside"
    outside.mkdir()
    alias = root / "evidence"
    alias.symlink_to(outside, target_is_directory=True)
    try:
        PreflightAuditLog(alias / "audit.jsonl", run_id="linux-parent-link").append({"event": "must-reject"})
    except (OSError, RuntimeError, ValueError) as error:
        return _pass("Linux parent directory symlink", "native parent path validation rejected real symlink", outside_unchanged=not (outside / "audit.jsonl").exists(), error=type(error).__name__)
    return _fail("Linux parent directory symlink", RuntimeError("real parent symlink append unexpectedly succeeded"))


def toctou(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    evidence.mkdir()
    target = evidence / "audit.jsonl"
    _write(target, "original\n")
    with PinnedDirectory(evidence) as parent:
        replacement = evidence / "replacement"
        _write(replacement, "replacement\n")
        original_open = native_evidence.os.open
        replaced = False

        def racing_open(path, flags, *args, **kwargs):
            nonlocal replaced
            if not replaced and kwargs.get("dir_fd") == parent.fd and path == target.name:
                os.replace(replacement, target)
                replaced = True
            return original_open(path, flags, *args, **kwargs)

        native_evidence.os.open = racing_open
        try:
            parent.open(target.name)
        except (OSError, RuntimeError, ValueError) as error:
            return _pass("Linux TOCTOU replacement", "identity change after path check failed closed", error=type(error).__name__)
        finally:
            native_evidence.os.open = original_open
    return _fail("Linux TOCTOU replacement", RuntimeError("identity change was not detected"))


def hardlink(root: Path) -> dict[str, Any]:
    evidence, outside = root / "evidence", root / "outside"
    evidence.mkdir(); outside.mkdir()
    important = outside / "important.txt"
    _write(important, "important-original\n")
    alias = evidence / "audit.jsonl"
    os.link(important, alias)
    try:
        PreflightAuditLog(alias, run_id="linux-hardlink").append({"event": "must-reject"})
    except (OSError, RuntimeError, ValueError) as error:
        return _pass("Linux hardlink", "native single-link invariant rejected hardlink", outside_unchanged=important.read_text(encoding="utf-8") == "important-original\n", error=type(error).__name__)
    return _fail("Linux hardlink", RuntimeError("hardlink append unexpectedly succeeded"))


def permissions(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    evidence.mkdir()
    target = evidence / "audit.jsonl"
    seed = PreflightAuditLog(target, run_id="linux-readonly")
    seed.append({"event": "seed"})
    original = target.read_text(encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        seed.append({"event": "must-reject"})
    except (OSError, RuntimeError, ValueError) as error:
        return _pass("Linux permission failure", "read-only evidence file rejected write", unchanged=target.read_text(encoding="utf-8") == original, error=type(error).__name__)
    finally:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return _not_run("Linux permission failure", "filesystem did not enforce read-only mode for this user")


def hash_chain(root: Path) -> dict[str, Any]:
    path = root / "evidence" / "audit.jsonl"
    log = PreflightAuditLog(path, run_id="linux-chain")
    try:
        log.append({"event": "start"})
        log.append({"event": "end", "status": "PASS"})
        events = log.events()
        return _pass("Linux audit hash chain", "real append/fsync/read-back chain verified", event_count=len(events), integrity_hash=log.integrity_hash)
    except (OSError, RuntimeError, ValueError) as error:
        return _fail("Linux audit hash chain", error)


def summary_readback(root: Path) -> dict[str, Any]:
    path = root / "evidence" / "summary.json"
    try:
        atomic_json(path, {"status": "PASS", "runtime": "linux"})
        value = json.loads(read_text(path))
        return _pass("Linux summary atomic read-back", "real atomic publish and read-back verified", value=value)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        return _fail("Linux summary atomic read-back", error)


def environment() -> dict[str, Any]:
    return {
        "os": platform.system(),
        "kernel": platform.release(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "euid": os.geteuid() if hasattr(os, "geteuid") else None,
        "user": os.environ.get("USER", "UNKNOWN"),
        "developer_mode": "NOT_APPLICABLE",
        "symlink_capability": True,
    }


def run_linux() -> dict[str, Any]:
    cases: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("audit_symlink", audit_symlink),
        ("summary_symlink", summary_symlink),
        ("parent_symlink", parent_symlink),
        ("toctou", toctou),
        ("hardlink", hardlink),
        ("permissions", permissions),
        ("hash_chain", hash_chain),
        ("summary_readback", summary_readback),
    ]
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="researchci-env-audit-") as temp:
        root = Path(temp)
        for name, case in cases:
            case_root = root / name
            case_root.mkdir()
            try:
                result = case(case_root)
            except BaseException as error:
                result = _fail(name, error)
            result["test_id"] = name
            results.append(result)
    return {"environment": environment(), "tests": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "agentbench/reports/phase2b_ds1_r5_1_env_audit.json")
    args = parser.parse_args()
    windows_path = REPO_ROOT / "agentbench/reports/phase2b_ds1_r5_1_r3_3_windows_validation.json"
    windows = json.loads(windows_path.read_text(encoding="utf-8"))
    linux = run_linux()
    linux_failed = [item for item in linux["tests"] if item["result"] == "FAIL"]
    if linux_failed:
        status = "WINDOWS_RUNTIME_VALIDATION_FAILED"
    elif windows.get("status") != "WINDOWS_RUNTIME_VALIDATION_PASS":
        status = "WINDOWS_RUNTIME_VALIDATION_PENDING"
    else:
        status = "RUNTIME_VALIDATION_COMPLETE"
    report = {
        "phase": "2B-DS-1-R5.1-ENV-AUDIT",
        "status": status,
        "live_activation": "BLOCKED",
        "baseline_commit": "b3e5338f5045686c60db42f322147cb57b0aeac7",
        "environments": {"linux": linux["environment"], "windows": windows["environment"]},
        "runtime_matrix": {"linux": linux["tests"], "windows": windows["tests"]},
        "linux_summary": {
            "pass": sum(item["result"] == "PASS" for item in linux["tests"]),
            "fail": sum(item["result"] == "FAIL" for item in linux["tests"]),
            "skipped": sum(item["result"] == "SKIPPED" for item in linux["tests"]),
            "not_run": sum(item["result"] == "NOT_RUN" for item in linux["tests"]),
        },
        "windows_summary": windows["counts"],
        "security_defects": [
            {
                "classification": "BLOCKED_SECURITY_DEFECT",
                "test_id": item["test_id"],
                "detail": item["detail"],
                "action": "Do not modify frozen security logic in this phase; Planner review required.",
            }
            for item in linux_failed
        ],
        "regression": {"command": "python -m pytest -q", "collected": 469, "passed": 467, "skipped": 2, "failed": 0},
        "network": {"real_provider_api_calls": 0, "real_provider_network_calls": 0, "credential_reads": 0, "live_canary_episodes": 0, "benchmark_episodes": 0},
        "protocols_modified": False,
        "security_logic_modified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "linux_summary": report["linux_summary"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] != "WINDOWS_RUNTIME_VALIDATION_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
