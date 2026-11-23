# 手机桌面 Dashboard

前端以早期 Merle 桌面模块为基底。桌面、Dock、分页、拖动、装扮、图片存储和主题预设直接迁入原模块；Ash 负责应用入口、双人头像与网关数据。

## 原模块与适配边界

| Ash 文件 | 来源及改动 |
| --- | --- |
| `static/js/merle-phone.js` | Merle `assets/phone.js`。替换应用注册表、默认布局和存储键；增加双人头像组件、本机备份边界及旧 Ash 布局迁移。保留原有网格、手势、Dock、组件编辑和主题预设实现。 |
| `static/js/merle-phone-media.js` | Merle `assets/phone-storage.js`，仅将数据库名改为 `ash_phone_media_v2`。保留短引用、Blob 缓存、迁移和延迟清理。 |
| `static/css/merle-phone.css` | Merle `assets/phone.css`，原样复制。 |
| `templates/phone-shell.html` 的桌面区域 | Merle `index.html` 中的 `page-phone`。改为 Ash 标识和应用；主题预设面板直接使用原有渲染逻辑。 |
| `static/css/merle-chat-base.css` | Merle `assets/chat-skin.css`，只适配选择器，保留默认紧凑聊天皮肤。 |
| `phone-shell.js` / `phone-chat.js` | Ash 应用与身份、会话、草稿、流式回复的接线，不再实现另一套桌面或装扮编辑器。 |
| `static/js/phone-viewport.js` | Merle `app.js` 的可视视口与键盘逻辑适配。外层统一调整手机容器，聊天 iframe 同步状态，避免重复缩小。 |

运行时无需访问 Merle 文件或服务，也不连接 Merle 后端。Merle 的音乐、游戏和 App Store 未注册为 Ash 应用。

原先的简化桌面渲染、分页、拖动、装扮编辑器、独立网格副本及旧侧栏 HTML/JS/CSS 已移除。手机聊天使用 `context-tools.css` 提供功能控件，使用 Merle 皮肤提供外观；不再加载旧纸张、标牌和夜间覆盖样式。`context-legacy.css` 仅供仍可独立访问的旧上下文/列表页面使用。

根页面和手机外壳固定在可视区域内。主屏幕只允许桌面页内部滚动；聊天页只滚动消息区，其他应用由内容区滚动。滚动到顶或到底时不向根页面传递滚动，顶部栏、Dock、输入栏和底部导航保持固定。已删除隐藏的旧会话列表 iframe，Chat 只有一套原生会话列表。

安装后的 PWA 用 `100lvh` 铺满画布，键盘打开时才采用实际可视视口高度。外壳不留底部空带：普通应用在滚动区内保留安全区，Chat 导航栏与对话输入栏各自延伸到底边并保护内部按钮。聊天 iframe 从外层接收底部安全区数值，避免依赖 iframe 中可能为零的 `env()`；键盘打开时归零，关闭后恢复。

## 使用

- 每次新加载 Dashboard 显示雾面玻璃开屏，可反复擦拭、画图；三个字母分别擦清后进入主屏幕，也可跳过或按 Escape。浅灰雾面与深色 Ash 沿用原版的柔和外观，密集凝水通过曲面法线采样底图。自然雨滴持续落下，最多四颗同时运动；擦拭会带走静止及下坠的水珠、擦断碰到的水痕；手指停留时也能挡住流入接触区的水珠。积水足够时才偶尔从手指下缘汇聚下滑。水珠碰撞合并并带走路径内的小水珠，水珠平滑偏移、偶尔停顿，沿实际轨迹留下宽窄渐变、数秒淡去的细薄水膜，没有预画线条或虚线擦除。雾层在低分辨率像素上预模糊，不依赖 Safari 的 Canvas filter。擦净的雾面不自动恢复；后台暂停，离开开屏后释放画布与事件监听；设备开启“减少动态效果”时停用水珠运动和淡出。开屏不读写业务数据。
- 长按应用或桌面空白处进入整理；拖动调整格子或放入 Dock，取消拖动恢复原布局。
- 整理时可管理页面、移动应用到指定页或 Dock、隐藏页面和恢复隐藏应用。键盘方向键也沿用原模块。
- 装扮使用 Merle 原面板：壁纸位置/遮罩、逐个图标换图、图标样式/透明度、照片/便签/日历/时钟/纪念日组件及命名主题预设。
- 双人头像保留轻微重叠。头像和昵称是展示信息；人格称呼仍在 Prompt 中设置。
- Chat 有 Chat / Conversation / Cover / Me。Cover 是 Merle 风格的便签墙，可新增、编辑、拖动和整理。Me 查看当前聊天配置并打开收藏列表；配置预设保留在设置页。浏览历史不会激活会话；「继续此会话」才切换网关。新建会话显式创建并激活。
- 聊天模型按钮与底部 ＋ 展开原有管理功能。触屏长按气泡打开复制/收藏/编辑/删除；滑动取消长按，输入时收起菜单。
- 月历卡支持手指横向拖动翻面，背面按月生成、保存和复制助手口吻的日记总结；不再生成常驻记忆提案。模型页入口为「总结日记」，沿用 `diary_merge` 配置键以保留已有模型设置。
- 召回设置页的 Memories 可试搜原话、查看来源和实际注入预览，并试调、保存召回权重。自动召回以 `<system_info>` 临时附在当前用户消息之后，不写回本轮历史；实现与配置见 [MEMORY_RETRIEVAL.md](MEMORY_RETRIEVAL.md)。

