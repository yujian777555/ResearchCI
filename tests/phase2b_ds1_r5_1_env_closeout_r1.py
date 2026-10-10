"""Phase 2B-DS-1-R5.1-ENV-CLOSEOUT-R1 Windows 真实环境探测。

只调用冻结 evidence API 和 Windows 文件系统操作，不修改安全实现、不访问网络。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentbench.deepseek_live_canary.native_evidence import PinnedDirectory
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog


def _run(args: list[str]) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        return completed.returncode, (completed.stdout or "").strip(), (completed.stderr or "").strip()
    except OSError as error:
        return 127, "", f"{type(error).__name__}: {error}"


def environment() -> dict[str, Any]:
    _, whoami, _ = _run(["whoami"])
    _, privileges, _ = _run(["whoami", "/priv"])
    _, systeminfo, _ = _run(["systeminfo"])
    os_lines = [
        line.strip()
        for line in systeminfo.splitlines()
        if line.strip().startswith(("OS Name", "OS Version", "OS 名称", "OS 版本"))
    ]
    developer = "DISABLED_OR_NOT_SET"
    if os.name == "nt":
        _, reg_out, _ = _run(["reg", "query", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock", "/v", "AllowDevelopmentWithoutDevLicense"])
        if "0x1" in reg_out.lower():
            developer = "ENABLED"
    return {
        "os": platform.system(),
        "platform": platform.platform(),
        "systeminfo_os": os_lines,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "whoami": whoami,
        "privileges": privileges,
        "se_create_symbolic_link_privilege": "SeCreateSymbolicLinkPrivilege" in privileges,
        "developer_mode": developer,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _symlink_case(root: Path, *, directory: bool) -> dict[str, Any]:
    evidence, outside = root / "evidence", root / "outside"
    evidence.mkdir(parents=True); outside.mkdir(parents=True)
    target = outside / ("target-dir" if directory else "target.json")
    if directory:
        target.mkdir()
        _write(target / "sentinel.txt", "outside-original\n")
    else:
        _write(target, "outside-original\n")
    alias = evidence / ("evidence-dir" if directory else "audit.json")
    error_text = ""
    winerror = None
    try:
        alias.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        winerror = getattr(error, "winerror", None)
        error_text = f"Python symlink: {type(error).__name__}: {error}"
        # 记录 cmd.exe mklink 的原生结果，不改变系统策略。
        args = ["cmd.exe", "/c", "mklink"] + (["/D"] if directory else []) + [str(alias), str(target)]
        code, stdout, stderr = _run(args)
        if code == 0 and alias.exists():
            error_text = stdout or "mklink created link"
        else:
            return {
                "test": "Windows directory symlink" if directory else "Windows file symlink",
                "result": "ENVIRONMENT_BLOCKED",
                "substatus": "WINDOWS_SYMLINK_ENVIRONMENT_BLOCKED",
                "runtime_verified": False,
                "winerror": winerror,
                "detail": error_text + " | mklink: " + (stderr or stdout or f"exit {code}"),
            }
    try:
        if directory:
            PreflightAuditLog(alias / "audit.jsonl", run_id="closeout-dir-link").append({"event": "must-reject"})
        else:
            PreflightAuditLog(alias, run_id="closeout-file-link").append({"event": "must-reject"})
    except (OSError, RuntimeError, ValueError) as error:
        unchanged = (target / "sentinel.txt").read_text(encoding="utf-8") == "outside-original\n" if directory else target.read_text(encoding="utf-8") == "outside-original\n"
        return {
            "test": "Windows directory symlink" if directory else "Windows file symlink",
            "result": "PASS",
            "runtime_verified": True,
            "outside_unchanged": unchanged,
            "detail": error_text or f"link rejected: {type(error).__name__}",
        }
    return {
        "test": "Windows directory symlink" if directory else "Windows file symlink",
        "result": "FAIL",
        "runtime_verified": True,
        "detail": "symlink write unexpectedly succeeded",
    }


def parent_replacement_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    moved = root / "evidence-original"
    attacker = root / "attacker"
    evidence.mkdir(parents=True); attacker.mkdir(parents=True)
    _write(attacker / "sentinel.txt", "attacker-original\n")
    try:
        with PinnedDirectory(evidence) as parent:
            try:
                os.rename(evidence, moved)
                evidence.mkdir()
            except OSError as error:
                return {
                    "test": "Windows parent directory replacement",
                    "result": "ENVIRONMENT_BLOCKED",
                    "substatus": "ENVIRONMENT_LIMITED",
                    "runtime_verified": False,
                    "detail": f"directory replacement blocked by native handle sharing: {type(error).__name__}: {error}",
                }
            try:
                fd = parent.open("audit.jsonl", write=True, create=True)
            except (OSError, RuntimeError, ValueError) as error:
                return {
                    "test": "Windows parent directory replacement",
                    "result": "PASS",
                    "runtime_verified": True,
                    "outside_unchanged": not (attacker / "audit.jsonl").exists(),
                    "detail": f"pinned parent identity rejected replacement: {type(error).__name__}: {error}",
                }
            else:
                os.close(fd)
                return {
                    "test": "Windows parent directory replacement",
                    "result": "FAIL",
                    "runtime_verified": True,
                    "detail": "write unexpectedly succeeded after parent replacement",
                }
    except (OSError, RuntimeError, ValueError) as error:
        return {
            "test": "Windows parent directory replacement",
            "result": "ENVIRONMENT_BLOCKED",
            "substatus": "ENVIRONMENT_LIMITED",
            "runtime_verified": False,
            "detail": f"parent replacement setup blocked: {type(error).__name__}: {error}",
        }


def main() -> int:
    output = REPO_ROOT / "agentbench/reports/phase2b_ds1_r5_1_env_closeout_r1.json"
    with tempfile.TemporaryDirectory(prefix="researchci-closeout-") as temp:
        root = Path(temp)
        tests = [
            _symlink_case(root / "file-link", directory=False),
            _symlink_case(root / "dir-link", directory=True),
            parent_replacement_case(root / "parent-replace"),
        ]
    previous_windows = json.loads((REPO_ROOT / "agentbench/reports/phase2b_ds1_r5_1_r3_3_windows_validation.json").read_text(encoding="utf-8"))
    report = {
        "phase": "2B-DS-1-R5.1-ENV-CLOSEOUT-R1",
        "status": "RUNTIME_VALIDATION_COMPLETE" if all(item["result"] == "PASS" for item in tests) else "WINDOWS_RUNTIME_VALIDATION_PENDING",
        "live_activation": "BLOCKED",
        "baseline_commit": "e276934df2149ca5b2b74ae077daa48225cfb869",
        "environment": environment(),
        "tests": tests,
        "prior_windows_matrix": {
            "junction": "PASS",
            "reparse": "PASS",
            "hardlink": "PASS",
            "symlink_prior_status": previous_windows["counts"],
        },
        "linux_existing_validation": {
            "symlink": "PASS",
            "toctou": "PASS",
            "hardlink": "PASS",
            "parent_replacement": "PASS",
        },
        "network": {"real_provider_api_calls": 0, "real_provider_network_calls": 0, "credential_reads": 0, "live_canary_episodes": 0, "benchmark_episodes": 0},
        "historical_reports_modified": False,
        "security_logic_modified": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "tests": tests, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
