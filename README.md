# SystemStatus-Plugin · 系统状态

主人发 `#系统状态`，机器人回复一张图，包含全部状态：服务器（系统、CPU、内存、Swap、负载）、磁盘、Docker（占用与每个容器）、机器人账号、已加载的插件。图片生成失败时自动改发文字版。

不依赖任何其他插件。分两部分：

| 部分 | 位置 | 作用 |
|---|---|---|
| 采集器 | `collector/`，跑在服务器系统上 | 读 `/proc`、磁盘和 `docker` 命令，只读不改。**每 15 秒在后台采集一次**（`refreshSeconds`），通过本机 HTTP 接口 `GET /v1/status` 立即返回最新一份，要带 token。某次采集失败时继续提供上一份 |
| 插件 | 其余文件，放进 TRSS 的 `plugins/` | 收到指令后向采集器要数据，加上机器人自己知道的信息，生成一页 HTML，交给 TRSS 自带的 Chromium 截图后发出 |

## 目录

```
SystemStatus-Plugin/
  plugin.manifest.json   插件说明书（橙汁等程序读取）
  index.js               TRSS 接入层，唯一认识 TRSS 的文件
  lib/                   核心逻辑，不依赖任何框架
    command.mjs          指令正则（接入层和测试共用）
    config.mjs           读取配置
    client.mjs           向采集器发请求
    html.mjs             生成状态图的整页 HTML（内联样式，无脚本、无外链）
    format.mjs           文字版（图片失败时用）和共用的格式化函数
  resources/status.html  固定一行的截图模板 {{@ html}}
  config/defaults.json   默认配置；实例配置写在 config/config.json（不进 Git）
  collector/             宿主机采集器（Python 标准库）+ systemd 单元 + 配置示例
  tests/                 Node 与 Python 测试
```

## 速度

在一台 2 核云服务器上实测：`docker stats` 单次约 2 秒，整套采集约 2.7 秒；Chromium 截一张图约 0.33 秒（机器人重启后第一次另需约 0.7 秒启动浏览器）。采集放在后台后，发指令到出图约 0.35 秒；图上会写明数据采集时间，正常采样时通常不超过 15 秒；采样失败时可能继续显示更早的快照。

## 安全

- 采集器只监听 `docker0` 网桥地址（通常是 `172.17.0.1`），外网访问不到，只有本机和容器能连。
- 每个请求都要带 `Authorization: Bearer <token>`。token 存在服务器上的一个 env 文件里（`config.json` 的 `envFile`，变量名 `SYSTEM_STATUS_TOKEN`），插件通过容器环境变量拿到，不写进插件文件，也不进 Git。
- 采集器只执行只读命令：`docker system df`、`docker ps`、`docker stats --no-stream`、`docker inspect`。它以 root 运行，因为要读 Docker。
- 指令只有主人能用。

## 安装

要求：Linux 宿主机、Docker、Python 3（只用标准库）；TRSS-Yunzai 跑在 Docker 容器里，并带 Chromium（没有也能用，会改发文字版）。下面的路径是示例，按自己的部署改。

1. 生成 token，写进一个只有 root 能读的 env 文件：
   ```sh
   echo "SYSTEM_STATUS_TOKEN=$(openssl rand -hex 32)" >> /opt/qqbot/.env && chmod 600 /opt/qqbot/.env
   ```
   **注意：只在首次创建 token 时运行；重复执行会追加同名变量。已有 `.env` 时先检查并保留其它配置，不要直接重复运行。**
2. 采集器：把 `collector/collector.py` 放到 `/opt/qqbot/system-status/`，把 `config.example.json` 复制成同目录的 `config.json`（`envFile` 指向第 1 步的文件），再安装并启用服务：
   ```sh
   cp collector/qqbot-system-status.service /etc/systemd/system/
   systemctl daemon-reload && systemctl enable --now qqbot-system-status
   curl http://172.17.0.1:15090/healthz   # 应返回 ok
   ```
3. 插件：把本目录（不含 `collector/`、`tests/`）放进 TRSS 的 `plugins/SystemStatus-Plugin/`。
4. 在 TRSS 容器的 compose 配置里加上 token 和宿主机地址，然后重建容器：
   ```yaml
   environment:
     SYSTEM_STATUS_TOKEN: ${SYSTEM_STATUS_TOKEN}
   extra_hosts:
     - host.docker.internal:host-gateway
   ```
5. 主人私聊机器人发 `#系统状态`。

## 从 2.x 升级

**3.0.0 是不兼容重写，不能直接覆盖 2.x 目录。** 旧版独立 CLI、Node API 和定时清理功能已移除。从 2.x 升级前，请先阅读 [迁移指南](docs/MIGRATION_2_TO_3.md) 并备份配置、检查旧定时任务。

## 更新

- 改了 `collector/collector.py`：覆盖后 `systemctl restart qqbot-system-status`。
- 改了 `lib/` 里的文件：覆盖后要重启 TRSS；TRSS 热加载只会重新读 `index.js`，不会重读它引用的文件。
- 只有改了 compose 配置才需要重建容器。

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE)：可以免费用于个人学习、研究、爱好和非营利用途，可以修改和转发（转发时附上许可证和开头的 `Required Notice` 一行）；**不允许商业用途**。

## 测试

```sh
npm test
```

Node 测试检查图片页面（每张卡片都在、颜色阈值、昵称等文字已转义、没有脚本和外链）、文字版、配置读取、请求错误提示，以及 `plugin.manifest.json` 里的每条指令都能被真实规则匹配。Python 测试检查 `/proc` 解析、token 校验、后台采集（失败时保留上一份）和镜像"可回收"的自算逻辑（不信 Docker 自带的数字）。
