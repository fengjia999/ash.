# Ash 项目地图（给 Claude 和接手的人看）

这份说明按 **2026-10-20，提交 `3a856d4`** 的源码整理。“这段时间”主要指 2026 年 9 月到 10 月，重点是 10 月 12 日以来的改动。下面说的是代码支持什么，不代表线上已经打开了所有功能；实际开关和供应商配置还要看部署环境及数据库。

## 1. 先用一句人话说清楚

Ash 是夹在聊天客户端和大模型之间的记忆网关：接住消息，带上人格、记忆和历史，找合适的模型回答，再把对话存起来。它自己还带一个可以直接聊天、管理记忆和配置模型的网页。

它基于 AI Memory Gateway 改造，现在的后端仍然主要挤在两个大文件里：

- **`main.py` 管流程**：收到请求后做什么、问哪个模型、怎么用工具、怎么把回答送回去。
- **`database.py` 管保存和一致性**：历史、记忆、设置如何存取，切会话、确认记忆、备份恢复怎样避免只做了一半。

没有一套藏在 `src/` 或 `services/` 里的分层框架。看到这两个文件很长是正常的；不要为了找“真正入口”继续乱翻。

## 2. 根目录和各文件夹是干什么的

### 文件夹

| 路径 | 大白话说明 | 和运行有什么关系 |
| --- | --- | --- |
| `templates/` | 网页的 HTML 骨架，使用 Jinja2；有些页面还把交互 JS 直接写在 HTML 里面 | 网页需要，不只是静态说明文件 |
| `static/js/` | 网页按钮、发送消息、读流式回答、切页面、桌面拖动等操作 | 浏览器交互需要；原生 JS，没有前端打包工程 |
| `static/css/` | 手机界面、聊天、纸张式记忆页、设置等样式 | 主要影响外观，但页面还在引用旧样式，不能按名字随便删 |
| `static/images/` | 头像、纸张背景、心跳杯子等配图，以及素材说明 | 大多是外观资源 |
| `static/fonts/` | 本地字体，包括 `wenkai/` 字体文件 | 外观资源，不是聊天逻辑 |
| `tests/` | 后端和前端行为检查；以 Python unittest 为主，也有 Node/浏览器脚本 | 服务启动不依赖它；改逻辑时用来防止旧功能坏掉 |
| `.venv/`、`.deps/` | 这台机器上的 Python 环境和依赖 | 不是业务源码；重建依赖后可以再生成，当前进程或测试可能正在用 |
| `__pycache__/`、`.pytest_cache/` | Python 和测试生成的缓存 | 停止相关任务后可以清理，会再生成 |
| `.git/` | Ash 的提交历史 | 不参与聊天，但保留历史、回滚和追踪改动靠它 |

### 根目录里的 Python 文件

| 文件 | 负责什么 |
| --- | --- |
| `main.py` | FastAPI 启动、鉴权、聊天入口、供应商路由、提示词拼接、缓存、工具循环、心跳和管理 API |
| `database.py` | PostgreSQL 连接池、自动建表/补字段、会话和消息、记忆和 Pending、模型设置、切换事务、备份恢复 |
| `prompt_manager.py` | 管理分段人格提示词：从数据库读取、编辑、拼接；从种子文件初始化 |
| `conversation_recall.py` | 从 Ash 历史原句中做本地自动召回；也负责主动向量搜索所需的句子索引构建 |
| `conversation_search.py` | 模型主动调用历史搜索工具时，使用 Embedding 和历史句子索引查对话 |
| `emotion_recall.py` | 给本地原句检索提供情绪识别和排序辅助；不是单独的聊天模型 |
| `memory_fragments.py` | 从对话提取第一人称记忆片段，整理、检索并打包召回结果 |
| `diary_author.py` | 区分日记是谁写的，避免把用户经历当成助手经历 |
| `diary_monthly.py` | 按月汇总日记，保存可复制的助手口吻总结；后台任务支持断线查询，失败保留上一版正文 |
| `diary_merge.py` | 仅兼容已经生成的旧日记合并提案的确认落库；不再生成新的合并稿 |
| `dashboard_delivery.py` | 网页传输优化：对适合的响应做 GZip，流式响应不压缩，避免聊天一段段输出变卡 |
| `seed_memories_example.py` | 初始记忆导入示例，不是服务入口 |

`requirements.txt` 是 Python 依赖清单；`Dockerfile` 安装依赖后运行 `python main.py`。本地也可以用 `uvicorn main:app` 启动。

