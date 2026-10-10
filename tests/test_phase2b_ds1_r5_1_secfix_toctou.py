"""SEC-FIX-R1：验证 evidence 打开句柄与预期文件身份绑定。"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentbench.deepseek_live_canary import native_evidence
from agentbench.deepseek_live_canary.native_evidence import PinnedDirectory, atomic_json
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fake_info(info, *, dev=None, ino=None, mode=None):
    return SimpleNamespace(
        st_dev=info.st_dev if dev is None else dev,
        st_ino=info.st_ino if ino is None else ino,
        st_mode=info.st_mode if mode is None else mode,
        st_nlink=1,
        st_file_attributes=getattr(info, "st_file_attributes", 0),
    )


def test_file_replacement_between_identity_check_and_open_fails_closed(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    target = evidence / "audit.jsonl"
    replacement = evidence / "replacement"
    _write(target, "original\n")
    _write(replacement, "replacement\n")
    replaced = False
    blocked = False

    with PinnedDirectory(evidence) as parent:
        if os.name == "nt":
            original_open = native_evidence._windows_open

            def racing_open(path, **kwargs):
                nonlocal replaced, blocked
                if not replaced and Path(path).name == target.name:
                    try:
                        os.replace(replacement, target)
                        replaced = True
                    except OSError:
                        blocked = True
                return original_open(path, **kwargs)

            monkeypatch.setattr(native_evidence, "_windows_open", racing_open)
        else:
            original_open = native_evidence.os.open

            def racing_open(path, flags, *args, **kwargs):
                nonlocal replaced
                if not replaced and kwargs.get("dir_fd") == parent.fd and path == target.name:
                    os.replace(replacement, target)
                    replaced = True
                return original_open(path, flags, *args, **kwargs)

            monkeypatch.setattr(native_evidence.os, "open", racing_open)

        rejected = False
        try:
            fd = parent.open(target.name)
        except (OSError, RuntimeError, ValueError):
            rejected = True
        else:
            os.close(fd)

    if blocked:
        assert target.read_text(encoding="utf-8") == "original\n"
    else:
        assert replaced is True
        assert rejected is True
        assert target.read_text(encoding="utf-8") == "replacement\n"


def test_inode_change_is_rejected_by_handle_identity(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    target = evidence / "audit.jsonl"
    _write(target, "original\n")
    with PinnedDirectory(evidence) as parent:
        fd = parent.open(target.name)
        try:
            opened = os.fstat(fd)
            fake = _fake_info(opened, ino=opened.st_ino + 1)
            monkeypatch.setattr(parent, "stat", lambda _name: fake)
            with pytest.raises(RuntimeError, match="identity"):
                parent.validate_file(fd, target.name)
        finally:
            os.close(fd)


def test_device_change_is_rejected_by_handle_identity(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    target = evidence / "audit.jsonl"
    _write(target, "original\n")
    with PinnedDirectory(evidence) as parent:
        fd = parent.open(target.name)
        try:
            opened = os.fstat(fd)
            fake = _fake_info(opened, dev=opened.st_dev + 1)
            monkeypatch.setattr(parent, "stat", lambda _name: fake)
            with pytest.raises(RuntimeError, match="identity"):
                parent.validate_file(fd, target.name)
        finally:
            os.close(fd)


def test_symlink_replacement_is_rejected(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    outside = tmp_path / "outside"
    evidence.mkdir(); outside.mkdir()
    target = evidence / "audit.jsonl"
    replacement = outside / "outside.json"
    _write(target, "original\n")
    _write(replacement, "outside-original\n")
    replaced = False

    with PinnedDirectory(evidence) as parent:
        if os.name == "nt":
            original_open = native_evidence._windows_open

            def racing_open(path, **kwargs):
                nonlocal replaced
                if not replaced and Path(path).name == target.name:
                    try:
                        target.unlink()
                        target.symlink_to(replacement)
                        replaced = True
                    except OSError:
                        pytest.skip("NOT_RUN: Windows symlink privilege unavailable")
                return original_open(path, **kwargs)

            monkeypatch.setattr(native_evidence, "_windows_open", racing_open)
        else:
            original_open = native_evidence.os.open

            def racing_open(path, flags, *args, **kwargs):
                nonlocal replaced
                if not replaced and kwargs.get("dir_fd") == parent.fd and path == target.name:
                    target.unlink()
                    target.symlink_to(replacement)
                    replaced = True
                return original_open(path, flags, *args, **kwargs)

            monkeypatch.setattr(native_evidence.os, "open", racing_open)

        with pytest.raises((OSError, RuntimeError, ValueError)):
            parent.open(target.name)

    assert replacement.read_text(encoding="utf-8") == "outside-original\n"


def test_hardlink_replacement_cannot_modify_external_target(tmp_path):
    evidence = tmp_path / "evidence"
    outside = tmp_path / "outside"
    evidence.mkdir(); outside.mkdir()
    important = outside / "important.txt"
    alias = evidence / "audit.jsonl"
    _write(important, "important-original\n")
    os.link(important, alias)
    with pytest.raises((OSError, RuntimeError, ValueError)):
        PreflightAuditLog(alias, run_id="secfix-hardlink").append({"event": "must-reject"})
    assert important.read_text(encoding="utf-8") == "important-original\n"


@pytest.mark.skipif(os.name == "nt", reason="NOT_RUN: Windows directory replacement is blocked by native handle sharing")
def test_parent_directory_replacement_fails_closed(tmp_path):
    evidence = tmp_path / "evidence"
    moved = tmp_path / "evidence-old"
    evidence.mkdir()
    with PinnedDirectory(evidence) as parent:
        os.rename(evidence, moved)
        evidence.mkdir()
        with pytest.raises(RuntimeError, match="directory identity"):
            parent.open("audit.jsonl", create=True, write=True)
    assert not (evidence / "audit.jsonl").exists()


def test_summary_atomic_write_race_does_not_replace_attacker_target(tmp_path, monkeypatch):
    summary = tmp_path / "evidence" / "summary.json"
    original_publish = PinnedDirectory.publish

    def racing_publish(parent, fd, temporary, target):
        attacker_target = parent.path / target
        attacker_target.write_text("attacker-target\n", encoding="utf-8")
        return original_publish(parent, fd, temporary, target)

    monkeypatch.setattr(PinnedDirectory, "publish", racing_publish)
    with pytest.raises(RuntimeError, match="existing evidence target"):
        atomic_json(summary, {"status": "must-not-publish"})
    assert summary.read_text(encoding="utf-8") == "attacker-target\n"
