"""Closeout 补证：真实路径替换、公开写入口、完整性断言及禁止联网保护。

仅在临时目录里操作真实文件；hook 只决定攻击时机，不伪造 stat/open 结果。
默认输出到显式指定的新文件，绝不覆盖历史报告。
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agentbench.deepseek_live_canary import native_evidence as native
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog, atomic_write_json

RUN = "closeout-recheck-offline"


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def snapshot(directory):
    return {str(p.relative_to(directory)): digest(p.read_bytes())
            for p in sorted(directory.rglob("*")) if p.is_file()}


def exception(error):
    return {"type": type(error).__name__, "message": str(error),
            "errno": getattr(error, "errno", None), "winerror": getattr(error, "winerror", None)}


def command(args):
    result = subprocess.run(args, capture_output=True, timeout=90, check=False)
    return {"command": args, "exit_code": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace")}


@contextmanager
def offline_guard():
    counters = {"network_attempts_blocked": 0, "credential_reads_blocked": 0}
    getitem = os._Environ.__getitem__

    def env_get(self, key):
        if key.upper() in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}:
            counters["credential_reads_blocked"] += 1
            raise AssertionError("真实凭据访问禁止")
        return getitem(self, key)

    def network(*args, **kwargs):
        counters["network_attempts_blocked"] += 1
        raise AssertionError("外部连接禁止")

    with ExitStack() as stack:
        stack.enter_context(patch.object(os._Environ, "__getitem__", env_get))
        for obj, name in [(socket.socket, "connect"), (socket.socket, "connect_ex"),
                          (socket, "create_connection")]:
            stack.enter_context(patch.object(obj, name, network))
        yield counters


def environment(temp_root):
    info = {"os": platform.system(), "kernel": platform.release(),
            "platform": platform.platform(), "python": platform.python_version(),
            "python_executable": sys.executable, "temporary_root": str(temp_root)}
    if os.name == "nt":
        info["whoami"] = command(["whoami"])
        info["privileges"] = command(["whoami", "/priv"])
        info["systeminfo"] = command(["systeminfo"])
        info["python_version"] = command([sys.executable, "--version"])
        info["elevated_admin_token"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
        info["se_create_symbolic_link_privilege"] = "SeCreateSymbolicLinkPrivilege" in info["privileges"]["stdout"]
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock") as key:
                value, _ = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")
                info["developer_mode"] = {"state": "ENABLED" if value == 1 else "DISABLED", "value": value}
        except FileNotFoundError as error:
            info["developer_mode"] = {"state": "NOT_SET", "error": exception(error)}
        except OSError as error:
            info["developer_mode"] = {"state": "UNKNOWN", "error": exception(error)}
    else:
        info.update(uid=os.getuid(), euid=os.geteuid(), developer_mode="NOT_APPLICABLE")
        info["filesystem"] = command(["stat", "-f", "-c", "%T", str(temp_root)])
        info["identity"] = command(["id"])
    return info


def seed(directory):
    directory.mkdir(parents=True)
    log = PreflightAuditLog(directory / "audit.jsonl", run_id=RUN)
    log.append({"event": "seed-start"})
    log.append({"event": "seed-end"})
    atomic_write_json(directory / "stable.json", {"run_id": RUN, "stable": True})
    return log


def integrity(directory):
    log = PreflightAuditLog(directory / "audit.jsonl", run_id=RUN)
    events = log.events()
    return {"audit_hash_chain_valid": len(events) == 2,
            "chain_tail": log.integrity_hash,
            "summary_integrity": json.loads((directory / "stable.json").read_text(encoding="utf-8")) == {"run_id": RUN, "stable": True}}


def rejected_call(action):
    try:
        action()
    except (OSError, RuntimeError, ValueError) as error:
        return exception(error)
    return None


def link_case(root, kind):
    outside = root / "outside"
    seed(outside)
    before = snapshot(outside)
    evidence = root / "evidence"
    directory = kind in {"directory_symlink", "junction"}
    if directory:
        alias, target = evidence, outside
    elif kind == "hardlink":
        evidence.mkdir()
        target = outside / "important.txt"
        target.write_text("important-original\n", encoding="utf-8")
        alias = evidence / "audit.jsonl"
        # hardlink 目标是攻击夹具本身；在建立 alias 前重新固定 outside 基线。
        before = snapshot(outside)
    else:
        evidence.mkdir()
        alias = evidence / ("summary.json" if kind == "summary_symlink" else "audit.jsonl")
        target = outside / ("stable.json" if kind == "summary_symlink" else "audit.jsonl")
    creation = {}
    if kind == "junction":
        creation["mklink"] = command(["cmd.exe", "/c", "mklink", "/J", str(alias), str(target)])
        if creation["mklink"]["exit_code"] != 0:
            return {"result": "ENVIRONMENT_BLOCKED", "creation": creation}
    elif kind == "hardlink":
        os.link(target, alias)
    else:
        try:
            alias.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            creation["python_error"] = exception(error)
        if os.name == "nt":
            # 独立原生 mklink 尝试；已创建时只移除本次临时链接。
            if alias.is_symlink():
                alias.unlink()
            creation["mklink"] = command(["cmd.exe", "/c", "mklink"] + (["/D"] if directory else []) + [str(alias), str(target)])
            if creation["mklink"]["exit_code"] != 0:
                return {"result": "ENVIRONMENT_BLOCKED", "substatus": "WINDOWS_SYMLINK_ENVIRONMENT_BLOCKED",
                        "creation": creation, "outside_target_modified": snapshot(outside) != before,
                        **integrity(outside)}
        elif "python_error" in creation:
            return {"result": "ENVIRONMENT_BLOCKED", "creation": creation}
    info = alias.lstat()
    if kind == "junction":
        assert getattr(info, "st_file_attributes", 0) & 0x400, "真实 junction 缺少 reparse 属性"
    elif kind == "hardlink":
        assert info.st_nlink >= 2, "未创建真实 hardlink"
    else:
        assert alias.is_symlink(), "未创建真实 symlink"
    actions = {}
    if kind != "summary_symlink":
        actions["audit_append"] = rejected_call(lambda: PreflightAuditLog(evidence / "audit.jsonl", run_id=RUN).append({"event": "attack"}))
    if directory or kind == "summary_symlink":
        actions["summary_write_and_publish"] = rejected_call(lambda: atomic_write_json(evidence / "summary.json", {"attack": True}))
    if directory:
        actions["readback"] = rejected_call(lambda: native.read_text(evidence / "stable.json"))
    invariants = integrity(outside)
    modified = snapshot(outside) != before
    passed = all(actions.values()) and not modified and invariants["audit_hash_chain_valid"] and invariants["summary_integrity"]
    return {"result": "PASS" if passed else "FAIL", "creation": creation, "operations": actions,
            "outside_target_modified": modified, "real_link_created": True,
            "file_attributes": getattr(info, "st_file_attributes", None), **invariants}


class EnvironmentLimited(RuntimeError):
    """攻击没有成功安装，不能宣称防御验证通过。"""


def parent_replacement_case(root, operation):
    evidence, moved, attacker = root / "evidence", root / "original", root / "attacker"
    log = seed(evidence)
    seed(attacker)
    original_before, attacker_before = snapshot(evidence), snapshot(attacker)
    attack = {"attempted": False, "installed": False, "renamed_original": False}
    original_open, original_publish = native.PinnedDirectory.open, native.PinnedDirectory.publish

    def replace(parent):
        parent.validate()
        attack["attempted"] = True
        attack["checked_identity"] = list(native._identity(os.fstat(parent.fd)))
        try:
            evidence.rename(moved)
            attack["renamed_original"] = True
            attacker.rename(evidence)
            attack["installed"] = True
            attack["replacement_identity"] = list(native._identity(evidence.stat()))
        except OSError as error:
            attack["error"] = exception(error)
            raise EnvironmentLimited("真实目录替换被操作系统阻断") from error

    def opening(parent, name, **kwargs):
        match = name == "audit.jsonl" if operation == "audit_append" else name.startswith(".summary.json.r5tmp-")
        if operation != "evidence_publish" and parent.path == evidence and kwargs.get("write") and match and not attack["attempted"]:
            replace(parent)
        return original_open(parent, name, **kwargs)

    def publishing(parent, fd, temporary, target):
        if operation == "evidence_publish" and parent.path == evidence:
            parent.validate_file(fd, temporary)
            replace(parent)
        return original_publish(parent, fd, temporary, target)

    error = None
    with patch.object(native.PinnedDirectory, "open", opening), patch.object(native.PinnedDirectory, "publish", publishing):
        try:
            if operation == "audit_append":
                log.append({"event": "attack"})
            else:
                atomic_write_json(evidence / "summary.json", {"attack": True})
        except (OSError, RuntimeError, ValueError) as caught:
            error = exception(caught)
    original_dir = moved if attack["renamed_original"] else evidence
    attacker_dir = evidence if attack["installed"] else attacker
    invariants = integrity(original_dir)
    attacker_changed = snapshot(attacker_dir) != attacker_before
    unchanged_original = all((original_dir / name).exists() and digest((original_dir / name).read_bytes()) == value for name, value in original_before.items())
    unpublished = not (original_dir / "summary.json").exists() and not (attacker_dir / "summary.json").exists()
    valid = invariants["audit_hash_chain_valid"] and invariants["summary_integrity"] and unchanged_original and unpublished and not attacker_changed
    if not attack["attempted"] or not valid:
        result = "FAIL"
    elif not attack["installed"]:
        result = "ENVIRONMENT_BLOCKED"
    else:
        result = "PASS" if error and "directory identity changed" in error["message"] else "FAIL"
    return {"result": result, "substatus": "ENVIRONMENT_LIMITED" if result == "ENVIRONMENT_BLOCKED" else None,
            "entrypoint": "PreflightAuditLog.append" if operation == "audit_append" else "atomic_write_json",
            "attack": attack, "rejection": error, "outside_target_modified": attacker_changed,
            "original_evidence_unchanged": unchanged_original, "summary_unpublished": unpublished, **invariants}


def toctou_case(root):
    evidence, replacement, preserved = root / "evidence", root / "replacement", root / "original.jsonl"
    seed(evidence)
    seed(replacement)
    target = evidence / "audit.jsonl"
    before = snapshot(replacement)
    checked = native._identity(target.stat())
    original_open = os.open
    attacked = False
    with native.PinnedDirectory(evidence) as parent:
        def racing(path, flags, *args, **kwargs):
            nonlocal attacked
            if path == target.name and kwargs.get("dir_fd") == parent.fd and not attacked:
                target.rename(preserved)
                (replacement / "audit.jsonl").rename(target)
                attacked = True
            return original_open(path, flags, *args, **kwargs)
        error = None
        with patch.object(os, "open", racing):
            try:
                fd = parent.open(target.name, write=True)
            except (OSError, RuntimeError) as caught:
                error = exception(caught)
            else:
                os.close(fd)
    assert attacked, "没有触发真实 TOCTOU 替换"
    invariants = integrity(evidence)
    unchanged = digest(target.read_bytes()) == before["audit.jsonl"]
    different = checked != native._identity(target.stat())
    passed = error is not None and "identity changed" in error["message"] and different and unchanged and invariants["audit_hash_chain_valid"]
    return {"result": "PASS" if passed else "FAIL", "rejection": error, "checked_inode_changed": different,
            "outside_target_modified": not unchanged, **invariants}


def collect():
    with tempfile.TemporaryDirectory(prefix="researchci-closeout-recheck-", dir=None if os.name == "nt" else "/tmp") as temporary:
        root = Path(temporary).resolve()
        info = environment(root)
        cases = [(kind, lambda p, k=kind: link_case(p, k)) for kind in ["file_symlink", "summary_symlink", "directory_symlink", "hardlink"]]
        if os.name == "nt":
            cases.append(("junction_reparse", lambda p: link_case(p, "junction")))
        else:
            cases.append(("toctou", toctou_case))
        cases += [("parent_" + op, lambda p, operation=op: parent_replacement_case(p, operation))
                  for op in ["audit_append", "summary_write", "evidence_publish"]]
        results = []
        for name, case in cases:
            case_root = root / name
            case_root.mkdir()
            try:
                result = case(case_root)
            except Exception as error:
                result = {"result": "FAIL", "error": exception(error)}
            result["test_id"] = name
            results.append(result)
    return info, results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # 在运行前拒绝覆盖任何已存在输出，避免改写历史结果。
    if args.output.exists():
        raise FileExistsError(args.output)
    with offline_guard() as counters:
        info, results = collect()
    counts = dict(Counter(item["result"] for item in results))
    if counts.get("FAIL") or any(counters.values()):
        status = "RUNTIME_VALIDATION_FAILED"
    elif any(item["result"] != "PASS" for item in results):
        status = "WINDOWS_RUNTIME_VALIDATION_PENDING" if os.name == "nt" else "ENVIRONMENT_BLOCKED"
    else:
        status = "PLATFORM_CASES_PASS"
    source_paths = ["agentbench/deepseek_live_canary/native_evidence.py", "agentbench/deepseek_live_canary/secure_io.py",
                    "agentbench/deepseek_live_canary/preflight.py", str(Path(__file__).relative_to(ROOT)).replace("\\", "/")]
    report = {"phase": "2B-DS-1-R5.1-ENV-CLOSEOUT-R1", "kind": "supplemental_runtime_evidence",
              "utc": datetime.now(timezone.utc).isoformat(), "base_commit": command(["git", "-C", str(ROOT), "rev-parse", "HEAD"])["stdout"].strip(),
              "status": status, "live_activation": "BLOCKED", "environment": info, "tests": results, "counts": counts,
              "source_hashes": {path: digest((ROOT / path).read_bytes()) for path in source_paths}, "offline_guard": counters,
              "real_provider_api_calls": 0, "real_provider_network_calls": 0, "real_credential_reads": 0,
              "live_canary_episodes": 0, "benchmark_episodes": 0}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": status, "counts": counts, "output": str(args.output)}, ensure_ascii=False))
    return 1 if status == "RUNTIME_VALIDATION_FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
