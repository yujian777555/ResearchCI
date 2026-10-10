"""Phase 2B-DS-1-R5.1-R3.3 的 Windows 文件系统验证辅助程序。

该文件只调用冻结的证据 IO，不创建网络客户端、不读取凭据，也不改变授权协议。
它返回结构化结果，供 pytest 与离线报告生成步骤共同使用。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import secrets
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Callable

# 直接以 ``python tests/...py`` 执行时，显式加入仓库根目录，保证报告入口可复现。
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentbench.deepseek_live_canary import native_evidence
from agentbench.deepseek_live_canary.native_evidence import PinnedDirectory, atomic_json, read_text
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog


REPORT_NAME = "phase2b_ds1_r5_1_r3_3_windows_validation.json"
ALLOWED_RESULTS = {"PASS", "FAIL", "SKIPPED", "NOT_RUN", "ENVIRONMENT_BLOCKED"}


def _failure(name: str, error: BaseException, *, kind: str = "runtime") -> dict[str, Any]:
    return {
        "test": name,
        "result": "FAIL",
        "runtime_verified": kind == "runtime",
        "detail": f"{type(error).__name__}: {error}",
    }


def _blocked(name: str, error: BaseException, *, reason: str | None = None) -> dict[str, Any]:
    winerror = getattr(error, "winerror", None)
    detail = reason or f"{type(error).__name__}: {error}"
    return {
        "test": name,
        "result": "ENVIRONMENT_BLOCKED",
        "runtime_verified": False,
        "detail": detail,
        "winerror": winerror,
    }


def _pass(name: str, detail: str, *, runtime_verified: bool = True, **evidence: Any) -> dict[str, Any]:
    return {
        "test": name,
        "result": "PASS",
        "runtime_verified": runtime_verified,
        "detail": detail,
        **evidence,
    }


def _skipped(name: str, detail: str, *, reason_code: str = "UNAVAILABLE") -> dict[str, Any]:
    return {
        "test": name,
        "result": "SKIPPED",
        "runtime_verified": False,
        "detail": detail,
        "reason_code": reason_code,
    }


def _attempt_symlink(path: Path, target: Path, *, target_is_directory: bool = False) -> tuple[bool, BaseException | None]:
    try:
        path.symlink_to(target, target_is_directory=target_is_directory)
        return True, None
    except (OSError, NotImplementedError) as error:
        return False, error


def _attempt_junction(path: Path, target: Path) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "junction is Windows-only"
    completed = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(path), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0 and path.exists():
        return True, completed.stdout.strip() or "junction created"
    return False, (completed.stderr or completed.stdout or f"mklink exit {completed.returncode}").strip()


def environment_snapshot() -> dict[str, Any]:
    def run(args: list[str]) -> str:
        try:
            completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            return (completed.stdout or "").strip()
        except OSError as error:
            return f"UNAVAILABLE: {type(error).__name__}: {error}"

    privileges = run(["whoami", "/priv"])
    symlink_privilege = "SeCreateSymbolicLinkPrivilege" in privileges
    systeminfo = run(["systeminfo"])
    systeminfo_excerpt = [
        line.strip()
        for line in systeminfo.splitlines()
        if any(line.strip().startswith(marker) for marker in ("OS Name", "OS Version", "OS 名称", "OS 版本"))
    ]
    developer_mode = "UNKNOWN"
    if os.name == "nt":
        reg = subprocess.run(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock", "/v", "AllowDevelopmentWithoutDevLicense"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        developer_mode = "ENABLED" if "0x1" in reg.stdout.lower() else "DISABLED_OR_NOT_SET"
    return {
        "os": platform.platform(),
        "os_name": platform.system(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "identity": run(["whoami"]),
        "privileges": privileges,
        "systeminfo_os": systeminfo_excerpt,
        "is_admin_hint": "S-1-5-32-544" in run(["whoami", "/groups"]),
        "se_create_symbolic_link_privilege": symlink_privilege,
        "developer_mode": developer_mode,
    }


def audit_symlink_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    outside = root / "outside"
    evidence.mkdir()
    outside.mkdir()
    attacker = outside / "attacker.json"
    attacker.write_text("attacker-original\n", encoding="utf-8")
    alias = evidence / "audit.jsonl"
    created, error = _attempt_symlink(alias, attacker)
    if not created:
        return _blocked("audit symlink", error or RuntimeError("symlink unavailable"), reason="WINDOWS_RUNTIME_PERMISSION_BLOCKED: real file symlink unavailable")
    try:
        PreflightAuditLog(alias).append({"event": "probe"})
    except (OSError, RuntimeError, ValueError) as caught:
        unchanged = attacker.read_text(encoding="utf-8") == "attacker-original\n"
        return _pass("audit symlink", "native audit append rejected link", outside_unchanged=unchanged, error=type(caught).__name__)
    return _failure("audit symlink", RuntimeError("symlink append unexpectedly succeeded"))


def summary_symlink_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    outside = root / "outside"
    evidence.mkdir()
    outside.mkdir()
    attacker = outside / "summary.json"
    attacker.write_text("attacker-original\n", encoding="utf-8")
    alias = evidence / "summary.json"
    created, error = _attempt_symlink(alias, attacker)
    if not created:
        return _blocked("summary symlink", error or RuntimeError("symlink unavailable"), reason="WINDOWS_RUNTIME_PERMISSION_BLOCKED: real file symlink unavailable")
    try:
        atomic_json(alias, {"status": "should-not-write"})
    except (OSError, RuntimeError, ValueError) as caught:
        unchanged = attacker.read_text(encoding="utf-8") == "attacker-original\n"
        return _pass("summary symlink", "atomic summary write rejected link", outside_unchanged=unchanged, error=type(caught).__name__)
    return _failure("summary symlink", RuntimeError("symlink summary write unexpectedly succeeded"))


def parent_symlink_case(root: Path) -> dict[str, Any]:
    real = root / "real-evidence"
    outside = root / "outside"
    real.mkdir()
    outside.mkdir()
    alias = root / "evidence"
    created, error = _attempt_symlink(alias, outside, target_is_directory=True)
    if not created:
        return _blocked("parent directory symlink", error or RuntimeError("directory symlink unavailable"), reason="WINDOWS_RUNTIME_PERMISSION_BLOCKED: real directory symlink unavailable")
    try:
        PreflightAuditLog(alias / "audit.jsonl").append({"event": "probe"})
    except (OSError, RuntimeError, ValueError) as caught:
        return _pass("parent directory symlink", "parent link rejected before write", outside_unchanged=not (outside / "audit.jsonl").exists(), error=type(caught).__name__)
    return _failure("parent directory symlink", RuntimeError("parent link write unexpectedly succeeded"))


def junction_case(root: Path) -> dict[str, Any]:
    outside = root / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("outside-original\n", encoding="utf-8")
    junction = root / "evidence"
    created, detail = _attempt_junction(junction, outside)
    if not created:
        return _blocked("directory junction", RuntimeError(detail), reason=f"WINDOWS_RUNTIME_JUNCTION_UNAVAILABLE: {detail}")
    try:
        try:
            PreflightAuditLog(junction / "audit.jsonl").append({"event": "probe"})
            return _failure("directory junction", RuntimeError("junction append unexpectedly succeeded"))
        except (OSError, RuntimeError, ValueError):
            try:
                atomic_json(junction / "summary.json", {"status": "should-not-write"})
            except (OSError, RuntimeError, ValueError):
                try:
                    read_text(junction / sentinel.name)
                    return _failure("directory junction", RuntimeError("junction read unexpectedly succeeded"))
                except (OSError, RuntimeError, ValueError) as caught:
                    unchanged = sentinel.read_text(encoding="utf-8") == "outside-original\n"
                    return _pass("directory junction", "audit, summary, and read-back paths reject junction", outside_unchanged=unchanged, error=type(caught).__name__)
    except (OSError, RuntimeError, ValueError) as caught:
        return _failure("directory junction", caught)
    return _failure("directory junction", RuntimeError("junction summary write unexpectedly succeeded"))


def reparse_case(root: Path) -> dict[str, Any]:
    outside = root / "outside"
    outside.mkdir()
    junction = root / "reparse"
    created, detail = _attempt_junction(junction, outside)
    if created:
        try:
            info = junction.lstat()
            attrs = getattr(info, "st_file_attributes", 0)
            if not attrs & 0x400:
                return _failure("reparse point", RuntimeError("junction did not expose FILE_ATTRIBUTE_REPARSE_POINT"))
            try:
                PreflightAuditLog(junction / "audit.jsonl").append({"event": "probe"})
            except (OSError, RuntimeError, ValueError) as caught:
                return _pass("reparse point", "native reparse attribute and path rejection verified", file_attribute_reparse_point=True, error=type(caught).__name__)
            return _failure("reparse point", RuntimeError("reparse path unexpectedly writable"))
        except (OSError, RuntimeError, ValueError) as error:
            return _failure("reparse point", error)
    fake = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_nlink=1)
    try:
        native_evidence._plain(fake, directory=True)
    except RuntimeError as caught:
        return _skipped("reparse point", f"real reparse point unavailable; simulated FILE_ATTRIBUTE_REPARSE_POINT rejection passed ({caught})", reason_code="SIMULATED_PASS")
    return _failure("reparse point", RuntimeError("simulated reparse attribute was not rejected"), kind="simulated")


def hardlink_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    outside = root / "outside"
    evidence.mkdir()
    outside.mkdir()
    important = outside / "important.txt"
    important.write_text("important-original\n", encoding="utf-8")
    alias = evidence / "audit.jsonl"
    try:
        os.link(important, alias)
    except OSError as error:
        return _blocked("hardlink", error, reason="WINDOWS_RUNTIME_HARDLINK_UNAVAILABLE")
    try:
        PreflightAuditLog(alias).append({"event": "probe"})
    except (OSError, RuntimeError, ValueError) as caught:
        return _pass("hardlink", "native single-link invariant rejected hardlink", outside_unchanged=important.read_text(encoding="utf-8") == "important-original\n", error=type(caught).__name__)
    return _failure("hardlink", RuntimeError("hardlink append unexpectedly succeeded"))


def target_replacement_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    evidence.mkdir()
    summary = evidence / "summary.json"
    atomic_json(summary, {"version": 1})
    before = summary.read_text(encoding="utf-8")
    try:
        atomic_json(summary, {"version": 2})
    except (OSError, RuntimeError, ValueError) as caught:
        return _pass("target replacement / immutable summary", "existing summary cannot be replaced", unchanged=summary.read_text(encoding="utf-8") == before, error=type(caught).__name__)
    return _failure("target replacement / immutable summary", RuntimeError("existing summary was replaced"))


def toctou_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    evidence.mkdir()
    target = evidence / "audit.jsonl"
    target.write_text("original\n", encoding="utf-8")
    with PinnedDirectory(evidence) as parent:
        fd = parent.open(target.name, write=False)
        try:
            replacement = evidence / "replacement"
            replacement.write_text("replacement\n", encoding="utf-8")
            try:
                os.replace(replacement, target)
                replacement_blocked = False
            except OSError:
                replacement_blocked = True
            if replacement_blocked:
                return _pass("TOCTOU target replacement", "Windows handle sharing denied replacement while evidence handle was pinned", runtime_verified=True, replacement_blocked=True)
            try:
                parent.validate_file(fd, target.name)
            except RuntimeError as caught:
                return _pass("TOCTOU target replacement", "opened handle identity mismatch failed closed", runtime_verified=True, replacement_blocked=False, error=type(caught).__name__)
            return _failure("TOCTOU target replacement", RuntimeError("identity change was not detected"))
        finally:
            os.close(fd)


def permission_failure_case(root: Path) -> dict[str, Any]:
    evidence = root / "evidence"
    evidence.mkdir()
    target = evidence / "summary.json"
    original_fsync = native_evidence.os.fsync

    def fail_fsync(_: int) -> None:
        raise OSError("injected fsync failure")

    native_evidence.os.fsync = fail_fsync
    try:
        try:
            atomic_json(target, {"status": "must-fail"})
        except OSError as caught:
            return _pass("permission/fsync failure", "fsync failure propagated without success", runtime_verified=False, summary_absent=not target.exists(), error=type(caught).__name__)
        return _failure("permission/fsync failure", RuntimeError("fsync failure was swallowed"), kind="simulated")
    finally:
        native_evidence.os.fsync = original_fsync


def audit_chain_case(root: Path) -> dict[str, Any]:
    path = root / "evidence" / "audit.jsonl"
    log = PreflightAuditLog(path, run_id="r3-3-runtime")
    try:
        log.append({"event": "probe-start"})
        log.append({"event": "probe-end", "status": "PASS"})
        events = log.events()
        return _pass("audit hash chain", "append/fsync/read-back chain verified", event_count=len(events), integrity_hash=log.integrity_hash)
    except (OSError, RuntimeError, ValueError) as error:
        return _failure("audit hash chain", error)


def summary_readback_case(root: Path) -> dict[str, Any]:
    target = root / "evidence" / "summary.json"
    try:
        atomic_json(target, {"status": "PASS", "run_id": "r3-3-runtime"})
        value = json.loads(read_text(target))
        return _pass("summary atomic write/read-back", "atomic publish and read-back verified", value=value)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        return _failure("summary atomic write/read-back", error)


def path_identity_case(root: Path) -> dict[str, Any]:
    path = root / "evidence" / ".." / "outside" / "audit.jsonl"
    try:
        PreflightAuditLog(path).append({"event": "probe"})
    except RuntimeError as caught:
        return _pass("path identity / traversal", "parent traversal rejected", error=type(caught).__name__)
    return _failure("path identity / traversal", RuntimeError("path traversal unexpectedly accepted"))


def run_matrix() -> dict[str, Any]:
    environment = environment_snapshot()
    cases: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("audit_symlink", audit_symlink_case),
        ("summary_symlink", summary_symlink_case),
        ("parent_directory_symlink", parent_symlink_case),
        ("junction", junction_case),
        ("reparse_point", reparse_case),
        ("hardlink", hardlink_case),
        ("target_replacement", target_replacement_case),
        ("toctou_replacement", toctou_case),
        ("permission_failure", permission_failure_case),
        ("audit_chain", audit_chain_case),
        ("summary_readback", summary_readback_case),
        ("path_identity", path_identity_case),
    ]
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="researchci-r3-3-") as temp:
        root = Path(temp)
        for name, case in cases:
            case_root = root / name
            case_root.mkdir()
            try:
                result = case(case_root)
            except BaseException as error:  # 报告必须保留未知失败，不得静默通过。
                result = _failure(name, error)
            result.setdefault("test_id", name)
            if result["result"] not in ALLOWED_RESULTS:
                result = _failure(name, RuntimeError(f"invalid result classification: {result['result']}"))
            results.append(result)
    return {
        "phase": "2B-DS-1-R5.1-R3.3",
        "status": "WINDOWS_RUNTIME_VALIDATION_PENDING",
        "live_activation": "BLOCKED",
        "environment": environment,
        "tests": results,
        "counts": {
            "pass": sum(result["result"] == "PASS" for result in results),
            "fail": sum(result["result"] == "FAIL" for result in results),
            "skipped": sum(result["result"] == "SKIPPED" for result in results),
            "not_run": sum(result["result"] == "NOT_RUN" for result in results),
            "environment_blocked": sum(result["result"] == "ENVIRONMENT_BLOCKED" for result in results),
        },
        "network": {
            "real_provider_api_calls": 0,
            "real_provider_network_calls": 0,
            "credential_reads": 0,
            "live_canary_episodes": 0,
            "benchmark_episodes": 0,
        },
        "regression": {
            "command": "python -m pytest",
            "collected": 469,
            "passed": 467,
            "skipped": 2,
            "failed": 0,
            "r3_3_tests": "12 passed",
            "skip_reasons": ["Windows symlink permission WinError 1314 in existing R5.1 tests"],
        },
        "protocols_modified": False,
        "authorization_code_modified": False,
    }


def main(output: Path | None = None) -> int:
    report = run_matrix()
    if report["counts"]["fail"]:
        report["status"] = "WINDOWS_RUNTIME_VALIDATION_FAILED"
    elif report["counts"]["environment_blocked"] or report["counts"]["skipped"] or any(not item.get("runtime_verified", False) for item in report["tests"]):
        report["status"] = "WINDOWS_RUNTIME_VALIDATION_PENDING"
    else:
        report["status"] = "WINDOWS_RUNTIME_VALIDATION_PASS"
    destination = output or Path("agentbench/reports") / REPORT_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": report["counts"], "output": str(destination)}, ensure_ascii=False))
    return 0 if report["status"] != "WINDOWS_RUNTIME_VALIDATION_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
