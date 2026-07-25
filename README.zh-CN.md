# Apervia

<p align="right">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

<p align="center">
  <img src="docs/images/apervia-icon.png" width="96" height="96" alt="Apervia 图标">
</p>

<p align="center"><strong>面向个人与团队的 Docker 原生智能工作空间</strong></p>

<p align="center">
  将对话、知识库、文件、模型与 MCP 工具统一到可持续维护的私有工作空间中，并通过隔离沙盒安全执行代码和文件任务。
</p>

<p align="center">
  <a href="#apervia-统一了什么">产品概览</a> ·
  <a href="#产品界面">界面导览</a> ·
  <a href="#安装与验证">安装</a> ·
  <a href="#启用隔离沙盒">沙盒</a> ·
  <a href="#文档">文档</a> ·
  <a href="#生产环境检查清单">生产检查</a>
</p>

<p align="center">
  <a href="https://github.com/wdyh1314520-gif/apervia-open-source/actions/workflows/publish-images.yml"><img src="https://github.com/wdyh1314520-gif/apervia-open-source/actions/workflows/publish-images.yml/badge.svg" alt="验证与镜像发布状态"></a>
  <img src="https://img.shields.io/badge/version-1.0.3-6C86BD" alt="Apervia 1.0.3">
  <img src="https://img.shields.io/badge/Docker-amd64%20%7C%20arm64-2496ED?logo=docker&logoColor=white" alt="Docker amd64 与 arm64">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
</p>

> Apervia 是依据 [MIT License](LICENSE) 发布的开源软件。

![Apervia 桌面登录页](docs/images/login-desktop.png)

## Apervia 统一了什么

| 区域 | 可用能力 | 维护边界 |
| --- | --- | --- |
| 对话 | 持久与临时会话、搜索、分享、图片上下文和活动详情 | 历史与数据按账号归属 |
| 模型 API | 独立的 Chat Completions 与 Responses 配置、流式输出、推理和工具调用 | 两种协议不复用彼此的请求链路 |
| 知识与文件 | 会话附件、长期资料库、知识库、预览和生成文件 | 服务端统一执行所有权、配额与存储限制 |
| MCP | 服务目录、OAuth + PKCE、凭据加密、工具扫描、风险分级和逐次授权 | 保留私网地址检查与明确权限等级 |
| 沙盒 | 临时代码与文档执行，支持 Playwright、LibreOffice、OCR、PDF 和 Office 处理 | App 不持有 Docker Socket，任务容器隔离且用完即删 |
| 后台 | 账号审核、角色、会话、配额、文件、知识库、MCP、回收站、备份、审计、维护与限流 | 全部集中在 `/admin` |
| 交付 | Compose、amd64/arm64 镜像、健康检查、SBOM、provenance 与版本发布 | App 与 Sandbox 使用同一版本发布 |

## 架构与安全边界

![Apervia Docker 安全执行架构](docs/images/architecture.png)

App 只挂载持久化数据卷。Docker Socket 仅提供给内部 `sandbox-runner`，Runner 不映射宿主端口；普通执行容器强制禁网，只能访问当前任务的临时卷，执行完成后容器和临时卷都会清理。

## 产品界面

登录后，模型选择、对话输入、文件入口和历史会话集中在同一个工作区：

![Apervia 登录后工作区](docs/images/workspace-desktop.png)

模型 API、Chat Completions、Responses、联网、MCP、图片和账户设置按功能分组管理：

![Apervia 设置界面](docs/images/settings-desktop.png)

完整操作请阅读 [用户指南](docs/USER_GUIDE.md)；账号审核、权限、配额、备份和审计请阅读 [管理员指南](docs/ADMIN_GUIDE.md)。

账号与平台运维统一在同一个后台中管理：

![Apervia 统一后台](docs/images/admin-desktop.png)

每个镜像版本都包含双语站内公告。点击确认会按账号记录已读，仅关闭卡片只会在当前页面暂时隐藏：

![Apervia 版本公告](docs/images/release-announcement-desktop.png)

## 安装与验证

### 选择部署范围

