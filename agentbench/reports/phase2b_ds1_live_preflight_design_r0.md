# Phase 2B-DS-1-LIVE-PREFLIGHT-DESIGN-R0

本轮只定义未来一次受控 Provider preflight 的协议边界。没有创建真实 transport，没有读取凭据，没有创建 socket，也没有执行任何 Provider 请求。

## 设计目标

未来的单次 preflight 必须经过 Planner approval、签名授权、fresh repository proof、一次性 ledger reservation、credential callback、生产 transport 构造和审计 sink 检查。全部条件满足后只允许一个 `GET /models`，收到结果并持久化后立即停止。

执行身份绑定 `run_id`、`authorization_id`、`token_id`、`repository_sha`、`protocol_hash`、`transport_mode`、`endpoint`、`allowed_method` 和 `allowed_path`。任何身份变化都拒绝继续。

## 状态机

正常路径为：

`CREATED → AUTHORIZED → FRESHNESS_VERIFIED → RESERVED → CREDENTIAL_ACQUIRED → TRANSPORT_READY → HTTP_STARTED → RESULT_RECEIVED → RESULT_PERSISTED → COMPLETED`

终态为 `COMPLETED`、`REJECTED`、`UNKNOWN` 和 `ABORTED`。`UNKNOWN` 没有 retry、重新 reservation 或重新请求的出口。`RESULT_PERSISTED` 只能进入 `COMPLETED`，不能重新进入 HTTP 阶段。完整状态、允许跳转和拒绝跳转记录在 [state machine JSON](D:/VETM/ResearchCI/agentbench/reports/phase2b_ds1_live_preflight_design_r0_state_machine.json) 中。

## 请求边界

唯一允许的请求是：

- 方法：`GET`
- 路径：`/models`
- 端点：冻结的 DeepSeek models endpoint
- 请求总数：最多一次

`POST /responses`、chat completions、未知路径、额外方法、tool execution、research task 和 benchmark 均拒绝。请求边界在授权指纹、ledger reservation 和 transport 构造前后重复核对。

## Evidence Bundle

允许持久化运行身份、授权指纹、仓库指纹、协议哈希、时间戳、transport 配置摘要、请求元数据、响应元数据、最终状态和失败原因。请求元数据只保存 method、path、endpoint 和时间；响应元数据只保存 HTTP 状态、request id、时间和目标模型存在性。

API key、Authorization header、原始 credential、token value 和完整响应正文禁止落盘。primary audit 使用 hash chain，summary 使用原子写入与读回校验。

## 失败语义

- 签名、仓库 freshness、ledger conflict、endpoint policy：`REJECTED`
- credential failure、network timeout、Provider 5xx、审计持久化失败：`UNKNOWN`
- operator abort：`ABORTED`
- `UNKNOWN` 不重试、不重复消耗 reservation、不再次执行请求

## 真实执行前置条件

目标 Windows/Linux runtime qualification、Planner 明确批准、签名授权、fresh repository proof、一次性 ledger、批准的 credential source、endpoint allowlist 和可写 audit sink 必须全部满足。任一条件失败即停止。

## 当前阻断

本轮没有 Planner approval，没有 live credential，没有真实 Provider request；Windows runtime qualification 仍因 symlink 和完整父目录攻击模型受环境限制。当前明确保持：

`LIVE EXECUTION NOT AUTHORIZED`

`LIVE ACTIVATION BLOCKED`

## 离线验证

`tests/test_live_preflight_design.py` 只加载冻结 JSON 并验证正常状态流、非法跳转、endpoint allowlist、evidence 禁止字段和 failure semantics；不创建 transport、不发起网络、不读取凭据。