`system_prompt.txt` 是**初始种子**。启动时补入数据库里还不存在的提示词段，不覆盖已有段；日常修改保存在数据库。直接改这个 txt，不等于线上人格马上改变，显式 reseed 才会覆盖对应内容。

### 网页里最值得认识的文件

- `templates/dashboard.html`：管理页主骨架，加载管理功能和手机桌面，包含 `phone-shell.html`、`conversation-prompts.html`。
- `templates/phone-shell.html` + `static/js/phone-shell.js`：手机应用外壳、页面导航、打开聊天和管理页面。
- `static/js/merle-phone.js`、`merle-phone-media.js`、`merle-icons.js`：复用/适配 Merle 的桌面布局、手势、壁纸、图标和小组件。
- `static/js/phone-storage.js`：本浏览器的桌面布局、名称、草稿和图片等状态；使用本地存储及 IndexedDB。
- `templates/context.html`：会话列表、历史、上下文和聊天页面；页面本身仍有不少内联 JS。
- **`static/js/context-chat.js`**：真正发送网页聊天请求、读取 SSE 回答的地方，入口函数是 `sendChat()`。
- `static/js/phone-chat.js`：给上面的聊天功能套手机交互，处理草稿、头像、返回按钮等。
- `static/js/dashboard.js`：管理页共用逻辑；`memory-notebook.js` 管日记，`settings-desk.js` 管设置，`conversation-prompts.js` 管会话提示词，`identity-avatars.js` 管身份头像，`usage-paper.js` 管用量展示。
- `static/js/phone-viewport.js`：手机可视区域和键盘适配；`theme.js` 管主题。
- `templates/prompt.html`、`login.html`：提示词编辑和登录。目录里还有 `base.html`、`quotes.html` 等历史模板；文件存在不代表当前入口仍然使用，删之前要查路由和引用。

## 3. 一条消息从进来到出去，经过哪些文件

### 先记住这条主路

```text
网页：context.html → context-chat.js → POST /api/conversations/{id}/chat
外部客户端：直接 POST /v1/chat/completions
                                  ↓
main.py：鉴权 → chat_completions() → 读取当前会话和供应商
                                  ↓
database.py：取历史、设置、常驻记忆
prompt_manager.py：取人格提示词
可选召回：conversation_recall.py
                                  ↓
main.py：拼上下文、存本轮用户消息、调用上游模型、处理工具
                                  ↓
database.py：存回答、工具记录、用量等
                                  ↓
main.py：返回 JSON 或 SSE → context-chat.js 显示回答
```

这不是每次都串行调用所有文件。召回、OCR、工具等按配置和模型输出决定是否走；下面是普通新消息的具体过程。

### 第一步：接住请求，确定你在跟谁聊

`main.py` 的 `gateway_auth_middleware()` 先检查权限。网页用登录 Cookie，写操作还要 CSRF；API 客户端用网关的鉴权配置。

网页聊天先到 `dashboard_chat()`，检查只提交一条用户文本，并确认选中的还是当前活动会话，然后复用 `chat_completions()`。外部客户端直接进 `chat_completions()`。

**会话由网关持有。** 请求里随手塞一个会话 ID，不会创建或激活它；创建、激活要走显式会话 API。网页翻看旧记录也不等于恢复那段会话。

如果最后一条用户消息是 `/compact`、`/switch`、`/status` 等已注册命令，会提前进入 `_execute_gateway_command()`。命令本身不按普通聊天存入历史，也不发给聊天模型；其中 compact 等操作可能另外调用摘要模型。

### 第二步：选供应商，整理历史和这次输入

仍然在 `main.py`：读取服务端聊天配置，选择 Anthropic 或 OpenAI 兼容供应商。已经固定的服务端配置会决定实际模型，不能只看客户端发来的 `model`。

`normalize_user_content()` 整理文字和图片，配置了 OCR 才调用 `preprocess_user_blocks_with_ocr()` 做图片识别。

默认 `CONTEXT_MANAGED=true`：通过 `database.py` 读取保存的历史，用 `_rebuild_messages_from_rows()` 还原模型需要的消息。无限上下文尽量保留完整历史；选了窗口模式才按预算只发最近一部分，窗口外内容可由临时摘要衔接，**数据库原历史不会因此被自动删除**。

兼容模式 `CONTEXT_MANAGED=false` 使用客户端传来的历史，跳过网关托管消息保存。网页聊天不支持这个模式；普通聊天入口仍会要求已有活动会话，所以它也不是完全无数据库的透明转发器。

### 第三步：把人格、记忆和本轮资料拼进去

