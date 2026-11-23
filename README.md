# Ash

一个为长期对话而生的私人 AI 网关：会话、记忆、工具和界面，放在同一个由自己掌控的系统里。

Python · PostgreSQL · Anthropic / OpenAI 兼容接口 · MCP · Web UI

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

## 特性

- **会话由网关管理**：浏览器、聊天平台、其他前端都接同一段对话
- **有来源的记忆**：常驻 / 流动 / 日记 / 记忆片段，模型想改长期记忆需要你在 Pending 里点头
- **MCP 对外暴露**：在别的前端里也能用同一套记忆
- **无前端也能聊**：网关内部自带聊天
- **多模型路由**：Anthropic Messages 与 OpenAI 兼容接口，主对话、摘要、Embedding 可分别配置
- **手机优先的内置界面**：聊天、历史、收藏、笔记墙、日记、记忆库
- **外部入口**：iMessage、QQ、飞书 / Lark、微信

## 跑起来

需要 Docker。以下命令均在仓库根目录执行。

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

- 用其他 OpenAI 兼容接口，改 `OPENAI_API_URL` 即可。
- `DASHBOARD_COOKIE_SECURE=false` 仅用于本地 HTTP，上 HTTPS 后改为 `true`。
- `ash_local_password` 仅用于本机。对外部署请同时修改 `DATABASE_URL` 和下面 PostgreSQL 容器的密码。

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

### 4. 确认启动

```bash
until curl -fsS http://localhost:8000/healthz; do sleep 2; done
```

通过后打开 <http://localhost:8000>，用 `DASHBOARD_PASSWORD` 登录。

API Key 和平台凭据不要提交到 Git，也不要放进要分享的备份。

## 文档

| 文档 | 内容 |
| --- | --- |
| [USAGE.md](docs/USAGE.md) | 会话命令、记忆、备份与已知问题 |
| [MEMORY_RETRIEVAL.md](docs/MEMORY_RETRIEVAL.md) | 记忆片段与 MCP 工具 |
| [DASHBOARD_PHONE.md](docs/DASHBOARD_PHONE.md) | 浏览器桌面与聊天界面 |
| [integrations/photon/README.md](integrations/photon/README.md) | 外部聊天接入 |
| [SECURITY.md](SECURITY.md) | 部署、凭据与安全说明 |

## 致谢

Ash 起源于七堂伽藍_ 与 Midsummer 的 [AI Memory Gateway](https://github.com/garan0613/ai-memory-gateway)，感谢原作者的框架与开放许可，MIT 许可文本保留在 [LICENSE](LICENSE)。

设计与规划主要由 Claude Opus 4.6 协作完成，实现与修改主要由 GPT 系列模型（GPT-6 Astra、GPT-5.6 Sol）协作完成。

记忆库页面的视觉部分受 [StarFold146/Nyx](https://github.com/StarFold146/Nyx) 启发。

*人和机幸幸福福*
