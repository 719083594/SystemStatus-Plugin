# ServerStatus-Plugin 2.x → SystemStatus-Plugin 3.0.0 迁移指南

> 适用：从旧 Release `v2.0.2` 升级到新版本 `3.0.0`。本指南基于重写提交 `22412367657b4381f9c335ce90a5896510aed79a`。**3.0.0 是破坏性重写，不可直接覆盖旧版安装。**

## 关键差异

| 项目 | 2.0.2 | 3.0.0 |
|---|---|---|
| 安装目录 | `plugins/ServerStatus-Plugin` | `plugins/SystemStatus-Plugin` |
| 功能入口 | Linux 独立 CLI、Node API、Yunzai 适配 | TRSS-Yunzai 入口 + Python HTTP 采集器 |
| 指令 | `#系统`、`#资源`、`#存储`、`#插件`、`#服务`、`#系统帮助` | 仅主人可用的 `#系统状态` |
| 定时清理 | 可选 cleanup.py + systemd timer | 代码中已移除；**旧任务不会因更新插件而自动停用** |
| 最低 Node | 18 | 20 |
| 采集方式 | 原 CLI / IPC 方案 | 宿主机 `GET /v1/status` + Bearer token；周期性快照 |

旧版 `api.mjs`、`scripts/status.py` 和 `collector/cleanup.py` 不再存在；如果依赖它们，请保留 2.x 或先开发替代方案。

## 步骤一：只读核查

在 **Linux 宿主机的 Bash** 执行以下命令（不修改系统）。实际路径与 service 名称以部署现场为准。

```bash
systemctl is-active server-status.service server-status-cleanup.timer qqbot-system-status.service 2>/dev/null || true
ip -4 -o addr show dev docker0 || true
ss -lnt '( sport = :15090 )' || true
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
```

另外确认旧插件目录、service `ExecStart`、机器人版本、Node 版本及 Docker Compose 文件。以上服务名仅来自仓库历史说明，**并未在实际服务器确认**。

## 步骤二：先备份

保留旧插件及配置、旧 collector 配置与 systemd units/timers、Docker Compose 文件及环境变量文件、现有提交号。备份放到私有目录，严格限制读取权限；建议另存一份离机备份。环境变量可能包含登录凭据及 token，**不得推送到公开仓库或发到聊天**。

不要通过 `git reset --hard` 删除本地变更；无需清理 Docker 镜像、数据卷、聊天历史或登录信息。

## 步骤三：旁路部署并验证 v3

1. 保留旧版安装及备份；将 v3 源码安装到 `plugins/SystemStatus-Plugin`，确认插件入口不会和旧版冲突。
2. 按 [v3 安装说明](../README.md) 安装宿主机 `collector/collector.py` 及 `qqbot-system-status.service`；提供的服务文件默认路径为 `/opt/qqbot/system-status/collector.py`，实际位置不同时先修改 `ExecStart`。
3. 配置 `SYSTEM_STATUS_TOKEN`，使采集器的 `envFile` 与 TRSS 容器环境变量匹配。README 中使用 `>>` 追加 token 的示例**不可重复执行**，否则可能存在多条同名变量；先核查再修改。
4. 确认 `docker0` 接口与容器网络实际可达；`172.17.0.1` 不是所有服务器的固定值。必要时按实际 Compose 网络模式调整 `host.docker.internal:host-gateway`。
5. 验证 `/healthz` 返回 `ok`；无 Bearer token 访问 `/v1/status` 应得到 401，有效 token 返回完整快照。不要将 token 输出到公开日志。
6. 主人私聊 `#系统状态` 验证图片；测试图片生成失败的文字回退，以及非主人无法调用。
7. 验收通过后，停止旧插件重复加载。逐一核对旧 `server-status.service`、`server-status-cleanup.timer` 是否仍在运行，**未经管理员明确决定不要停用或删除**。
8. 记录旧、新版本、配置变更、验收结果；验证服务或容器重启后仍正常。

## 验收标准

- 状态图与文字版包含真实 CPU、内存、Swap、磁盘、Docker、机器人和插件数据；主人权限正确。
- 采集器只监听预期受控接口，外网不能未经授权读取数据；无 token 返回 401。
- 采样时间戳准确；**采集失败时可保留较早的快照**，不要把缓存结果视为 15 秒内实时数据。
- 不存在重复插件，旧定时清理任务的去留明确，登录和机器人数据未受影响。

## 回滚

先保留失败日志与新配置快照。根据实际 unit/Compose 名称停止新服务并恢复备份的旧插件、旧采集器和环境变量，再验证旧指令及登录状态。**不要为回滚删除共享容器或数据卷。**

## 验证状态

此迁移指南依据源码和发布记录静态核查；**尚未在你的实际 Linux + Docker + TRSS 环境进行迁移或端到端验证**。v3 工作流与自动化测试结果应独立核验，不能沿用 v2 的绿色测试记录。