`build_system_prompt_with_memories()` 组织几个部分：

1. `prompt_manager.py` 从 `prompt_sections` 读取人格和基础提示词。
2. `database.py` 读取常驻记忆：固定区 `core`（兼容旧 `ring`）和流动区 `recent`。
3. 根据会话模式，加入临时摘要；根据本轮配置，加入自动召回。
4. 处理会话额外提示词、读取前端提示词的开关、注入位置和频率，并记录实际注入。

开启片段召回后，`build_dynamic_turn_block()` 通过 `memory_fragments.py` 检索相关片段，用 `<memories>` 包裹并放在当前用户消息开头，跳过上下文已有的片段。托管模式保存用户原文用于显示和搜索，另用 `content_json` 保留本轮完整模型输入。以后重放这条历史时沿用当时的资料，不重新召回；compact 和摘要则读取原始对话，避免把注入资料又总结一遍。

提示词缓存也在 `main.py`：人格与固定记忆、流动区分别构成稳定块，再管理历史消息的缓存位置。窗口模式禁用消息缓存，但仍保留稳定的系统块。这里的缓存是请求前缀复用，不是把回答存在本地直接返回。

### 第四步：调用模型，必要时来回用工具

用户消息在调用上游前保存。Anthropic 路由使用 `handle_tool_loop()` / `stream_with_tool_loop()`；OpenAI 兼容路由使用 `handle_openai_tool_loop()` / `stream_openai_with_tool_loop()`。对外仍返回 OpenAI 兼容的 JSON 或 SSE。

模型要求调用工具时，`dispatch_tool_call()` 分流：

- 内置工具直接访问数据库，例如搜索日记、搜索历史、提出记忆修改。
- 主动历史搜索通过 `database.search_conversation_history()` → `conversation_search.py` → 原句索引和原始消息；它需要完整的向量配置，与自动召回开关分开。
- 外部工具由 `call_mcp_tool()` 转给配置好的 MCP 服务。
- 客户端专有工具交回原客户端执行，随后走 `handle_tool_continuation()` 或 `handle_openai_continuation()` 续场；网页不会代替外部客户端运行它的工具。

工具清单有会话快照，工具调用和结果也要持久化。尤其交给客户端的工具调用，要先存再发，不能只在浏览器里显示一下。

模型通过 `create_memory`、`edit_memory`、`delete_memory` 写常驻记忆时，产生的是 **Pending 待确认提案**。用户在管理页批准后，数据库才正式应用修改。

### 第五步：保存和送回回答

非流式拿到完整回答后保存并返回。流式则一边向客户端输出、一边收集结果，按对应流程保存工具事件和最终回答；两者也会记录用量。上游返回的 reasoning 可以随回答保存，网页从对应消息打开查看。

网页 `context-chat.js` 读取流并更新消息，`phone-chat.js` 补手机交互。浏览器停止接收不保证上游已停止，重试前应先刷新确认这一轮有没有入库。

## 4. 普通聊天之外，还有哪几条重要支线

### 换会话：不是自动把旧记录压没

`/compact` 生成交接摘要，`/message N` 选择要带走的消息，`/switch` 才真正交接。流程从 `main.py` 进入 `database.py` 的切换事务：摘要进流动区，创建并激活新会话，带上选定消息。旧会话还在。

流动区默认保留最近 8 条摘要，用户可改数量；较老的摘要原样归档到日记。这个归档不另外调用摘要模型，也不产生 Pending。


### 心跳：后台也能继续处理事情

`main.py` 的 `lifespan()` 启动 `heartbeat_loop()`，周期检查是否应该触发，再由 `heartbeat_check()` / `_fire_heartbeat()` 调模型和工具。它有领取令牌、缓存位置和活动记录，防止多个实例重复处理。最近修复为沿用最后一次真实聊天保存的供应商快照，不随全局配置变化而误换供应商。

## 5. 数据到底存在哪里

**主要业务数据在 PostgreSQL，连接地址来自 `DATABASE_URL`。** 不是根目录的一组 JSON 文件。

