# SystemStatus-Plugin · 系统状态

为 **TRSS-Yunzai** 提供一张系统状态图。主人发送 `#系统状态`，即可查看 Linux 宿主机、Docker 容器、机器人账号和已加载插件的状态；图片生成或发送失败时自动转为文字。

**机器人端依赖 TRSS-Yunzai。** 宿主机采集器独立运行，核心格式化与 HTML 生成不依赖框架；当前提供的机器人接入层只有 TRSS-Yunzai，其他框架需要另行适配。

[功能](#功能) · [下载](#下载) · [安装](#安装) · [配置](#配置) · [更新](#更新) · [常见问题](#常见问题) · [测试与验证范围](#测试与验证范围)

## 功能

| 部分 | 展示内容 |
|---|---|
| 宿主机 | 主机名、系统与内核、运行时间、CPU 平均占用、核心数、系统负载 |
| 内存 | 物理内存总量、已用和可用容量，以及 Swap 使用情况 |
| 磁盘 | 挂载点、文件系统类型、总容量、已用和可用空间 |
| Docker 容器 | 运行状态、健康状态、重启次数、CPU 和内存用量 |
| Docker 存储 | 镜像、容器、数据卷和构建缓存占用；镜像可回收空间估算 |
| 机器人 | 账号、昵称、适配器、连接与在线状态、框架和 Node 版本、进程内存及运行时间；框架提供时显示收发消息计数 |
| 插件 | 实际加载的插件名称与版本 |

当前指令为 **`#系统状态`**，群聊和私聊均可使用，权限限机器人主人。主人身份由 TRSS-Yunzai 的配置确定。协议连接、QQ 在线和账号异常分别判断；没有可靠信息时显示未知。

报告默认发送 PNG。缺少宿主机数据时，仍可显示机器人与插件信息；图片生成失败、发送抛错或回执未成功确认时转为文字，不自动重发图片。

## 运行结构

完整包包含两个部分，需要分别安装：

| 部分 | 安装位置示例 | 职责 |
|---|---|---|
| TRSS 插件 | `/opt/qqbot/yunzai/plugins/SystemStatus-Plugin/` | 接收指令、读取机器人信息、生成并发送报告 |
| 宿主机采集器 | `/opt/qqbot/system-status/` | 读取 Linux 与 Docker 指标，通过内网 HTTP 接口提供快照 |
| systemd 服务单元 | `/etc/systemd/system/qqbot-system-status.service` | 启动、守护采集器 |
| 连接凭据 | 示例为 `/opt/qqbot/.env` | 为采集器和机器人提供同一个 token |

采集器不依赖 TRSS，重启机器人不会停止宿主机采集。只安装插件时，机器人部分可以工作，完整的服务器指标还需要采集器。

### 环境要求

- **机器人端**：TRSS-Yunzai、Node.js ≥20。图片使用框架自带渲染器；无可用渲染器时发送文字。
- **采集端**：Linux 宿主机、Python ≥3.9、Docker CLI；示例使用 systemd 管理服务。Python 采集器只使用标准库，无需额外安装 Python 库。
- **网络**：机器人容器能够访问采集器绑定的宿主机内网地址和端口。

采集器应运行在宿主机上；放进普通机器人容器后，看到的系统环境和权限范围可能不同。当前未提供 Windows/macOS 宿主机采集实现。

## 下载

前往 [v3.0.2 Release](https://github.com/719083594/SystemStatus-Plugin/releases/tag/v3.0.2)，下载：

- `SystemStatus-Plugin-v3.0.2.zip`：插件与采集器完整包。
- `SHA256SUMS.txt`：下载校验文件。

在两份下载文件所在目录执行：

```sh
sha256sum -c SHA256SUMS.txt
unzip SystemStatus-Plugin-v3.0.2.zip
cd SystemStatus-Plugin-v3.0.2
```

解压后的主要内容：

```text
SystemStatus-Plugin-v3.0.2/
  README.md
  LICENSE
  docs/
  plugin/SystemStatus-Plugin/       TRSS 插件目录
    index.js
    lib/
    resources/
    config/defaults.json
    package.json
    plugin.manifest.json
  collector/                       宿主机安装材料
    collector.py
    config.example.json
    qqbot-system-status.service
```

`Code → Download ZIP` 和 Git 克隆得到的是**源码目录**：插件的 `index.js`、`lib/` 等位于仓库根目录，采集器位于 `collector/`。它与 Release 完整包的目录结构不同。下载或解压均不会自动安装服务。

## 安装

以下为**首次安装**示例，以宿主机 root 执行，假设 TRSS 已位于 `/opt/qqbot/yunzai`。路径、Compose 服务名、网桥地址应按实际环境调整；已有部署请使用[更新步骤](#更新)，保留实例配置。

### 1. 准备连接 token

采集器和机器人必须使用同一个、至少 32 字符的 token。下面只在变量不存在时添加，保留 `.env` 中其他内容：

```sh
umask 077
mkdir -p /opt/qqbot
touch /opt/qqbot/.env
if ! grep -q '^SYSTEM_STATUS_TOKEN=' /opt/qqbot/.env; then
  printf '\nSYSTEM_STATUS_TOKEN=%s\n' "$(openssl rand -hex 32)" >> /opt/qqbot/.env
fi
chmod 600 /opt/qqbot/.env
```

已有 token 直接复用，避免重复写入同名变量。实际 token、`.env` 和实例配置不应上传到公开仓库。

### 2. 安装宿主机采集器

在完整包的解压目录中执行：

```sh
if [ -e /opt/qqbot/system-status/config.json ] || [ -e /etc/systemd/system/qqbot-system-status.service ]; then
  printf '%s\n' '发现已有采集器配置或服务，请按更新步骤处理。'
else
  install -d -m 700 /opt/qqbot/system-status
  install -m 700 collector/collector.py /opt/qqbot/system-status/collector.py
  install -m 600 collector/config.example.json /opt/qqbot/system-status/config.json
  install -m 644 collector/qqbot-system-status.service /etc/systemd/system/qqbot-system-status.service
fi
```

先核对采集器的 `config.json`：`envFile` 指向保存 token 的文件，`bind` 指向可用网桥或内网 IPv4。默认 `docker0` 会解析该网桥的实际 IPv4。如果改变安装路径，还需同步修改服务单元中的 `ExecStart`。

确认后启动：

```sh
systemctl daemon-reload
systemctl enable --now qqbot-system-status.service
```

例如网桥实际地址为 `172.17.0.1` 时，可在宿主机检查：

```sh
curl --fail http://172.17.0.1:15090/healthz
```

正常返回 `ok`。示例 IP 并非所有环境的默认值；健康检查成功仅说明宿主机侧可访问，容器侧仍需核对路由和防火墙。

### 3. 安装 TRSS 插件

```sh
if [ -e /opt/qqbot/yunzai/plugins/SystemStatus-Plugin ]; then
  printf '%s\n' '发现已有插件目录，请按更新步骤处理。'
else
  cp -a plugin/SystemStatus-Plugin /opt/qqbot/yunzai/plugins/
fi
```

将完整包中的 `plugin/SystemStatus-Plugin/` 放入框架的 `plugins/`。源码仓库的安装方式则是将仓库根目录作为 `plugins/SystemStatus-Plugin/` 使用。

### 4. 配置 Docker 中的机器人

在原 Compose 的 `yunzai` 服务中合并以下字段，保留原有环境变量、挂载及其他配置：

```yaml
environment:
  SYSTEM_STATUS_TOKEN: ${SYSTEM_STATUS_TOKEN}
extra_hosts:
  - host.docker.internal:host-gateway
```

示例 Compose 目录为 `/opt/qqbot`，从同目录的 `.env` 读取 token。修改 Compose 后更新对应容器：

```sh
cd /opt/qqbot
docker compose up -d --no-deps yunzai
```

插件默认连接 `http://host.docker.internal:15090`。该名称解析的宿主机地址必须与采集器监听地址相符且可达；必要时通过插件的 `config/config.json` 指定实际内网地址。防火墙仅放行机器人网桥到采集器指定地址和端口的访问。

没有修改 Compose 时，安装或升级插件后重启 TRSS 进程即可。新环境还需确认主人身份已在框架中配置。

### 5. 验收

主人发送 `#系统状态`，检查服务器、磁盘、Docker、机器人账号和插件信息，以及报告底部的采集时间。容器健康、协议连接和 QQ 账号在线是不同状态，应分别核对。

## 配置

### 插件：`config/config.json`

默认配置来自 `config/defaults.json`。可在插件目录新建 `config/config.json`，仅覆盖需要修改的字段；实例配置已被 Git 忽略。

| 字段 | 默认值 | 说明 |
|---|---|---|
| `collectorUrl` | `http://host.docker.internal:15090` | 采集器地址，支持 HTTP/HTTPS |
| `timeoutMs` | `10000` | 请求等待上限，1000～60000 毫秒的整数 |
| `tokenEnv` | `SYSTEM_STATUS_TOKEN` | 从哪个机器人环境变量读取 token，配置中填写变量名 |
| `timeZone` | `Asia/Shanghai` | 报告时区，使用有效时区名称，如 `UTC` |

实例配置按次读取，保存后下次查询生效。token 的实际值通过机器人进程环境传入。

### 采集器：`/opt/qqbot/system-status/config.json`

| 字段 | 示例 / 默认值 | 说明 |
|---|---|---|
| `bind` | `docker0` | 网桥名称或内网/回环 IPv4，不接受公网或全零监听地址 |
| `port` | `15090` | 1～65535 的整数 |
| `envFile` | `/opt/qqbot/.env` | 必填，保存 token 的文件路径 |
| `envKey` | `SYSTEM_STATUS_TOKEN` | 文件中的变量名，须与机器人 token 值对应 |
| `refreshSeconds` | `15` | 每次采集完成后的等待秒数，5～3600 的有限数字 |

修改后重启 `qqbot-system-status.service`。示例服务以 root 运行；Docker socket 访问本身具有较高权限，配置和凭据文件应限制读取。采集器仅执行只读查询，不提供清理、删除或更新操作。

### 缓存与错误处理

- CPU 采样间隔为 0.5 秒；默认每次完整采集完成后再等待 15 秒，因此两份数据的时间差包含采集耗时。查看状态时直接读缓存。
- 最近采集失败时，短时间保留上次成功结果并标注异常；快照年龄达到 `max(60, 3 × refreshSeconds)` 秒后，状态接口返回 503。
- Docker 存储汇总、镜像估算、容器列表、用量和详情分别容错；一项失败仍保留其他信息，并提示缺失项。最多展示50个容器。
- 镜像可回收空间按未被任何容器使用的镜像估算；未知容器引用数不会当作可回收。估算不意味着执行清理。
- 磁盘采集按设备去重，当前包含 ext2/ext3/ext4、XFS、Btrfs 和 ZFS 文件系统。
- `/v1/status` 使用 Bearer token 鉴权；`/healthz` 不返回宿主机数据。无快照、采样失败或过期时，健康检查返回503；Docker 分项故障另在报告中提示。
- HTTP 活跃连接上限16个，空闲读取超时5秒。访问范围还取决于路由与防火墙，应限定在可信内网。

## 更新

升级前备份插件实例配置、采集器配置、token 文件及服务单元。程序文件和实例数据分别处理：

| 内容 | 更新方式 |
|---|---|
| 插件程序 | 将新包的 `plugin/SystemStatus-Plugin/` 合并到现有目录，保留 `config/config.json`，然后重启 TRSS |
| 采集器程序 | 用新包的 `collector/collector.py` 更新宿主机对应文件，然后重启采集器 |
| 配置与凭据 | 保留既有 `config/config.json`、采集器 `config.json` 和 `.env`，按需要补充字段 |
| 服务单元 / Compose | 仅在这些定义实际变化时更新；修改单元后执行 `systemctl daemon-reload`，修改 Compose 后更新对应容器 |

Git 克隆安装的插件可在仓库目录执行 `git pull --ff-only` 拉取源码。**Git 拉取不会自动更新已复制到其他位置的采集器，也不会自动重启服务。** 本地源码有改动时先核对差异，保留自己的修改。

本插件未提供 QQ 更新指令。Release ZIP 安装的目录不带 Git 记录，按上表合并更新即可。更新后重新检查采集器健康和 `#系统状态` 回图。

从2.x迁移请先阅读[迁移指南](docs/MIGRATION_2_TO_3.md)：3.x 为不兼容重写，旧独立 CLI、Node API 和定时清理已移除；旧定时任务需要单独核对。v3.0.1 的发布附件只有插件，从 v3.0.2 起完整包包含配套采集器。

## 常见问题

| 现象 | 优先检查 |
|---|---|
| 指令没有回复 | TRSS 是否加载插件、账号是否被框架识别为主人、群或账号配置是否禁用了该功能 |
| 只显示机器人和插件 | 采集器服务、内网监听地址、容器到宿主机的连通性、token 环境变量 |
| 提示拒绝访问 | 采集器文件中的 token 与机器人进程环境是否一致，修改环境后容器是否已更新 |
| 提示无有效数据或已过期 | 采集器是否首次采集成功、最近采样是否失败；查看服务日志 |
| Docker 部分信息缺失 | Docker CLI、daemon、访问权限及具体失败项；缺失数据不能按零处理 |
| 发送文字而非图片 | 框架渲染器是否可用，或图片发送是否失败/未成功确认 |
| 账号显示“已连接，在线状态未知” | 框架只提供了协议连接证据，未提供明确的 QQ 在线状态 |
| 生成图片很快但收图很慢 | 分别观察采集、渲染、OneBot/NapCat 上传和 QQ 送达耗时 |

采集器日志：

```sh
systemctl status qqbot-system-status.service --no-pager
journalctl -u qqbot-system-status.service -n 50 --no-pager
```

## 测试与验证范围

当前 CI 在 **Linux / Ubuntu** 上运行 Node **20、22、24、26** 和 Python **3.13**。Windows 未加入该工作流，采集器本身面向 Linux。

自动化覆盖命令权限、配置与数据校验、图片/文字降级、账号状态、CPU 解析、采样失败与过期、Docker 分项故障、HTTP 鉴权与连接限制，以及完整包内容和校验值。开发环境可执行：

```sh
node --test
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/build-release.py --output dist
```

`npm test` 同时运行 Node 与 Python 测试，要求命令 `python` 指向受支持的 Python 3。发布流程在四个 Node 版本的 CI 成功后打包；已存在的版本标签和附件保持原样。仅更新 README 不改变程序版本或重发既有附件。

v3.0.2 后续已在一套 Linux＋Docker＋TRSS 环境完成采集、鉴权、缓存更新及 QQ 回图验收，单次端到端处理约1.93秒、渲染约237毫秒，用户收图约2秒。该记录说明对应环境的验收结果，其他服务器仍应实际验证；图片生成速度与平台送达速度分别计算。

版本变更见 [v3.0.2 发布说明](docs/RELEASE_NOTES_3_0_2.md)。发布说明记录当时的验证范围，后续实机验收与 CI 结果分别说明。

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE)。使用、修改及再分发的范围与限制以许可证全文为准，并保留许可证与 `Required Notice`。
