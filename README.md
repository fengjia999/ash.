# Ash

> 灰烬，是对话熄灭以后仍然留下的余辉。

Ash 是一个为长期运行的 AI 助手设计的自托管 Agent Runtime。它统一管理会话、
分层记忆、提示词缓存、模型路由、MCP 工具与主动任务，让一次次彼此分离的对话能够
留下可验证、可整理，也可以被遗忘的痕迹。

## 关于这个分支

Ash 基于七堂伽藍_ 的
[AI Memory Gateway](https://github.com/garan0613/ai-memory-gateway)
开发。感谢原作者提供网关的原始框架；当前项目已经在此基础上进行了大幅重构，主要包括：

- 重新设计记忆流程，将常驻记忆、流动摘要、碎片记忆与日记分开管理，并加入异步记忆提取、评分、召回、衰减和 Pending 确认机制。
- 重构面向昂贵模型的提示词缓存策略与上下文边界，使稳定人格、常驻记忆和流动上下文能够尽可能复用 Prompt Cache；同时保留由用户主动控制的 `/compact` 与 `/switch` 会话交接方式。
- 扩展 Anthropic 与 OpenAI 兼容接口的多路由、多供应商和独立模型配置。
- 重构由网关持有上下文的会话管理，包括历史搜索、交接摘要、消息选择、切换及 Dashboard 会话界面。
- 在原始框架之后加入 MCP 服务与工具接入，并扩展模型可用的记忆读写和会话搜索能力。

原项目的版权声明与 MIT License 保留在 [LICENSE](LICENSE) 中。
当前公开版本位于 [fengjia999/Ash-public](https://github.com/fengjia999/Ash-public)。

> Ash 目前仍是实验性项目，接口、数据结构和交互方式可能继续变化。请勿在没有配置
> 身份验证并理解模型调用费用的情况下直接暴露到公网。

## Before you start

复制公开模板并在本地填写配置；不要提交生成后的私人文件。未创建
`system_prompt.txt` 时，程序会使用空白的公开示例初始化提示词分区：

```bash
cp .env.example .env
cp system_prompt.example.txt system_prompt.txt
```

Dashboard 默认指向本仓库，也可通过 `PUBLIC_REPOSITORY_URL` 改为自己的 fork。
部署到公网前请阅读 [SECURITY.md](SECURITY.md)。

## Browser chat

`/` opens the dashboard at the conversation list. Selecting a historical
conversation opens its context for preview; activate it explicitly to resume
chat. Use the back control in the conversation header to return to the list.

The conversation composer supports streamed replies, basic Markdown (bold, inline
code, and fenced code), and manual context additions. Browser chat requires
`CONTEXT_MANAGED=true` and uses the dashboard session plus CSRF protection, without
exposing the gateway API secret. Requests reject a stale conversation selection.
The route and supplier controls change the global gateway configuration; choosing
a compatible supplier also selects the OpenAI-compatible route. Model IDs can be
picked from the refreshed list or entered manually.

Stopping reception closes the browser stream; the upstream request may still be
processing. Refresh the context to verify saved messages before retrying. Existing
conversations with client-only tool snapshots still require their original client
for those tools. The browser does not execute frontend-specific tools.

The public JSON health endpoint is now `/healthz`; update probes that previously
used `/`.

## Conversation ownership

The gateway owns the active conversation. Chat request headers, body metadata,
and frontend conversation IDs cannot create or switch it. Use the conversation
management API explicitly:

- `POST /api/conversations` creates a conversation without activating it.
- `POST /api/conversations/{id}/activate` switches the active conversation.
- Deleting the active conversation leaves the gateway with no active conversation.

Managed context stores the complete message history. It is not summarized,
trimmed by message count, or moved to another conversation automatically.

## Gateway slash commands

When the last user turn consists only of a registered command, the chat route
handles it as gateway control traffic. The command is neither stored in context
nor forwarded to the normal chat model. Both streaming and non-streaming
OpenAI-compatible clients receive an ordinary assistant result message.

- `/compact` generates and saves a new handoff-summary snapshot.
- `/compact redo` regenerates from the same frozen message boundary. Optional
  text after `redo` is passed as a regeneration preference.
- `/message 12` freezes the last 12 visible user/assistant messages for the
  next handoff. `/message(12)` is accepted as a compatibility spelling.
- `/switch [name]` atomically writes the saved summary into the standing-memory
  flow timeline, then creates and activates a conversation containing any
  frozen messages. The summary is not injected again as a separate handoff.
- `/switch 12 [name]` generates a fresh summary, selects 12 messages, and
  switches in one request.
- `/heartbeat on` and `/heartbeat off` change only the enabled flag and preserve
  the configured interval, provider, and model.
- `/diary` generates one diary proposal from the active
  conversation and returns the full draft in chat. `/yes` approves that exact
  proposal; `/no` rejects it. The proposal is bound to the source conversation
  in metadata, survives restarts, and cannot approve unrelated pending items.
- `/status` shows the active conversation, summary version, selection count,
  pending diary review, and heartbeat state; `/help` prints the command list.

`compact`, `message`, and `switch` require `CONTEXT_MANAGED=true`. Selection is
limited to 200 messages per handoff. Unregistered slash text is sent to the
model normally; prefix a registered command with a second slash (for example,
`//compact`) to send it as ordinary text as well. Summary snapshots and message
selections are persisted on the source conversation, so they survive gateway
restarts. The flow timeline retains the newest 8 summaries by default. Its
limit can be changed from 1 to 100 directly in the dashboard's flow-zone header
without restarting the service; `FLOW_MEMORY_MAX_ITEMS` supplies only the
initial default before a value is saved. The gateway moves summaries older than
the saved limit unchanged into the diary archive in the same transaction and
removes the flow rows. `FLOW_MEMORY_HARD_TOKENS` (default `12000`) remains an
emergency guard for unusually large summaries, but normal rolling is based on
item count. Automatic promotion never creates a Pending proposal or calls the
summary model. When a promoted entry's title starts with a valid `YYYY-MM-DD`,
that explicit prefix becomes its diary date; otherwise the date it entered the
flow timeline remains the fallback. The original flow date and the
promotion-time date source stay in metadata; later manual edits remain
authoritative.

## Memory writes

Switching with `/switch` queues memory extraction from a frozen source-conversation
snapshot in the same transaction as the switch. A background worker uses the
Memory Extraction model (the existing `long_term_summary_*` configuration), the
persona/memory prompt, and standing memory to extract new preferences, habits,
plans, and important opinions. Every new fragment must include verbatim quotes
and source message IDs; quotes are checked against the snapshot before saving.
Handoff copies, hidden messages, reasoning, and tool payloads are excluded.
Each switch job also reserves at most three unscored legacy fragments. The first
extraction request scores these separately without rewriting them or inventing
quotes. Retries reuse that reservation, and scores commit with job completion.
Exhausted failed jobs release reservations for later switches.
Long conversations are processed in batches of up to roughly 24,000 characters,
with at most 12 fragments per batch. Empty results are valid. Failed jobs retry
up to three times; interrupted jobs resume after their lease expires. Fragment
writes and job completion commit together. Existing migrated fragments retain
their diary provenance but have no invented message-level quotes.
Manual
standing-memory edits take effect immediately. The chat and heartbeat models can
also propose standing-memory creates, edits, and deletes through `create_memory`,
`edit_memory`, and `delete_memory`; model-authored changes remain Pending until
the user approves or rejects them in the dashboard. Edit proposals show the old
and proposed text with character-level marker highlighting. Diary
drafts also require explicit review.
Standing-memory tools accept content/IDs only, with no reason field.

Fragment forgetting is deterministic and never invokes a model. An hourly sweep
uses retention `2 ** (-age_days / (30 + 150 * importance))`; retention below
`FRAGMENT_FORGET_THRESHOLD` (default `0.2`) creates a pending forgetting entry,
pausing recall without deleting content. Unscored or undated legacy fragments
are skipped; scoring starts their retention clock. The dashboard exposes Keep
(reset the clock) and Confirm Forget (delete) actions. Important fragments decay
more slowly. This lifecycle is separate from the five-component retrieval score.
Standing memory is presented as two zones: the fixed zone (`core`, plus legacy
`ring` records) is manually maintained, while the flow zone (`recent`) receives
conversation summaries when switching sessions.
For prompt caching, the core prompt and fixed zone share the first stable cache
block, while the bounded flow timeline uses the second block. A session switch
rebuilds only the flow block; ordinary turns reuse both blocks and retain the
remaining message-cache breakpoints.
Archived flow summaries and authored diaries live in the diary branch. Existing
diary summaries are split once into independent fragments while the source diary
remains intact; the obsolete diary summary field is then cleared. `search_memory`
returns complete compact fragment text with no title, date metadata, or follow-up
read step. When a date is useful it belongs at the beginning of the fragment text
itself. `search_diary` returns a compact diary directory using keywords, and
`read_diary` reads one diary body. All three are read-only.
`search_conversation_history` remains available as an independent search over
earlier raw conversations.
The three standing-memory write tools never mutate active memory directly; they
only create or update a Pending proposal.
Automatic fragment-memory recall is relevance-gated and packed by estimated input
tokens instead of a fixed item count. It stops at about 1,500 tokens by default
without filling leftover space with lower-ranked results. Override the cap with
`LONG_TERM_RECALL_MAX_TOKENS` for the initial default, or adjust it at runtime in
the dashboard's history-search settings. The saved value accepts 256-8,000
tokens and takes precedence over the environment default.

Fragment retrieval first requires cosine similarity at least
`LONG_TERM_RECALL_MIN_SEMANTIC_SCORE` (default `0.35`). Missing query/candidate
vectors or no eligible matches produce zero fragments; keyword matches cannot
bypass this gate. Eligible fragments are ranked by `semantic_similarity * 0.45
+ recency_score * 0.20 + importance * 0.15 + entity_overlap * 0.10
+ thread_affinity * 0.10`, with all components in `[0, 1]`.
Recency uses extraction write time with a 30-day exponential half-life
(`FRAGMENT_RECENCY_HALF_LIFE_DAYS`); migration dates give no recency bonus.
Importance and entities are supplied by the extraction model, with entity names
checked against the quoted evidence. Existing unscored fragments temporarily use
importance `0.5`; missing entities give zero overlap. Entity overlap is the
fraction of a fragment's stored entities mentioned in the query. Thread affinity
is `1` within the same conversation handoff family, otherwise `0`. These weights
apply to fragments; diary and conversation searches keep their own ranking.

The memory dashboard separates fixed memory entries, extracted/migrated memory
fragments, and diaries. Its complete prompt-splice preview lives at the bottom of
Settings and lazily exposes each prompt section plus the fixed and flow memory
blocks in actual assembly order.

The dashboard stores separate provider/model selections for handoff summaries
and memory extraction. Existing installations keep using the
handoff selection for extraction until the settings form is saved once,
after which the two selections are independent. The extraction
environment fallback can also be configured separately with
`LONG_TERM_SUMMARY_API_URL`, `LONG_TERM_SUMMARY_API_KEY`, and
`LONG_TERM_SUMMARY_MODEL`; each falls back to its `MEMORY_ORGANIZER_*`
counterpart when omitted. Moving flow memory into the diary archive still does
not call either summary model automatically.

Summary and diary jobs use low reasoning effort by default so thinking models
leave enough output budget for visible results. Set
`MEMORY_ORGANIZER_REASONING_EFFORT` to override that default.

## Context limit

Set `MODEL_CONTEXT_LIMIT` to the real context-window token limit of the routed
model. `CONTEXT_TOKEN_SAFETY_MARGIN` defaults to `4096`. The gateway performs a
conservative local estimate before saving and sending a new user turn. If the
full history does not fit, it returns HTTP 413 with
`error=context_limit_exceeded`; it does not trim, summarize, or switch sessions.

`MODEL_CONTEXT_LIMIT=0` disables the local estimate and leaves the hard-limit
decision to the upstream provider.

## Long-running operation

- Export a full JSON backup after meaningful memory changes and periodically
  test a restore on a separate instance. Backup schema versions 2 through 8 are
  accepted by both the dashboard preview and restore API.
- The JSON backup contains memories, pending operations, conversations, and
  messages. It intentionally does not contain deployment secrets, provider
  profiles, or model settings; preserve those environment variables and
  settings separately.
- Keep `MEMORY_CLEANUP_INTERVAL=0` unless automatic deletion of low-importance
  legacy fragments is explicitly desired. It is disabled by default.
- Watch the flow-token indicator and diary "待关键词" count in the memory
  dashboard. They expose maintenance pressure without triggering model calls.
- Set `MODEL_CONTEXT_LIMIT` to the routed model's real context limit so an
  oversized conversation fails predictably before an upstream request.
- Monitor `GET /healthz`: it remains lightweight and reports `status=degraded` with
  `database_status=unavailable` when the memory database cannot be queried,
  without exposing the database error or credentials.

## OpenRouter Anthropic endpoint

For the OpenAI-compatible route, an OpenRouter provider may use either the base
URL `https://openrouter.ai/api/v1` or the full Chat Completions endpoint. The
gateway expands the base URL automatically and loads models from the same
effective dashboard profile or environment fallback used for chat.

The Anthropic route can use OpenRouter's native Messages API without converting
the request to OpenAI Chat Completions:

```env
ANTHROPIC_API_URL=https://openrouter.ai/api/v1/messages
DEFAULT_MODEL=claude-opus-4-6
```

On hosted deployments, `API_KEY` can instead be saved from Dashboard → Settings
→ Anthropic route key. The Dashboard value is stored in the database and takes
precedence over the environment fallback, so it survives service restarts until
manually deleted. The plaintext key is never returned by the management API and
the credential table is deliberately excluded from gateway JSON backups. Remove
the deployment `API_KEY` variable if deleting the Dashboard value should leave
the Anthropic route fully disabled.

For this endpoint the gateway automatically uses bearer authentication,
normalizes native Claude aliases such as `claude-opus-4-6` to OpenRouter's
`anthropic/claude-opus-4.6` slug, and sends the conversation ID as `session_id`
for provider-sticky cache routing. Requests are restricted to OpenRouter's
Anthropic provider so they do not fall back to a different Claude host. Existing
explicit `cache_control` blocks are preserved. Direct Anthropic requests retain
their native headers and model IDs.

## Chat route

`ROUTE_PROVIDER` remains the startup default for normal chat. The dashboard
Settings page can persist `auto`, `openai`, or `anthropic`; the saved route takes
effect on the next request without restarting the service. An explicit
`provider`, `route_provider`, or `provider_hint` request field still takes
precedence over the saved default. Heartbeats keep their independent route.

## Authentication

Keep two independent passwords in the deployment environment:

```env
GATEWAY_SECRET=secret-used-by-napcat-and-other-api-clients
DASHBOARD_PASSWORD=separate-password-used-only-for-dashboard-login
```

All `/v1/*` requests require `Authorization: Bearer <GATEWAY_SECRET>` and never
accept secrets in the URL. Dashboard pages and management APIs use a signed,
HttpOnly login cookie instead; the gateway secret is never sent to browser
JavaScript. Dashboard sessions last seven days by default. Set
`DASHBOARD_SESSION_TTL_HOURS` to change that duration. HTTPS deployments use a
Secure cookie by default; set `DASHBOARD_COOKIE_SECURE=false` only for local HTTP
development.

## Heartbeat cache

Heartbeats operate only on the explicitly active conversation. Each check gives
the selected model a bounded autonomous tool loop with the same gateway MCP and
memory tools exposed by normal chat. The model may use any of those tools until
it returns without another tool call. A notification is sent only when the model
chooses to call the notification tool.

`HEARTBEAT_PROVIDER` explicitly selects `openai` or `anthropic`. Anthropic checks
reuse the persisted main-chat cache anchor. Tool rounds append after the stable
prefix and may add a tool-result cache anchor without invalidating that prefix.
OpenAI checks do not touch the Anthropic cache. `HEARTBEAT_MODEL` optionally overrides the
model used by the selected route; otherwise Anthropic uses `DEFAULT_MODEL`, and
OpenAI uses `DEFAULT_MODEL` when it is OpenAI-like or `gpt-4o-mini` otherwise.

Relevant settings:

- `HEARTBEAT_ENABLED` enables the worker.
- `HEARTBEAT_INTERVAL` is the inactivity threshold in minutes.
- `HEARTBEAT_CHECK_INTERVAL` is the worker polling interval in seconds.
- `HEARTBEAT_CLAIM_TIMEOUT` is the stale distributed-claim timeout in seconds
  and defaults to `1800`.
- `HEARTBEAT_PROVIDER` selects `openai` or `anthropic` and defaults to `openai`.
- `HEARTBEAT_MODEL` optionally overrides the route's inferred model.
- `HEARTBEAT_MAX_TOKENS` reserves the OpenAI-compatible heartbeat output budget
  and defaults to `4096`; reasoning tokens count against this budget on
  OpenRouter.
- `HEARTBEAT_REASONING_EFFORT` controls heartbeat reasoning independently and
  defaults to `low`. OpenRouter Gemini 2.5/3 thinking models use this low default
  even when general OpenAI-route reasoning is disabled.

These environment variables are initial defaults. The dashboard Heartbeat page
can persist the enabled state, interval, provider, and model in PostgreSQL;
saved values take effect on the next worker poll without restarting the service.

Every wake is stored in the heartbeat activity log with the final judgment and
tool events, and is visible in the dashboard. Heartbeats that used tools are
materialized immediately as hidden assistant history, so later heartbeats and
real turns can recognize notifications and other actions without altering the
user's message. Any activity that loses a conversation race is materialized
before the next real user turn instead. Tool execution is cancelled if the active
conversation changes while the heartbeat is running. Checks continue at the
configured interval without a cumulative push limit.
Anthropic intervals above 55 minutes are clamped to 55 minutes so the
next check occurs before the one-hour cache TTL.

## MCP servers

`MCP_SERVER_URL` remains available for unauthenticated MCP servers. For
authenticated or multiple servers, use `MCP_SERVERS_JSON`:

```env
MCP_SERVERS_JSON=[{"url":"https://terminal.example.com/mcp","bearer_token":"replace-with-a-secret"},{"url":"https://search.example.com/mcp","bearer_token":"another-secret"}]
```

Each server may use a different bearer token. The gateway sends it as the
`Authorization: Bearer ...` header on MCP initialization, tool discovery, and
tool calls. Tokens are never included in tool definitions, API responses, or
MCP logs. When `MCP_SERVERS_JSON` is set, it takes precedence over the legacy
`MCP_SERVER_URL` list.

## Photon iMessage notifications

The optional standalone Photon Bridge service turns iMessage into a personal
frontend and gives heartbeat checks a direct HTTP notification tool. Configure
both values to expose `send_imessage_notification` to newly created conversations:

```env
PHOTON_NOTIFY_URL=https://your-photon-bridge.example/notify
PHOTON_NOTIFY_SECRET=replace-with-a-separate-strong-secret
```

Existing conversations keep their frozen tool snapshot. After enabling the
integration, create or switch to a new conversation before expecting heartbeat
checks to see the notification tool.

Photon frontend tool continuations are persisted as complete tool call/result
pairs. Successful native replies and Tapbacks are also materialized as assistant
timeline entries, allowing later heartbeat checks to see exactly what the user
already received even when the model correctly emits no duplicate final text.