| 数据 | 主要位置 |
| --- | --- |
| 会话与完整消息 | `conversations`、`context_messages` |
| 人格提示词 | `prompt_sections` |
| 固定记忆、流动记忆及其待确认操作 | `standing_memory_blocks`（包含状态及操作信息） |
| 日记和日记待确认操作 | `long_term_memories`、`long_term_memory_proposals` |
| 供应商、模型任务、心跳、OCR 等配置 | PostgreSQL 中对应设置表 |
| 会话额外提示词、来源、注入记录和共享预设 | `conversation_extra_prompts`、`conversation_prompt_sources`、`conversation_extra_prompt_injections`、`extra_prompt_presets` |
| 旧版迁移记录（随备份恢复） | `nocturne_extraction_jobs` |
| 原句向量索引 | `conversation_recall_index`，由 `conversation_recall.py` 建立；可重建，不等于原始对话 |
| 手机桌面布局、壁纸、自定义图标、草稿等 | 浏览器本地存储 / IndexedDB，不属于服务器备份 |

记忆片段保存在 `memories` 中。数据库还保留 `raw_memory_ledger` 等旧结构，供兼容、原文保留和备份使用。旧表还在，不代表旧功能仍在跑；但“不再参与召回”也不代表内容已经可以丢掉。

当前完整备份格式是 **22**，支持旧格式恢复。历史消息是否包含要看导出选项，网页默认走轻量备份；向量派生索引恢复后重建。浏览器桌面数据有单独的导出入口。

## 6. 这段时间加了什么，哪些已经退役

下面按功能归纳，不逐条抄界面微调提交；日期依据 Git 历史。

| 时间 | 改了什么 | 对主干的影响 |
| --- | --- | --- |
| 9 月上旬 | 网页直接聊天、显式会话激活、防止切换后串会话、日记与 Pending 记忆管理 | 扩展了聊天入口和记忆管理，现已是日常功能 |
| 9 月中下旬 | 窗口上下文、临时摘要、分任务模型、多供应商、固定/流动缓存块、Pending CRUD | 进入请求组装、数据结构和缓存主干，不能当皮肤删 |
| 9 月底至 10 月 1 日 | 从碎片提取转向历史原句召回，保留主动向量搜索，退役碎片功能 | 旧“碎片抽取、衰减、自动整理”不再是当前工作流；旧数据和账本保留 |
| 10 月 2 日 | 会话额外提示词、注入位置/频率和追踪、日记作者、纸张式管理界面 | 前者是上下文逻辑，后者大多是表现层，两者不要混为一谈 |
| 10 月 8 日 | 将召回冻结在用户轮次中，摘要只读干净原文 | 是历史重放和缓存正确性的关键约定 |
| 10 月 12 日 | Nocturne 自动召回、交接摘要异步提炼写入、旧日记迁移和逐篇试迁 | 可选外接记忆系统；迁移界面是临时工具 |
| 10 月 13—16 日 | Nocturne 检索诊断和关键词回退、独立跨对话召回开关、轻量备份默认行为和恢复修复 | 检索及数据恢复行为有变化，不只是 UI |
| 10 月 17 日 | 可复用会话提示词预设、页面加载优化、静态资源版本和压缩 | 预设进入数据库及格式 19 备份；其余改善页面响应 |
| 10 月 18—19 日 | 客户端工具调用先落库再流式发送、心跳调度/供应商修复、服务端聊天模型和 API 表单预设 | 工具续场和路由属于主干正确性修复 |
| 10 月 19—20 日 | Merle 风格手机桌面、应用内导航、壁纸库、头像名称、聊天气泡/时间/reasoning 展示、设置和日记重做 | 大量改动集中在网页表现层，但 reasoning 保存和供应商复用也涉及后端 |
| 10 月 20 日 | 删除不用的日记摘要生成及其配置 | 不要恢复成“日记自动摘要模型”；compact、临时摘要、关键词生成和合并仍是各自独立的功能 |

追具体实现可从这些提交找：`f2450bf`（召回冻结）、`f3ed0dd`（Nocturne 召回）、`c67eb25`（提炼队列）、`ccfabcd`（独立跨会话召回）、`0d420ff`（提示词预设）、`c725235`（客户端工具落库）、`0403bc1`（心跳供应商）、`b266352` / `7008886`（手机桌面）、`5b1ba32`（移除日记摘要生成）。

## 7. 哪些是核心，哪些删了也不会塌

这里必须分清：**一个功能可以不用，不等于它对应的文件今天就能直接删除。** `main.py` 有顶层导入，也会在启动和退出时调用一些可选模块。

### 主干：改动时要一起看调用方和数据库

- `main.py`、`database.py`、`prompt_manager.py`：聊天、提示词和持久化骨架。
- 活动会话的归属、消息 `content` / `content_json` 的区别、工具记录与续场：否则会发生串会话、重复注入或工具上下文丢失。
- 固定区/流动区、Pending 确认、交接事务、备份恢复兼容：这几块守的是用户数据和记忆语义。
- 供应商路由、鉴权、流式协议和缓存位置：改坏了会直接影响访问、回答或成本。

