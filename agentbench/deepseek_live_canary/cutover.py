"""独立授权后的单次 replacement GET /models 协调器；CLI 不开放该入口。

R5 只在 MockTransport 中演练这一相同路径。输出不包含 key、headers 或完整
目录。即使 PASS 也只输出预检证据并停止，POST /responses 需要另行批准。
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Callable

import httpx2

from .authorization import AuthorizationVerifier, OneUseLedger, read_repository_state, validate_repository
from .preflight import PreflightAuditLog, persist_preflight_result, run_preflight
from .sdk_client import build_sdk_client


def execute_replacement_preflight(*, authorization: Any, verifier: AuthorizationVerifier,
        ledger_path: str | Path, output_dir: str | Path, repo_root: str | Path,
        run_id: str, expected_harness_sha: str, credential_provider: Callable[[], str],
        transport: Any = None, state_reader: Callable = read_repository_state,
        transport_factory: Any = None) -> dict[str, Any]:
    """验证→不可回退 reserve→凭据回调→真实 SDK→持久化→STOP。

    没有内置批准或环境凭据回退。调用者必须先获得未来独立的人类批准；R5 的
    测试只传临时签名和 synthetic credential。
    """
    if not isinstance(verifier, AuthorizationVerifier):
        raise RuntimeError("trusted authorization verifier required")
    root = Path(repo_root).resolve()
    for path in (Path(ledger_path).resolve(), Path(output_dir).resolve()):
        if path == root or root in path.parents:
            raise ValueError("execution ledger and evidence must be outside the frozen repository")
    mode = "MOCK_HTTP" if isinstance(transport, httpx2.MockTransport) else "LIVE_HTTP"
    approval = verifier.verify(authorization, run_id=run_id, harness_sha=expected_harness_sha, transport_mode=mode)
    def repository_check():
        validate_repository(state_reader(root), expected_harness_sha, require_fresh=(mode == "LIVE_HTTP"))
    repository_check()
    ledger = OneUseLedger(ledger_path)
    reservation = ledger.reserve(approval, repo_root=root)
    log = PreflightAuditLog(Path(output_dir) / f"{run_id}.jsonl", run_id=run_id)
    summary_path = Path(output_dir) / f"{run_id}.summary.json"
    client = None
    try:
        repository_check()
        credential = credential_provider()
        if not isinstance(credential, str) or not credential:
            raise RuntimeError("operator-supplied credential missing")
        client, audit = build_sdk_client(api_key=credential, audit_log=log, transport=transport,
            reservation=reservation, repository_check=repository_check, transport_factory=transport_factory)
        del credential
        result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
        # 资格结论必须与同一 SDK/transport/log 的实际观察一致。
        instrumented = (audit.max_retries == 0 and audit.transport_retries == 0 and not audit.compromised
                        and audit.sdk_invocations_by_endpoint == {"models": 1, "responses": 0}
                        and audit.attempts_by_endpoint == {"models": 1, "responses": 0}
                        and audit.completions_by_endpoint == {"models": 1, "responses": 0}
                        and audit.verified and result.http_attempt_count_verified)
        if result.status == "PASS" and not instrumented:
            result = replace(result, status="FAIL_TRANSPORT_UNVERIFIED", http_attempt_count_verified=False)
        result = replace(result, authorization_stage="PRECHECK_ONLY", canary_authorized=False,
                         http_status=audit.last_http_status or result.http_status)
        summary = persist_preflight_result(result, summary_path, log)
        state = "RESULT_PERSISTED" if instrumented or (audit.last_http_status is not None and result.status != "PASS") else "UNKNOWN"
        row = ledger.read(approval.intent["token_id"])
        reservation.transition(row["state"], state, {"status": summary["status"],
            "target_present": summary["target_present"], "http_attempts_observed": summary["http_attempts_observed"],
            "http_attempt_count_verified": summary["http_attempt_count_verified"], "primary_event_hash": summary["primary_event_hash"]})
        return {**summary, "ledger_state": state, "authorization_hash": approval.authorization_hash,
                "sdk_invocations_by_endpoint": dict(audit.sdk_invocations_by_endpoint),
                "authorization_transport_mode": audit.authorization_transport_mode,
                "execution_security_mode": audit.execution_security_mode,
                "wire_backend": audit.wire_backend,
                "is_test_injection": audit.is_test_injection,
                "mock_http_attempts": audit.http_attempts if mode == "MOCK_HTTP" else 0,
                "actual_external_network_calls": audit.actual_external_network_calls}
    except BaseException:
        # 捕获的异常可落 UNKNOWN；硬 kill 将保留 RESERVED/HTTP_STARTED，二者也不可复用。
        row = ledger.read(approval.intent["token_id"])
        if row["state"] in {"RESERVED", "HTTP_STARTED"}:
            reservation.transition(row["state"], "UNKNOWN", {"status": "UNKNOWN", "automatic_retry": False})
        raise
    finally:
        if client is not None:
            client.close()
