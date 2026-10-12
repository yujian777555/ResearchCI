# Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-AUTH-R0

## Execution Authorization Ticket

此工件定义未来一次具体 Provider 请求的票据边界。当前票据是设计占位，状态为 `NOT_GRANTED`，run id 和 expiry 尚未分配，没有 credential source，也没有 Planner execution approval。

票据绑定：

- Final Approval artifact：`phase2b_ds1_live_preflight_final_approval_r0.json`
- repository SHA：`25e9dfccaaf7cf0113746070db16da3b06efe89a`
- DeepSeek/STATS protocol hashes
- runtime：Linux WSL2 Ubuntu-22.04 原生 Linux filesystem
- provider：DeepSeek
- method：`GET`
- endpoint：`/models`
- maximum：1
- ledger：single-use
- credential policy：approved callback only

任何 repository SHA、protocol hash、runtime、scope、approval 或 expiry 变化都会使票据失效。消费后不能回到 READY；EXPIRED、REVOKED、INVALID 和 UNKNOWN 不能进入 READY 或 EXECUTE。

## Approval 与 Execution Authorization

Final Approval 回答“是否可以进入执行阶段”；Execution Authorization 回答“哪一次具体请求可以执行”。流程为：

`Final Approval → Execution Authorization → Credential Injection → Single GET /models → Evidence Persist`

当前 Final Approval 是 HOLD，因此不能生成已授予的执行票据。`NOT_GRANTED` 是有意冻结状态。

## 最小权限与失败关闭

唯一请求是 1 次 DeepSeek `GET /models`。`POST /responses`、其他 endpoint、tool/agent execution、benchmark 和 canary 均拒绝。缺少 approval、credential source 或 runtime qualification 时保持 HOLD；scope、runtime、repository 或 protocol 不匹配时 REJECT；票据重放时 REJECT。

## 审计绑定

未来有效票据必须在消费前写入 run identity、授权指纹、repository SHA、protocol hashes、runtime identity、scope fingerprint、ledger reservation 和 expiry。持久 evidence 只保存元数据、指纹、请求/响应 metadata、最终状态和失败原因。当前没有 Provider 请求、callback 或 transport。

当前状态：`EXECUTION AUTHORIZATION: NOT GRANTED`，`LIVE ACTIVATION: BLOCKED`。
