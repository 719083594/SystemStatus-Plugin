# SystemStatus-Plugin · 系统状态

主人发送 `#系统状态`，机器人回复服务器、磁盘、Docker、机器人账号及已加载插件的状态图。图片生成失败或发送未成功确认时改发文字，不自动重发图片。缺少宿主机数据时，机器人与插件部分仍可使用。

**v3.0.2 完整包同时包含插件和宿主机采集器，两部分分别安装。** 不依赖其他插件；解压下载包不会自动安装、启动或更新服务器上的任何程序。

## 下载完整包

前往 [最新 Release](https://github.com/719083594/SystemStatus-Plugin/releases/latest)，下载 `SystemStatus-Plugin-v3.0.2.zip` 和 `SHA256SUMS.txt`。ZIP 已包含配套的两部分，无需另外找采集器。GitHub 的 `Code → Download ZIP` 是含测试及开发文件的源码包，也包含采集器，目录结构与发布包不同。

完整包解压后：

```text
SystemStatus-Plugin-v3.0.2/
  README.md
  LICENSE
  docs/                             本版说明、2.x 迁移指南
  plugin/
    SystemStatus-Plugin/            整个目录放入 Yunzai 的 plugins/
      index.js
      lib/
      resources/
      config/defaults.json          实例配置另建 config/config.json
      package.json
      plugin.manifest.json
      LICENSE
  collector/                        复制到宿主机，不能当作 Yunzai 插件运行
    collector.py
    config.example.json
    qqbot-system-status.service
```

## 实际部署位置

以下沿用 `/opt/qqbot` 部署方式，路径可按环境调整：

| 部分 | 实际位置 | 如何运行 |
|---|---|---|
| 插件 | `/opt/qqbot/yunzai/plugins/SystemStatus-Plugin/` | TRSS-Yunzai 加载，接收指令并出图 |
| 采集器 | `/opt/qqbot/system-status/collector.py`、`config.json` | Linux 宿主机运行，通过本机 HTTP 提供状态 |
| 采集器服务 | `/etc/systemd/system/qqbot-system-status.service` | systemd 启动、守护，不另建定时任务 |
| token | `/opt/qqbot/.env` | 采集器与 Yunzai 容器共用的连接凭据 |

采集器源码和插件在同一仓库，**运行时不在插件目录中**。它不依赖 Yunzai，重启机器人不会停止宿主机采集。只安装插件不会创建宿主机服务。

## 安装

要求：Linux 宿主机、Docker、Python ≥3.9（标准库）、TRSS-Yunzai（Node ≥20）。TRSS 带 Chromium 时可出图，否则改发文字。CI 使用 Python 3.13 和 Node 20/22/24/26，不代表真实 QQ、Docker 或 Chromium 全流程验收。

先执行 `sha256sum -c SHA256SUMS.txt` 校验，再解压进入 `SystemStatus-Plugin-v3.0.2/`。以下以宿主机 root 执行，Yunzai 目录应已存在。已有部署升级见下方“更新”，保留实例配置与 token。

1. 首次创建 token：

   ```sh
   # 只在不存在 SYSTEM_STATUS_TOKEN 时添加，保留已有 .env 内容。
   install -d -m 700 /opt/qqbot
   touch /opt/qqbot/.env
   if ! grep -q '^SYSTEM_STATUS_TOKEN=' /opt/qqbot/.env; then
     printf '\nSYSTEM_STATUS_TOKEN=%s\n' "$(openssl rand -hex 32)" >> /opt/qqbot/.env
   fi
   chmod 600 /opt/qqbot/.env
   ```

   已有变量不要重复生成；token 至少 32 个字符。勿将实际凭据上传到仓库。

2. 安装宿主机采集器：

   ```sh
   install -d -m 700 /opt/qqbot/system-status
   install -m 700 collector/collector.py /opt/qqbot/system-status/collector.py
   install -m 600 collector/config.example.json /opt/qqbot/system-status/config.json
   install -m 644 collector/qqbot-system-status.service /etc/systemd/system/qqbot-system-status.service
   systemctl daemon-reload
   systemctl enable --now qqbot-system-status.service
   curl --fail http://172.17.0.1:15090/healthz
   ```

   默认 `bind: "docker0"` 解析该网桥实际 IPv4，`172.17.0.1` 仅为示例。`config.json` 的 `envFile` 应指向上一步文件。使用其他部署路径时也要修改服务里的路径。健康返回 `ok`，无有效快照或采样失败返回 HTTP 503。

3. 安装插件目录：

   ```sh
   cp -a plugin/SystemStatus-Plugin /opt/qqbot/yunzai/plugins/
   ```

   不要把整个发布包复制进去。新装插件后重启 TRSS-Yunzai。

4. 在原有 Compose 的 `yunzai` 服务中合并以下内容，保留其余环境变量及配置：

   ```yaml
   environment:
     SYSTEM_STATUS_TOKEN: ${SYSTEM_STATUS_TOKEN}
   extra_hosts:
     - host.docker.internal:host-gateway
   ```

   Compose 从 `/opt/qqbot/.env` 读取 token。修改 Compose 后才重建 Yunzai 容器，例如在 `/opt/qqbot` 执行 `docker compose up -d --no-deps yunzai`。插件默认连接 `http://host.docker.internal:15090`，可用插件的 `config/config.json` 覆盖。需确认此地址映射到采集器监听的网桥地址；若不一致，显式使用能从容器访问的该网桥地址。

5. 主人私聊机器人发送 `#系统状态`，核对图片、在线状态及服务器数据采集时间。

## 采集与异常处理

- 默认每次采集完成后等待 15 秒；若采集耗时约 2.8 秒，两份数据间隔约为 18 秒。请求直接读取内存快照，不等待 Docker 现场采集。
- 最近采样失败时短时间显示上次成功数据，图片与文字明确提示。快照年龄达到 `max(60, 3 × refreshSeconds)` 秒时，`/v1/status` 返回 503；插件提示数据不可用，不展示过期宿主机指标。
- `/healthz` 不需 token，不返回宿主机数据；无快照、采样失败或快照过期返回 503。它检查宿主机采样是否有效，Docker 部分故障通过状态报告单独提示。
- Docker 磁盘占用、镜像估算、容器列表、用量、详情分别容错，一项失败保留其他信息并标注缺失项。最多展示 50 个容器，超出时提示截断。镜像可回收数字为估算，采集器不执行清理。
- CPU 总时间不重复计入 Linux 已包含在 user/nice 中的 guest/guest_nice。
- 生成图片、上传、QQ 接收是不同阶段。此前新加坡整套采集约 2.85 秒、缓存接口约 0.6 毫秒；东京 v3.0.1 回图用户实测约 2 秒。这些既有环境测量不代表本版在所有服务器的发送速度。

## 安全与配置

- 默认监听 Docker 网桥内网地址，拒绝公网 IPv4 和 `0.0.0.0`。实际访问范围仍取决于路由和防火墙。
- `GET /v1/status` 必须带 `Authorization: Bearer <token>`；`/healthz` 是不带数据的健康检查。
- `refreshSeconds` 必须是 5–3600 的有限数字，端口是 1–65535 的整数；错误配置阻止启动。
- HTTP 最多同时处理 16 个连接，读取空闲超时 5 秒，满额时关闭新连接。它不是面向公网的服务。
- 采集器以 root 运行，只执行 Docker 等只读查询，不执行更新、删除或清理。配置及 env 文件应仅 root 可读。
- `#系统状态` 仅主人可用。插件实例配置 `config/config.json` 不进 Git；token 通过容器环境变量取得。

## 更新

升级前备份实例配置与服务单元。完整包包含两部分，但只覆盖需更新的程序文件，不覆盖 `config.json`、`config/config.json` 或 `.env`。

- 采集器：覆盖 `/opt/qqbot/system-status/collector.py`，执行 `systemctl restart qqbot-system-status`，检查健康接口和服务日志。
- 插件：将 `plugin/SystemStatus-Plugin/` 中的文件合并到现有目录，保留实例配置；修改 `lib/` 后重启 TRSS。仅 `index.js` 改动可依靠热加载。
- 只有 Compose 配置变化时才重建对应容器。
- 从 2.x 升级不能直接覆盖旧目录：3.0.0 是不兼容重写，旧独立 CLI、Node API、定时清理已移除。先阅读 [迁移指南](docs/MIGRATION_2_TO_3.md)，备份并核对旧定时任务。
- v3.0.1 包仅含插件本体；从 v3.0.2 起最新完整包包含插件及采集器。旧版本保持原样。

## 源码目录与测试

仓库 `index.js`、`lib/`、`resources/`、`config/defaults.json` 是插件源码；`collector/` 是独立采集器源码和安装材料。`scripts/build-release.py` 按明确清单生成完整包。源码包的插件文件在仓库根目录，完整发布包的插件文件在 `plugin/SystemStatus-Plugin/`。

```sh
npm test
python scripts/build-release.py --output dist
```

自动化覆盖指令权限、配置、数据校验、图片与文字降级、账号状态、采样失败与过期、Docker 部分失败、CPU 解析、HTTP 鉴权及连接限制、完整包内容及校验值。四个 Node 版本 CI 通过后才自动发布对应提交的完整包，不包含实例配置、token、依赖缓存或测试文件。

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE)：可用于个人学习、研究、爱好和非营利用途；修改与转发时附上许可证及 `Required Notice`。不允许商业用途。