PostgreSQL 现在也是实际启动依赖：即使 `MEMORY_ENABLED=false`，启动仍会初始化会话和提示词表，不能靠这个开关省掉数据库。

### 功能可以关闭；真要删代码，需要成套拆

| 功能 | 不用它会怎样 | 如果想彻底移除，要处理什么 |
| --- | --- | --- |
| 手机桌面、壁纸、小组件、主题、配图和字体 | 后端 API 聊天不靠它们；网页外观和交互会减少 | 模板引用、JS 初始化、CSS 依赖和静态资源版本；不能只删所有带 `paper` 的文件 |
| 整套 Dashboard | 外部 API 可以继续作为入口，但失去网页聊天和管理能力 | 网页路由、模板和静态挂载；设置、激活会话和 Pending 仍要有可用管理方式 |
| Ash 原句自动召回 / 主动向量搜索 | 不补充旧原句也能聊天；主动向量搜索没有配置就不可用 | 工具注册、检索调用、启动索引任务、设置和测试；`conversation_recall.py` 同时被向量搜索复用，不能只看自动召回开关 |
| 心跳 | 关掉后只有用户主动发消息才触发正常聊天 | worker、唤醒事件、活动记录、领取令牌和设置入口 |
| OCR | 不配置时按原有图片流程处理，不额外识字 | 预处理调用、模型任务设置、相关界面 |
| 额外提示词和预设、用量图表、日记总结/关键词工具 | 不影响最基础的一问一答，但会损失相应功能 | 提示词注入与重放、API、页面和备份结构各自的引用，不能只删表 |
| `dashboard_delivery.py` | 不压缩也能提供服务，但页面传输更重 | 它被顶层导入并注册为中间件，先移除引用才能删文件 |

### 不属于运行主干的材料

- [`archive/COMMIT_SUMMARY.md`](archive/COMMIT_SUMMARY.md)、各专题说明、迁移说明等 Markdown 不参与服务运行。可以整理归档，但会损失维护知识；`LICENSE` 还承担版权许可说明。
- `seed_memories_example.py` 不参与启动；不用示例导入流程可以移出部署包。
- Python/测试缓存可再生；本地依赖环境可重建；`tests/` 可以不放进部署镜像，但建议保留在源码仓库。
以上都是架构判断，**这次只写说明，没有删除、关闭或迁移任何功能和数据**。

## 8. Claude 接下来改代码，先从哪里看

| 需求 | 先看 |
| --- | --- |
| 发消息、路由、流式回答、工具续场 | `main.py` 的 `chat_completions()` 和两套 tool loop；网页侧看 `context-chat.js` |
| 人格没更新、提示词重复、缓存命中不对 | `prompt_manager.py`、`build_system_prompt_with_memories()`、`_freeze_managed_turn_context()` 和缓存辅助函数 |
| 串会话、切换/摘要异常 | `main.py` 的命令处理、`database.py` 的活动会话和切换事务 |
| 自动想起不相关内容 | `build_dynamic_turn_block()`，检查片段筛选、相关度排序和上下文去重 |
| 模型主动搜索不到历史 | `conversation_search.py`、`conversation_recall.py` 的索引 worker、Embedding 配置 |
| 记忆修改没有生效 | 内置工具是否创建 Pending、是否批准，及 `apply_pending_standing_memory_operation()` |
| 桌面、页面导航、聊天样式 | `phone-shell.*`、`merle-phone.*`、`phone-chat.*`、`context.html`；也查模板内联 JS |
| 日记界面/整理 | `memory-notebook.js`、`dashboard.js`、日记 API、`diary_monthly.py`；旧合并提案确认见 `diary_merge.py` |
| 备份丢项或恢复行为 | `main.py` 的导入导出入口、`database.py` 的备份迭代和恢复函数 |

修改前用 `rg` 查调用和模板引用。改聊天、持久化或切换时，优先跑 `tests/` 中对应的 unittest；例如 `python -m unittest discover -s tests -p 'test_dashboard_chat.py'`。Python 环境需先具备依赖，部分检查另需 Node 或浏览器。

相关细节继续看 [README.md](../README.md)、[DASHBOARD_PHONE.md](DASHBOARD_PHONE.md)、[DASHBOARD_PERFORMANCE.md](archive/DASHBOARD_PERFORMANCE.md)。专题文档可能描述不同阶段，遇到冲突以当前调用链和测试为准。
