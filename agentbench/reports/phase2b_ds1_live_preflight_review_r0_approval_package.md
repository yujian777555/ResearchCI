# Controlled Live Preflight Approval Package

## Executive Summary

ResearchCI Controlled Live Preflight 的目的，是在未来进行一次最小权限的 Provider 可用性验证。请求范围固定为 DeepSeek 的 `GET /models`，最多 1 request，完成后立即停止。此包用于 Planner 人工判断，不构成执行授权。

当前结论：`APPROVAL PACKAGE READY`，`EXECUTION AUTHORIZATION NOT GRANTED`，`LIVE ACTIVATION BLOCKED`。

## Security Evidence Summary

### Authorization

状态：PASS。已完成 authorization schema、scope binding、expiration、revocation 和 one-use 设计。授权对象绑定 run identity、repository SHA、protocol hash 和最小权限范围。

### Evidence Integrity

状态：PASS。现有证据链包含 audit hash chain、summary atomic write、fd identity validation 和 evidence persistence。授权包只引用指纹、哈希、状态和元数据，不携带敏感凭据内容。

### TOCTOU Protection

状态：PASS。SEC-FIX-R1 已验证基于父目录 fd 的相对打开、`O_NOFOLLOW`、`O_CLOEXEC`、opened-fd identity validation，以及 device/inode/type/mode 比较。Linux 真实 replacement、parent replacement 和 summary publish 场景通过。

### Runtime Validation

- Linux：PASS
- Windows：PENDING
- 原因：symlink privilege unavailable；完整 parent replacement attack model 受 Windows 环境句柄共享限制

## Requested Action

未来若 Planner 单独批准，唯一请求为：

- Provider：DeepSeek
- Method：`GET`
- Endpoint：`/models`
- Maximum calls：1
- 目的：验证 credential validity、transport availability 和 endpoint accessibility

## Explicit Non-Goals

本授权包明确排除：`POST /responses`、model inference、agent execution、tool call、benchmark、canary 和 research task execution。

## Execution Preconditions

未来执行必须同时满足：

1. Planner Approval exists
2. Signed authorization valid
3. Repository SHA matches
4. Protocol hashes match
5. Runtime qualification accepted
6. One-use ledger available
7. Credential source approved
8. Audit sink available

任一条件失败：`NO EXECUTION`。

## Credential and Evidence Boundary

未来凭据只能由获批准的 callback 提供，短暂存在于内存中，请求结束立即丢弃。审计中只允许保存 authorization fingerprint、approval fingerprint、run id、repository SHA、protocol hash、scope、final state 和 failure reason。原始凭据、敏感认证材料和完整响应正文不得写入 evidence。

## Approval Decision Template

```text
APPROVAL DECISION

Request: DeepSeek GET /models, maximum 1 call
Scope: single controlled live preflight
Risk: see risk register
Evidence: see authorization schema and frozen runtime reports
Decision: [ APPROVE ] [ REJECT ] [ HOLD ]
Reason:
Approver:
Timestamp:
```

当前不填写 APPROVE。Planner 尚未授予执行授权。

## Current Blockers

- No planner approval
- No live credential
- No real provider request
- Windows runtime qualification pending

## Supporting Artifacts

- `agentbench/reports/phase2b_ds1_live_preflight_auth_r0_schema.json`
- `agentbench/reports/phase2b_ds1_live_preflight_design_r0_state_machine.json`
- `agentbench/reports/phase2b_ds1_r5_1_env_closeout_r1_recheck_security_review.md`
- `agentbench/reports/phase2b_ds1_r5_1_env_closeout_r1_recheck_scope_audit.json`