| 范围 | 服务 | 适用场景 |
| --- | --- | --- |
| 仅 App | `app` | 对话、模型、文件、知识库、联网与 MCP，不需要本地代码执行 |
| App + Sandbox | `app`、`sandbox-runner`、执行镜像 | 需要隔离代码、浏览器、Office、PDF、OCR 和文档生成任务 |

建议先启动 App，确认登录和模型对话正常后再启用 Sandbox。

### 1. 准备主机

- Docker Engine 24+ 或 Docker Desktop
- Docker Compose v2
- 建议至少 8 GB 内存；启用沙盒和文档处理时建议 16 GB

```bash
git clone https://github.com/wdyh1314520-gif/apervia-open-source.git
cd apervia-open-source
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
Copy-Item .env.example .env
```

如果仓库或 GHCR Package 为私有，请先登录：

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

### 2. 配置 App

编辑 `.env`：

```dotenv
APP_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source:latest
APP_PULL_POLICY=always
SANDBOX_DOCKER_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:latest
APP_BIND_IP=127.0.0.1
TRUST_PROXY_X_FOR=0
APP_HOST_PORT=8002
AUTH_SIGNUP_ENABLED=1
AUTH_DEFAULT_ROLE=pending
SANDBOX_TOOLS_ENABLED=0
```

仅本机使用时保持 `APP_BIND_IP=127.0.0.1`。需要局域网访问时再改为明确的网卡地址或 `0.0.0.0`，并同时配置防火墙、反向代理和 TLS。

默认保持 `TRUST_PROXY_X_FOR=0`。只有 App 绑定到 `127.0.0.1`，并且唯一入口恰好是一层可信反向代理时，才设置为 `1`；App 直接通过 `0.0.0.0` 暴露时不要启用。

### 3. 启动并验证 App

```bash
docker compose pull app
docker compose up -d app
docker compose ps
docker compose logs --tail 100 app
curl --fail http://127.0.0.1:8002/api3/health/ready
```

