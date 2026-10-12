# Phase 2B-DS-1-LIVE-PREFLIGHT-AUTH-R0

本轮定义未来单次真实 Provider preflight 的授权证明，不执行任何 Provider 请求，不读取 credential，不创建 live transport。

## Authorization Object

授权对象必须包含 authorization id、run id、requester、approver、创建和过期时间、repository SHA、protocol hash、provider、endpoint、method、scope、transport mode、credential policy、audit destination 和 one-use 标志。授权指纹绑定 run identity、提交 SHA、协议 hash 和最小权限 scope，防止旧授权用于新代码或新协议。

## 最小权限

唯一允许范围是 `DeepSeek / GET /models / max_requests=1`。`POST /responses`、chat completion、tool execution、agent execution、benchmark 和 canary 不属于授权范围，任何范围变化都拒绝。

## Approval Workflow

状态路径为：

`REQUESTED → REVIEWING → APPROVED → READY_FOR_EXECUTION → CONSUMED`

失败状态为 `REJECTED`、`EXPIRED`、`REVOKED` 和 `CANCELLED`。`APPROVED` 不会自动执行；Executor 必须等待独立的显式执行触发。一次 reservation 消费后，任何第二次消费都拒绝。

## Credential Policy

未来执行只能从获批准的 credential callback 获取凭据，保存在临时内存中，仅用于该次请求，完成后立即丢弃。API key、token、Authorization header 和 raw secret 禁止写入审计或 summary，也禁止出现在异常和响应正文中。

## Revocation

授权在过期、人工撤销、repository SHA 改变、protocol hash 改变或 scope 改变时失效。结果统一为 `REJECT`，Executor 不得自行重新授权或扩大权限。

## 执行边界与审计

未来顺序固定为：审批 artifact、签名验证、仓库 freshness、一次性 ledger reservation、credential callback、transport 构造、唯一 `GET /models`、Evidence Persist、STOP。Evidence Bundle 只保存授权和审批指纹、run id、提交 SHA、协议 hash、scope、最终状态和失败原因；hash chain 与原子 summary 是强制要求。

## 当前未授权状态

当前没有 Planner approval，没有 live credential，也没有真实 Provider 请求；Windows runtime qualification 仍是环境阻断。因此：

`AUTHORIZATION DESIGNED`

`EXECUTION AUTHORIZATION NOT GRANTED`

`LIVE ACTIVATION BLOCKED`

完整字段和判定规则见 [authorization schema](D:/VETM/ResearchCI/agentbench/reports/phase2b_ds1_live_preflight_auth_r0_schema.json)。
