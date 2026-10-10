"""R3.3 Windows 原生文件系统验证的 pytest 覆盖。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from phase2b_ds1_r5_1_r3_3_validation import (  # noqa: E402
    ALLOWED_RESULTS,
    audit_chain_case,
    audit_symlink_case,
    hardlink_case,
    junction_case,
    parent_symlink_case,
    path_identity_case,
    permission_failure_case,
    reparse_case,
    summary_readback_case,
    summary_symlink_case,
    target_replacement_case,
    toctou_case,
)


def _assert_runtime_or_environment(result: dict) -> None:
    assert result["result"] in ALLOWED_RESULTS
    assert result["result"] != "FAIL", result


def test_audit_symlink_runtime_or_explicit_environment_block(tmp_path):
    _assert_runtime_or_environment(audit_symlink_case(tmp_path))


def test_summary_symlink_runtime_or_explicit_environment_block(tmp_path):
    _assert_runtime_or_environment(summary_symlink_case(tmp_path))


def test_parent_directory_symlink_runtime_or_explicit_environment_block(tmp_path):
    _assert_runtime_or_environment(parent_symlink_case(tmp_path))


def test_junction_runtime_or_explicit_environment_block(tmp_path):
    _assert_runtime_or_environment(junction_case(tmp_path))


def test_reparse_point_runtime_or_explicit_simulation_boundary(tmp_path):
    result = reparse_case(tmp_path)
    assert result["result"] in ALLOWED_RESULTS
    assert result["result"] != "FAIL", result


def test_hardlink_runtime_or_explicit_environment_block(tmp_path):
    _assert_runtime_or_environment(hardlink_case(tmp_path))


def test_target_replacement_is_immutable(tmp_path):
    assert target_replacement_case(tmp_path)["result"] == "PASS"


def test_toctou_replacement_fails_closed(tmp_path):
    assert toctou_case(tmp_path)["result"] == "PASS"


def test_permission_failure_is_not_success(tmp_path):
    result = permission_failure_case(tmp_path)
    assert result["result"] == "PASS"
    assert result["runtime_verified"] is False


def test_audit_hash_chain_readback(tmp_path):
    assert audit_chain_case(tmp_path)["result"] == "PASS"


def test_summary_atomic_readback(tmp_path):
    assert summary_readback_case(tmp_path)["result"] == "PASS"


def test_path_identity_rejects_traversal(tmp_path):
    assert path_identity_case(tmp_path)["result"] == "PASS"