打开 [http://127.0.0.1:8002](http://127.0.0.1:8002)。在全新数据卷上：

1. 注册第一个真实账号，它会成为初始管理员。
2. 登录后打开**设置 → API**，保存 Chat Completions 或 Responses 配置。
3. 添加或同步模型，在工作区顶部选中模型并发送一条短消息。
4. 从账号菜单打开**后台管理**，或访问 `/admin`，检查账号与系统状态。

全新数据卷不会预置、模拟或自动导入任何账号。除非主动修改 `AUTH_DEFAULT_ROLE`，后续注册账号都会保持待审核状态。

## 启用隔离沙盒

先生成 Runner 共享密钥并写入 `.env`：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```dotenv
SANDBOX_TOOLS_ENABLED=1
SANDBOX_RUNNER_SECRET=替换为上一步生成的值
```

原生 Linux 还需把 Docker Socket 属组写入 `DOCKER_SOCKET_GID`：

```bash
stat -c %g /var/run/docker.sock
docker compose --profile sandbox pull app sandbox-runner sandbox-image
docker compose --profile sandbox up -d app sandbox-runner
docker compose --profile sandbox ps
docker compose --profile sandbox logs --tail 100 sandbox-runner
```

`sandbox-image` 服务只负责拉取执行镜像，不会启动常驻容器。未启用时保持 `SANDBOX_TOOLS_ENABLED=0`，Chat 与 Responses 都不会收到不可执行的工具定义。

启动后请确认：

- `app` 健康，且没有挂载 `/var/run/docker.sock`。
- `sandbox-runner` 健康、不映射宿主机端口，只能通过内部网络访问。
- App 与 Sandbox 镜像使用相同的发布版本。

## 文档

| 文档 | 内容 |
| --- | --- |
| [快速开始](docs/QUICKSTART.md) | 安装、首个管理员、本地构建与基础检查 |
| [用户指南](docs/USER_GUIDE.md) | 登录后的工作区、模型、文件、知识库、MCP 与沙盒 |
| [管理员指南](docs/ADMIN_GUIDE.md) | 账号审核、权限、平台数据、备份、审计与限流 |
| [集成指南](docs/INTEGRATIONS.md) | MCP、SearXNG、Ollama 与宿主机服务 |
| [运维指南](docs/OPERATIONS.md) | 备份、恢复、升级、回滚、日志与故障排查 |
| [发布指南](docs/RELEASE_GUIDE.md) | 修改、PR、版本说明、镜像发布、升级与回滚 |
| [运行手册](RUNBOOK.md) | 代码级运行边界和深入排障 |
| [安全策略](SECURITY.md) | 漏洞报告与受支持版本 |
| [贡献指南](CONTRIBUTING.md) | 开发、验证与提交规范 |

## 本地构建与验证

优先复用已发布镜像。需要开发当前源码时：

```bash
docker build -t apervia:local .
docker build -t apervia-sandbox:local docker/sandbox-prod
```

将 `.env` 中的镜像改为本地标签，并设置 `APP_PULL_POLICY=never`。提交前运行：

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q app3.py app3_parts sandbox_runner mcp_client tests
docker compose --profile sandbox config --quiet
docker compose --profile sandbox-build config --quiet
```

## 数据与升级原则

- 所有运行数据统一写入 Compose 命名卷 `apervia_app3_data`。
- 升级前必须备份数据卷，并保留上一版完整镜像标签。
- MCP 数据库 `/data/mcp_server_store.db` 与密钥 `/data/mcp_token.key` 必须成套备份。
- 不要执行 `docker compose down -v`，除非明确要永久删除全部运行数据。
- 镜像回滚不会自动回滚数据库格式；涉及数据迁移时必须结合发布说明恢复对应备份。

发布到其他仓库时，版本化镜像写法为：

```dotenv
APP_IMAGE=ghcr.io/<owner>/<repository>:1.0.3
```

标准备份文件可命名为 `apervia-data.tar.gz`。恢复会覆盖当前卷内数据，执行前必须先备份当前状态并核对目标卷名。

完整操作步骤见 [运维指南](docs/OPERATIONS.md)。

## 生产环境检查清单

- App 与 Sandbox 固定为相同的完整版本号，不要长期无条件跟随 `latest`。
- 尽量让 App 监听 `127.0.0.1` 并置于一层可信反向代理后；仅在这个拓扑中设置 `TRUST_PROXY_X_FOR=1`。
- 对外开放前补齐 HTTPS、防火墙、请求大小限制和独立备份计划。
- 备份 `apervia_app3_data`，包括 `/data/mcp_server_store.db` 与 `/data/mcp_token.key`，并实际测试恢复。
- 始终保留至少一个有效管理员，定期检查待审核、停用和删除中的账号。
- 每次升级后验证登录、真实模型对话、文件、MCP 和至少一次 Sandbox 任务。

## 常见启动检查

| 现象 | 首先检查 |
| --- | --- |
| 页面打不开 | 查看 `docker compose ps`、`docker compose logs --tail 100 app` 和就绪接口 |
| 没有可选模型 | 检查 API 类型、Base URL、密钥，再添加或同步模型 |
| 容器访问不到主机服务 | 使用 `host.docker.internal`，不要使用容器自己的 `127.0.0.1`，并检查主机监听地址与防火墙 |
| 没有沙盒工具 | 检查 `SANDBOX_TOOLS_ENABLED=1`、Runner 密钥一致、Runner 健康且 Sandbox 镜像已存在 |
| 新账号无法进入 | 在 `/admin` 审核待处理账号 |

## 当前边界

- 当前按单 App 实例设计，不支持直接横向扩容。
- 仓库不内置域名、反向代理、TLS 或自动证书配置。
- 沙盒能力依赖宿主机 Docker Engine，并默认关闭。
- 对外开放前，请先完成访问控制、防火墙、HTTPS、备份和恢复演练。

## 参与维护

提交问题或改动前请阅读 [贡献指南](CONTRIBUTING.md) 与 [行为准则](CODE_OF_CONDUCT.md)。安全问题请按 [安全策略](SECURITY.md) 私下报告，不要公开披露漏洞细节。
