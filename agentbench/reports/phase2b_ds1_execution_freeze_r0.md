# Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-FREEZE-R0

## Freeze target

本轮把当前 main HEAD `52a643763a072bbc828e335d26f9e65d1ced8ab6` 记录为候选 immutable execution SHA。未来执行必须在该 SHA 对应的固定 checkout 中进行；发布 freeze manifest 的后续提交不能被误认为 execution target。

## Artifact chain

清单保存了 execution config、execution auth、approval、grant 和 credential source 的路径、内容 SHA-256 与 repository SHA。当前五项分别绑定更早提交，未全部等于 freeze SHA，因此链状态为 `CHAIN_INVALID`，执行状态保持 `BLOCKED`。这保留了 stale binding 事实并防止把新清单当作自动批准。

## Hard stop

以下情况在任何 credential 或网络动作之前停止：artifact repository SHA 与 frozen SHA 不一致、Config/Auth/Approval/Grant/Credential 链不一致、credential 提前获取或写入、scope 不是 DeepSeek `GET /models` 单次请求、任何 retry，以及 freeze 后 HEAD 变化。

拒绝路径返回 `REJECT_BEFORE_EXECUTION`、`CHAIN_INVALID`、`SECURITY_ABORT`、`NETWORK_SCOPE_VIOLATION`、`EXECUTION_ABORT` 或 `EXECUTION_INVALIDATED`；这些路径都禁止 callback 和网络。

## Scope

本轮只新增 freeze manifest、离线 hard-stop 测试和审计报告。没有调用 Provider、读取 credential、创建 transport 或修改安全核心。

## Regression

Freeze hard-stop 测试：8 passed。全量 `python -m pytest -q` 收集 638 项，544 passed、90 failed、4 skipped；失败集中在既有 Windows `native_evidence.evidence_lock` 锁文件打开路径（`WinError 80` 后继 `WinError 5`），没有修改冻结安全核心。结果标记为 `ENVIRONMENT_BLOCKED`。
