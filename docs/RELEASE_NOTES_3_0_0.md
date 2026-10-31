# SystemStatus-Plugin v3.0.0

首次以 **SystemStatus-Plugin** 名称发布的 3.x 版本。与 **ServerStatus-Plugin 2.x 不兼容**，不要直接覆盖旧版。

## 新功能
- 主人发送 `#系统状态`，汇总 Linux 主机 CPU、内存、Swap、负载、磁盘、Docker 容器与存储占用，以及 TRSS-Yunzai 机器人账号和已加载插件。
- 使用 TRSS 自带 Chromium 生成完整图片；图片渲染失败时回退为文字消息。
- Python 标准库宿主机采集器后台按默认 15 秒刷新数据，通过 Bearer token 保护的本机 HTTP API 提供快照。若采集出错，可能保留更早的快照。
- 插件核心 `lib/` 与 TRSS 接入层 `index.js` 分离；提供 `plugin.manifest.json`。

## ⚠️ 从 2.x 升级须知
- 安装目录改为 `plugins/SystemStatus-Plugin`，新指令为 `#系统状态`；旧版 `#系统`、`#资源`、`#存储`、`#插件`、`#服务` 等指令不再保留。
- 旧版独立 Linux JSON/PNG CLI、`api.mjs`/Node API 和定时清理功能在 3.0.0 中已移除。
- 旧 systemd 清理定时任务不会随安装新插件自动停止，请人工核对。
- 当前针对 **Linux 宿主机 + Docker 中的 TRSS-Yunzai**，要求 Node.js ≥20、Python 3；默认使用宿主机 `docker0` 接口（地址以实际环境为准）。
- 安装或迁移前务必备份旧配置、服务单元、环境变量以及 Docker Compose 文件；不要将 token、账号或其他凭据上传到公开仓库。

详细操作：[README](https://github.com/719083594/SystemStatus-Plugin/blob/main/README.md) · [2.x → 3.0 迁移指南](https://github.com/719083594/SystemStatus-Plugin/blob/main/docs/MIGRATION_2_TO_3.md)。

## 测试与已知限制
- GitHub Actions 已通过 Node.js **20 / 22 / 24 / 26** 和 Python **3.13** 单元测试；发布流水线还会重新测试源码与 ZIP 包。
- **尚未对真实 Linux + Docker + TRSS 服务器执行端到端集成测试。** 本版本正式发布不代表已验证你的服务器部署。
- 系统状态中的 Docker 可回收空间为估算值；请勿据此自动清理数据。

## 下载与校验
附件 **SystemStatus-Plugin-v3.0.0.zip** 为包含 `SystemStatus-Plugin/` 顶层目录的完整源码/安装材料，含采集器、插件代码、测试、许可证和迁移指南。`SHA256SUMS.txt` 可用于核对 ZIP 完整性。

许可证：**PolyForm Noncommercial 1.0.0**，仅允许非商业用途。
