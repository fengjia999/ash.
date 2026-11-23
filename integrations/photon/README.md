# Ash 内置 iMessage 收发组件

此目录复用 Photon（来源提交 `138d882`）的 Spectrum 12.8 收发实现，包括图片、Tapback、投票、流式回复和消息合并。它是 Ash 的内部组件，不是第二个部署项目。

- Ash 的 Python supervisor 按需启动 Node 子进程，配置通过 stdin 传入，不出现在进程参数或连接环境变量中。
- 内部 HTTP 控制端口仅监听 `127.0.0.1`，使用每次启动随机生成的凭据，不需映射端口。
- Photon 项目配置保存在 Ash PostgreSQL。子进程不写独立配置文件。状态发现文件只包含本机控制端口和临时凭据，权限为 0600。
- Node 通过本机 Ash 端口和专用 Bot 凭据调用 `/v1/chat/completions`，始终使用 Ash 当前活动会话。所有 iMessage 输入轮次串行处理，前端工具的完整续场不会在不同 iMessage 对象之间交错。
- 保存配置或重连会先结束旧流的接收并处理已接收输入，再更换 Photon 客户端。意外退出后不重放消息；Dashboard 的「重连」可显式重试。
- 未启用时不启动 Node；停用后停止新消息授权并退出；未完成的输入不会自动重放。

Dockerfile 自动构建并打包运行时，只部署 Ash 镜像即可。默认 `python main.py` 单实例部署。

原生 VPS / 本地 Python 部署，在仓库根目录运行：

```sh
python3 scripts/setup_bots.py
```

此命令自动准备 Node、安装 iMessage 与 QQ 依赖并构建收发组件；不需要另外部署桥接服务。Node 路径保存在 `.runtime/bots.json`，供 systemd 和交互式启动共同使用。运行 Ash 的同一用户应拥有仓库与 `.runtime/` 的访问权限。安装完成后重启 Ash，再在 Dashboard 重连。

只读检查：`python3 scripts/setup_bots.py --check`。开发行为测试：`npm test --prefix integrations/photon`（需保留开发依赖）。

Dashboard 保存配置或重连时，自动记录 ASGI 实际监听端口供内部组件回连；使用自定义 uvicorn 端口时无需再单独设置连接环境变量。尚未记录实际端口的旧配置沿用 `PORT`（默认 8080），更新后点一次重连即可。多个本机 ASGI worker 由文件锁共享一个收发进程；跨容器多副本尚不支持单一连接所有权，应先使用一个服务副本。

构建使用 TypeScript 的逐文件转译，避免加载整个 SDK 类型图造成小内存构建环境溢出。`npm run typecheck` 可在资源充足的开发机执行完整类型检查；协议与行为检查使用 Node 测试。生产镜像只保留运行依赖。