月度总结通过后台任务执行，状态和正文保存在 `diary_monthly_summaries`；重复请求复用任务，失败保留上一版正文，不自动重放模型请求。

备份格式 22 起，完整和轻量备份均包含月度总结。恢复保留已有正文并更换任务编号，不恢复运行中的生成请求；版本 2～21 的旧备份仍可导入，由于不含月度总结，恢复时清除当前月度总结，导入预览会明确提示。

## 本地数据

| 数据 | 位置 |
| --- | --- |
| 原生桌面布局、组件、Dock、壁纸和图标引用、主题预设 | localStorage `ash.phone.desktop.v2`，由 Merle 原模块统一管理 |
| 原生桌面图片 | IndexedDB `ash_phone_media_v2` / `images`，元数据只保存 `phone-image:` 短引用 |
| 已上传壁纸图库 | 桌面布局的 `wallpapers` 数组保存图片引用；`wallpaperImage` 指定当前壁纸，图库随本机桌面备份导出、恢复 |
| 展示昵称 | localStorage `ash.phone.v1`，保留 `version: 1` 与 `names`，不再维护第二套布局 |
| 用户/助手头像 | IndexedDB `ash-phone-local` / `assets` 的 `avatar-user`、`avatar-assistant` |
| 收藏 | IndexedDB `ash-phone-local` / `keepsakes`，入口在 Me |
| 便签 | 正文在服务端 `cover_notes`；摆放位置在 `ash.phone.v1.noteLayout` |
| 聊天草稿 | localStorage `ash.phone.draft.<conversationId>` |
| 应用外观（跟随系统／浅色／深色） | localStorage `ash-dashboard-theme`；桌面、应用页和聊天共用 |

首次运行会将旧 `ash.phone.v1` 的布局、便签、壁纸、图标样式与透明度迁入原生桌面，展示昵称和头像保留。旧图片不会因迁移被主动删除。布局、头像、壁纸、图标和草稿均不上传服务器。真实消息、记忆、活跃会话、供应商和路由仍使用 Ash 原接口。

设置 → 备份与导入 → 本机桌面，导出版本 3，包含原生布局、组件/主题图片、昵称、头像以及收藏、便签摆放位置和旧版纪念册封面，不包含未收藏的聊天消息和输入草稿。可导入旧版本 1、2 备份，旧备份不会清空已有收藏。服务器备份与本机桌面备份独立。本机数据按浏览器和站点来源隔离。

收藏使用 IndexedDB `ash-phone-local` 的 `keepsakes` 存储区，原文快照按会话和消息编号去重。旧版 `album-cover` 图片继续随本机备份保留。收藏不会调用模型或写入服务器，原消息后续编辑、删除也不改变已收藏的快照。

桌面外观中的“应用外观”控制全局主题，默认跟随设备，设备明暗变化立即同步所有页面及聊天 iframe。“桌面文字”只调整桌面文字颜色。旧桌面 `mode` 在没有全局偏好时迁入统一主题；桌面备份仍携带 `mode`，导入时恢复全局选择，不再维护第二套桌面明暗状态。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_dashboard*.py'
.venv/bin/python -m unittest discover -s tests -p 'test_identity*.py'
node tests/dashboard_phone.browser.cjs
```

浏览器测试需要 Playwright、Chromium 和 Jinja2，可设置 `PLAYWRIGHT_MODULE` 与 `PYTHON`。`ASH_PHONE_MOBILE=1` 使用手机触控模式；截图位置由 `ASH_SCREENSHOT_DIR` 指定。测试拦截所有服务请求，不连接真实数据库或模型。

回归覆盖原生桌面手势、拖动取消、Dock 与页面移动、壁纸/图标/照片组件、主题预设、持久化和本地备份，以及 Ash 会话隔离、草稿、流式成功/失败、供应商和苏醒配置。键盘几何使用模拟 visualViewport，不代替 iPhone Safari 实机测试。

Cover 便签正文使用现有 PostgreSQL，不依赖外部记忆库。内置 `create_note` 工具将助手便签写入同一张墙；UI 可新增、编辑和删除。工具不自动调用模型、不做摘要、不注入召回。全量服务端备份版本 20 包含便签正文；版本 2–19 仍可导入，旧全量备份恢复时便签为空。便签编辑与删除检查 revision，防止旧页面覆盖新内容。
