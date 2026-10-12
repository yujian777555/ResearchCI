# Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-APPROVAL-GRANT-R0

## Decision

最终 grant decision：`HOLD`。

Runtime 已接受为 Linux WSL2 Ubuntu-22.04，scope 固定为 DeepSeek `GET /models`、最多 1 request。Execution Authorization artifact 已定义，但 credential source 为 `NOT PROVIDED`，Planner explicit execution approval 缺失，因此 grant 不能转换为 `GRANTED`。

## Preconditions

未来 Grant 必须绑定：

- accepted Linux runtime
- exact repository SHA
- exact DeepSeek/STATS protocol hashes
- valid Final Approval
- valid Execution Authorization
- explicitly approved credential source
- immutable scope
- ready audit sink

## Execution Scope

唯一允许范围：DeepSeek、`GET`、`/models`、1 request。`POST /responses`、model inference、tool calls、agent tasks 和 benchmark 均禁止。

## Revocation

Grant 在 repository changed、protocol changed、runtime changed、scope changed 或 expiration 时立即失效。Grant 消费后不能 replay，任何第二次消费都拒绝。

## Current blockers

- credential source：`NOT PROVIDED`
- Planner explicit approval：缺失
- Final Approval：HOLD
- Execution Authorization：NOT GRANTED

当前不创建 transport、不调用 callback、不读取凭据、不请求 Provider。`LIVE ACTIVATION BLOCKED` 保持不变。
