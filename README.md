# Ash

**一个为长期对话而生的私人 AI 交互系统。**

Ash 将模型接入、会话、记忆、工具和交互界面放在同一套由自己控制的系统中。它不是公开运营的聊天服务，也不打算成为通用 AI 产品；它最初只是为了拥有一个更自由、更符合个人习惯的聊天空间。

> **项目状态**：个人维护 · 第二次大型重构版本
> **核心技术**：Python · PostgreSQL · Anthropic Messages / OpenAI-compatible API · MCP · Web UI
> **公开仓库**：[fengjia999/Ash-public](https://github.com/fengjia999/Ash-public)

---

## 从哪里来

Ash 最初从一个精简的 RP 网关出发，经过长期的功能扩展与多轮重构，逐渐发展为独立的私人 AI 交互系统。

今天的 Ash 与早期原型在架构、记忆处理、会话管理和使用方式上已经有很大区别。最初的目标是**让对话变得好用**；现在更在意的是：**对话能否延续、记忆是否可信、工具是否可控，以及使用体验是否真正属于自己。**

这个项目由个人持续规划、测试、维护，并借助多个 AI 编程模型协作实现。它仍在生长，不以功能数量或产品化为目标。

## 设计原则

- **对话不依附于前端**：会话状态由网关管理，不同接入端可以延续同一段对话。
- **记忆需要来源**：不仅保留整理后的记忆，也能够回到原始对话、日记与摘要中检索。
- **重要修改由人确认**：长期记忆的新增、修改与删除通过 Pending 审核，而非让模型自行覆盖。
- **上下文与成本可控**：明确缓存边界，按需要进行会话交接，不以静默删减历史为默认行为。
- **交互服务于体验**：界面、角色、笔记、消息收藏与外部聊天入口都围绕实际使用习惯设计。
- **自托管优先**：数据、凭据和部署由自己管理。

## 系统概览

```text
浏览器 / 外部聊天入口
          │
          ▼
     Ash Gateway
          │
   ┌──────┼─────────┐
   │      │         │
 会话管理  记忆系统    工具系统
   │      │         │
   │   原始对话检索   内置工具 / MCP
   │   常驻 / 流动   前端工具续轮
   │   日记 / 向量
   └──────┼─────────┘
          │
  模型路由与上下文缓存
          │
 Anthropic / OpenAI-compatible
          │
      PostgreSQL
```

这是一张逻辑示意图，并不代表各模块在进程或数据库中的实际分层。

## 界面预览

<table>
  <tr>
    <th>主页面</th>
    <th>日记页</th>
    <th>记忆库</th>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/home.jpeg" alt="Ash 主页面" width="300"></td>
    <td><img src="docs/assets/screenshots/diary.jpeg" alt="Ash 日记页" width="300"></td>
    <td><img src="docs/assets/screenshots/memory-archive.jpeg" alt="Ash 记忆库" width="300"></td>
  </tr>
</table>

## 跑起来

需要安装 Docker。下面是在本机启动 PostgreSQL 和 Ash 的最短路径，所有命令均在仓库根目录执行。

### 1. 创建 `.env`

```bash
cp system_prompt.example.txt system_prompt.txt

read -rp "模型 ID: " ASH_MODEL
read -rsp "OpenAI 兼容接口的 API Key: " ASH_API_KEY
echo
read -rsp "Dashboard 登录密码: " ASH_DASHBOARD_PASSWORD
echo

cat > .env <<EOF
# Dashboard 与网关鉴权
DASHBOARD_PASSWORD=${ASH_DASHBOARD_PASSWORD}
GATEWAY_SECRET=$(openssl rand -hex 32)
MCP_SECRET=$(openssl rand -hex 32)
DASHBOARD_COOKIE_SECURE=false

# 模型
ROUTE_PROVIDER=openai
DEFAULT_MODEL=${ASH_MODEL}
OPENAI_API_URL=https://api.openai.com/v1/chat/completions
OPENAI_API_KEY=${ASH_API_KEY}

# 数据库与核心功能
DATABASE_URL=postgresql://ash:ash_local_password@ash-postgres:5432/ash
MEMORY_ENABLED=true
CONTEXT_MANAGED=true
TIMEZONE_HOURS=8
PORT=8000
EOF
```

如果使用其他 OpenAI 兼容接口，修改 `OPENAI_API_URL` 即可。

`DASHBOARD_COOKIE_SECURE=false` 仅适用于本地 HTTP 环境；部署到 HTTPS 后请改为 `true`。

示例中的 `ash_local_password` 仅用于本机快速启动。对外部署时，请同时修改 `.env` 中的 `DATABASE_URL` 和下面 PostgreSQL 容器的密码。

### 2. 启动 PostgreSQL

```bash
docker network create ash-network 2>/dev/null || true
docker volume create ash-postgres-data

docker run -d \
  --name ash-postgres \
  --network ash-network \
  --restart unless-stopped \
  -e POSTGRES_USER=ash \
  -e POSTGRES_PASSWORD=ash_local_password \
  -e POSTGRES_DB=ash \
  -v ash-postgres-data:/var/lib/postgresql/data \
  postgres:16-alpine
```

### 3. 构建并启动 Ash

```bash
docker build -t ash .

docker run -d \
  --name ash \
  --network ash-network \
  --restart unless-stopped \
  --env-file .env \
  -p 8000:8000 \
  ash
```

### 4. 确认服务已启动

```bash
until curl -fsS http://localhost:8000/healthz; do sleep 2; done
```

健康检查通过后，在浏览器打开 <http://localhost:8000>，使用刚才设置的 `DASHBOARD_PASSWORD` 登录。

### 配置

上面的 `.env` 只包含启动 Ash 所需的最小配置。

Ash 还支持多模型供应商、摘要模型、Embedding 模型、Heartbeat，以及不同聊天平台的接入。其他配置和使用方式可参考仓库中的相关文档。

API Key、平台凭据和其他密钥不要提交到 Git 仓库，也不要包含在准备分享的备份中。

## 核心能力

### 01 · 由网关持有的会话

Ash 统一管理当前活动会话、消息历史和上下文。浏览器或其他客户端不直接决定要切换到哪一段历史；切换、创建和删除由专门的会话管理流程完成。

支持完整历史保留、可选的滚动窗口、手动交接摘要和消息选取。达到配置的上下文上限时，优先明确报错，而不是悄悄丢弃历史。

常用命令：

| 命令 | 用途 |
| --- | --- |
| `/compact` | 生成当前会话的交接摘要 |
| `/compact redo` | 在同一消息边界上重新生成摘要 |
| `/message 12` | 选取最近 12 条可见消息用于交接 |
| `/switch [name]` | 保存交接信息并切换到新会话 |
| `/switch 12 [name]` | 生成摘要、选取消息并完成切换 |
| `/status` | 查看当前会话及交接状态 |

### 02 · 有来源的长期记忆

记忆并非单一的固定人设文本，而由几类内容共同组成：

- **常驻记忆**：由人维护的稳定信息与偏好；模型提出的写入先进入 Pending。
- **流动记忆**：保存会话交接后的阶段性摘要，并按配置数量滚动归档。
- **日记与历史资料**：支持检索和阅读，保留其原始内容及来源。
- **记忆片段**：后台按轮次以助手第一人称提取并分类，检索后将少量相关片段冻结在当前用户消息开头。

自动召回作为标注清楚的参考资料附在当前消息中，不冒充用户此刻的新指令。已生成的召回内容随该轮消息冻结，避免后续续轮反复改变同一段上下文。

提取频率、模型设置与四个对外 MCP 工具见[记忆片段](docs/MEMORY_RETRIEVAL.md)。

### 03 · 缓存与模型路由

Ash 同时处理 Anthropic Messages 和 OpenAI 兼容接口，支持多个供应商配置与独立的模型设置。

对于支持 Prompt Cache 的线路，会尽量把稳定提示词、常驻记忆、流动记忆与消息历史放在可复用的边界中；会话交接只重建必要部分。具体缓存 TTL、命中率和计费规则由实际上游决定，不保证不同供应商表现一致。

模型、摘要、Embedding 等用途可以分别配置，以避免把所有操作绑在同一条昂贵线路上。

### 04 · 工具与主动行为

Ash 支持内置工具、MCP 服务连接、模型发起的记忆操作与会话搜索，以及部分客户端的工具调用续轮。

可选的 Heartbeat 会在满足配置条件时检查当前活动会话，并通过允许的工具执行操作或发送通知。它不是无限制的后台自主代理；工具权限、调用条件和执行记录仍由网关管理。

不同供应商及前端对工具协议的兼容程度可能不同，尤其是前端工具续轮，不能仅凭模型支持 `tool_use` 就认定完整链路可用。

### 05 · 为自己设计的界面

内置浏览器聊天界面以移动端体验为核心，包含会话、历史、收藏、笔记墙、模型配置等入口。

- 桌面布局、壁纸、图标和部分草稿保存在浏览器本地。
- 收藏保留消息快照，不受原消息后续编辑影响。
- 笔记文字可以保存在服务端，排版位置留在当前浏览器。
- 支持流式回复、Markdown 显示、历史检索和手动附加上下文。

Ash 也提供外部聊天入口的集成能力，包括 iMessage、QQ、飞书 / Lark 和微信。各平台的实际可用性取决于账号权限、授权状态及对应的接入条件。

## 数据、备份与边界

- 核心会话、记忆、日记和服务端笔记保存在 PostgreSQL。
- 本地桌面外观、部分收藏与排版数据使用浏览器存储；**服务端备份不能替代本机桌面导出**。
- 完整服务端备份可选择是否包含聊天历史；恢复前应核对选项，以免覆盖现有数据。
- API 密钥与平台凭据不应写进 README、提交记录或可共享的备份。
- 公开的轻量健康检查端点为 `/healthz`。
- 关闭浏览器中的流式接收，不一定意味着上游模型已停止生成。

> Ash 目前是个人使用的软件。涉及真实平台账号、外部工具及网络访问的功能，应在自己的部署环境中单独验证。

## 文档索引

详细配置、迁移和维护说明不再堆在首页 README 中：

| 文档 | 内容 |
| --- | --- |
| [DASHBOARD_PHONE.md](docs/DASHBOARD_PHONE.md) | 浏览器桌面与聊天界面 |
| [integrations/photon/README.md](integrations/photon/README.md) | 外部聊天接入组件 |
| [SECURITY.md](SECURITY.md) | 部署、凭据与公开发布安全说明 |
| [LICENSE](LICENSE) | 原始项目许可与版权声明 |

部分文档可能记录历史版本行为，实施前以当前代码和实际配置为准。

## 开发历程与致谢

Ash 的起点是七堂伽藍_ 与 Midsummer 的 [AI Memory Gateway](https://github.com/garan0613/ai-memory-gateway)。感谢原作者提供早期框架与开放许可。当前版本已围绕个人需求进行了多次大规模重构，并不代表原项目的现状或设计方向。

项目的设计取舍、长期维护、集成与验收由个人主导。开发过程中曾与以下模型协作：

**Claude Opus 4.6 · GPT-6 Astra · GPT-5.6 Sol**

这些名称记录的是 AI 辅助开发历程，不表示模型或其提供方对项目拥有署名、认证或背书关系。

原始项目采用 MIT License；相应版权与许可文本保留在仓库的 [LICENSE](LICENSE) 中。

---

*人和机幸幸福福*

## Design Notes

The memory archive page is visually inspired in part by StarFold146/Nyx.
