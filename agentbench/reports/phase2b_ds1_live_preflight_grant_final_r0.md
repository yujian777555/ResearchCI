# Phase 2B-DS-1-LIVE-PREFLIGHT-GRANT-FINAL-R0

## Grant decision

本工件把指定 repository SHA、Linux WSL2 runtime、执行配置、执行授权、credential source 和最小请求 scope 绑定在一个一次性 Grant 中。当前状态为 `HOLD`，不会转换为 `GRANTED`。

- execution target：`1fa9b1958993c9a89c6001036ead6fdb88064c28`
- publication commit：`24326dcdbc074e4d4f201ac49f4bbd686cb40284`
- runtime：Linux WSL2 Ubuntu-22.04
- Provider：DeepSeek
- scope：`GET /models`，最多 1 request
- credential source：`environment_callback`，引用 `DEEPSEEK_API_KEY`
- credential value：`NOT_ACQUIRED`

## Binding and state

Execution config、execution auth、approval 和 credential source binding 均通过 SHA 与当前 execution target 绑定。Grant 状态机为 `CREATED → VALIDATED → HOLD → GRANTED → CONSUMED → DESTROYED`；本轮停在 `VALIDATED → HOLD`。

Grant 只有在未来获得明确人工批准、完成一次性 reservation 且 credential 仍未泄露时才可进入 `GRANTED`。当前 Grant 不可消费，第二次消费、scope 改变、旧 SHA、运行时改变和任何 credential acquisition 尝试均拒绝。

## Execution boundary

唯一允许的未来动作是一次 DeepSeek `GET /models`。`POST /responses`、其它 endpoint、tool call、agent execution、benchmark、canary 和任何自动重试均不在 Grant 范围内。网络访问当前为 false。

Credential 只允许由 lazy callback 在获批后进入内存，不能写磁盘、日志、audit、summary、report 或异常消息；本轮没有调用 callback，也没有读取环境变量。

## Offline evidence

离线测试覆盖当前 SHA 绑定、旧 SHA 拒绝、scope mutation 拒绝、credential acquisition 拒绝、Grant replay 拒绝和零 Provider/网络/credential 计数。

Execution status 保持 `BLOCKED`。

## Regression

Grant 离线测试：10 passed。全量 `python -m pytest -q` 收集 621 项，527 passed、90 failed、4 skipped；失败集中在既有 Windows `native_evidence.evidence_lock` 锁文件打开路径（`WinError 80` 后继 `WinError 5`），没有修改冻结安全核心。该结果标记为 `ENVIRONMENT_BLOCKED`，不能宣称全量回归通过。

## Scope

本轮仅新增 Grant 工件和离线测试；授权、secure IO、native evidence、ledger、协议、科研代码与历史报告均未修改。真实 Provider API、网络、credential、callback、canary 和 benchmark 计数均为 0。
