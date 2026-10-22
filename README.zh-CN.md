# Cursor Model Router

简体中文 | [English](README.md)

这是一个**仅面向 Cursor** 的模型路由器。Cursor 将 OpenAI Chat Completions 格式的请求发给本服务；路由器根据自定义模型名选择上游服务，按实际选择应用上下文预算和思考参数，并适配支持的协议。配套扩展在编辑器状态栏提供紧凑的档位选择，不需要为每个档位创建独立模型名。

- 支持的上游协议：OpenAI Chat Completions 兼容接口、Anthropic Messages。
- 示例配置已核对的模型：DeepSeek V4.1 Flash、Qwen3.8 Flash、GLM-5.3、Kimi K3/K2.6、MiniMax M3.1-Flash，以及 Claude Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Haiku 5.5。**不添加 OpenAI/GPT 模型。**
- 服务默认只监听 `127.0.0.1`，不记录请求正文或授权头。
- 厂商 API Key 从本机 `.env` 读取。对应密钥未配置时，模型不会出现在 `/v1/models` 或档位选择器中。
- 编辑器扩展和 Agent MCP 共用本机档位选择；网关收到基础模型别名请求时应用当前选择。
- 上下文档位是实际生效的本地请求预算，并且不会超过相应模型文档所列的窗口上限。安装 DeepSeek 官方 tokenizer 后会用它计数；其他模型使用偏保守的 UTF-8 字节估算。最终仍以上游模型的限制和返回为准。

> 这不是厂商 SDK。模型 ID、地址、参数、限流和上下文规格可能变化。启用模型前请再核对厂商官方文档。仓库不包含任何用户的 API Key、隧道地址或本机配置。

## 快速开始（macOS/Linux）

```sh
git clone https://github.com/lqq151510/cursor-model-router.git
cd cursor-model-router
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# 编辑 .env，只填写自己已经开通的厂商 API Key
cp config.example.toml config.toml
./scripts/download-tokenizer.sh
.venv/bin/python gateway.py
```

健康检查地址为 `http://127.0.0.1:18881/health`；`/v1/models` 只列出已配置且有对应 API Key 的模型。

## Cursor 连接要求

Cursor 的 BYOK 请求可能由 Cursor 服务端构造，服务端无法访问你电脑的 `localhost` 或局域网地址。因此，如果 Cursor 提示禁止访问私有网络，需要让网关通过受保护的 HTTPS 地址可达。

本地开发时可直接用 `curl` 检查回环地址。要连接 Cursor，可使用自己管理的 HTTPS 主机或 Cloudflare Tunnel。公网入口能够触发付费模型请求，必须先开启 Bearer 身份验证：

1. 在本机 `.env` 设置强随机值 `CURSOR_ROUTER_TOKEN=...`，并在 `config.toml` 设置 `server.gateway_token_env = "CURSOR_ROUTER_TOKEN"`。
2. 重启网关，确认聊天请求必须带该令牌。
3. 仅在鉴权已验证后启动隧道。`scripts/start-public-tunnel.sh` 会启动临时 Cloudflare Quick Tunnel；网关所在电脑需保持开机。
4. 在 Cursor 的 OpenAI API Key 字段填写**路由器令牌**，Base URL 填隧道 HTTPS 地址并以 `/v1` 结尾。
5. 在 Cursor 编辑器运行 **Cursor Model Router: Set Local Router Token**，让扩展也能认证本地档位选择请求。

路由器令牌不是厂商 API Key。通过公网隧道时，请把 DeepSeek、Qwen、GLM、Kimi、MiniMax 或 Anthropic 的密钥分别放进 `.env` 对应变量。未开启网关鉴权的纯本地配置可以转发 Cursor 请求中的厂商密钥，但不要把这种模式暴露到公网。

Cloudflare 临时隧道地址重启后会改变，只适合测试。长期使用请配置稳定的受控隧道。不要提交 `.env` 或隧道凭据。

## 配置 Cursor

1. 打开 **Settings → Models → API Keys**，启用 OpenAI 兼容模型访问。
2. 将 OpenAI Base URL 设为你的 HTTPS 隧道地址，以 `/v1` 结尾。
3. 在 **Settings → Models** 为已配置的厂商添加一个基础模型别名，例如 `deepseek-flash` 或 `qwen3.8-flash`。不要把隐藏的旧 DeepSeek 兼容别名逐个添加到模型列表。
4. 运行 `python3 scripts/package_cursor_extension.py` 构建扩展，然后用 Cursor 的 **Install from VSIX** 命令安装生成的 `.vsix` 文件。
5. 在 Cursor 编辑器状态栏点击 **模型档位**，或执行 **Cursor Model Router: Edit Model Profile**，选择模型、上下文预算和该模型支持的思考档位。随后在 Cursor 模型列表中选择相同的基础模型。

编辑器扩展会在编辑器窗口提供紧凑档位选择。若要在 Cursor Agent 窗口直接点击调节，可选择安装本机客户端补丁：完全退出 Cursor 后运行 `python3 scripts/patch_cursor_agent_ui.py install`，重新打开 Cursor 后在 Agent 输入框旁点击“档位”。此补丁在 Agent 窗口内显示选择框，不打开网页。Agent 自带模型菜单仍负责选择基础模型，请选与路由器相同的模型别名。档位切换会影响后续经过网关的请求。网关在超限时会删除最旧的完整对话轮次，并保留系统/开发者消息和最新用户轮次；如果最新请求本身仍超限，会返回 400，而不会静默截断它。

## 模型与协议适配

每个 `[models."alias"]` 配置定义一个 Cursor 可见模型。`config.example.toml` 使用真实上游模型 ID；对应 API Key 填入 `.env` 后才会展示。例如：

```toml
[models."qwen3.8-flash"]
selector_enabled = true
requires_api_key = true
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen3.8-flash"
api_key_env = "DASHSCOPE_API_KEY"
protocol = "openai-chat-completions"
context_tokens = 1000000
context_options = [262144, 524288, 1000000]
max_output_tokens = 131072
```

Claude 使用 Anthropic Messages 协议，由网关转换 Cursor 的 Chat Completions 请求：

```toml
[models."claude-sonnet-5-5"]
selector_enabled = true
requires_api_key = true
base_url = "https://api.anthropic.com"
endpoint = "/v1/messages"
model = "claude-sonnet-5-5"
api_key_env = "ANTHROPIC_API_KEY"
protocol = "anthropic-messages"
anthropic_version = "2023-06-01"
context_tokens = 1000000
context_options = [262144, 524288, 1000000]
max_output_tokens = 128000
```

转换器支持文本、图片 URL / data URL、函数工具、自适应思考、思考力度、非流式响应和 Anthropic SSE 流式事件。Claude Agent 工具循环需要完整保留思考签名块；网关会按工具调用 ID 将签名暂存在进程内存，并在后续工具结果请求中原样带回。重启网关会清除此短期缓存。其他未覆盖的厂商专属能力不会自动转换。

### DeepSeek 档位

`deepseek-flash` 基础别名支持：

- 上下文预算：`256K`、`512K`、`1M`
- 思考力度：`low`、`high`、`max`
- 非思考：向 DeepSeek 发送官方定义的 `thinking.type=disabled`

“非思考”会真正关闭 DeepSeek 思考模式，但不等于 Cursor 自己的 Fast 服务档。预算会扣除输出预留，并留出 5% 安全余量。图片与工具定义的 token 计数仍是估算。旧兼容别名保留在配置中并隐藏，不会显示成大量重复模型。

### 各模型真实能力

选择器只显示对应模型实际配置的选项：

| 模型 | 上下文预算 | 思考控制 |
|---|---|---|
| DeepSeek V4.1 Flash | 256K / 512K / 1M | 非思考、low / high / max |
| Qwen3.8 Flash | 256K / 512K / 1M | 非思考、low / medium / xhigh |
| GLM-5.3 | 256K / 512K / 1M | low / high / max；不能关闭思考 |
| Kimi K3 | 256K / 512K / 1M | low / high / max；始终思考 |
| Kimi K2.6 | 128K / 256K | 思考 / 非思考；没有力度档位 |
| MiniMax M3.1-Flash | 256K / 512K / 1M | low / medium / high / xhigh / max；不能关闭思考 |
| Claude Fable 5.1、Opus 5.5、Sonnet 5.5、Haiku 5.5 | 256K / 512K / 1M | 自适应思考和对应力度；没有非思考开关 |

这些设置会实际成为上游请求参数。网关不会扩大模型窗口，也不会伪造厂商没有提供的速度模式。低思考力度可能降低推理开销，但不会冒称独立的 Fast 模式。

### Cursor 编辑器扩展

`cursor-extension/` 是无需第三方依赖的 VS Code 扩展，可运行在 Cursor 编辑器窗口。它从 `GET /v1/router/profiles` 读取可用配置，并通过 `POST /v1/router/selection` 保存选择。选择接口使用与聊天请求相同的可选 Bearer 校验。标记为 `requires_api_key` 的模型在没有对应密钥时会同时从扩展和 `/v1/models` 中隐藏。

### Cursor Agent 的 MCP 控制（可选备用方式）

不安装客户端补丁时，Cursor Agent 也可通过本机 MCP 在聊天中打开可点击的档位面板。将以下内容合并到 `~/.cursor/mcp.json` 现有的 `mcpServers` 对象中，并把路径替换为你克隆仓库的绝对路径：

```json
{
  "mcpServers": {
    "cursor-model-router": {
      "command": "python3",
      "args": ["/你的绝对路径/cursor-model-router/mcp_server.py"]
    }
  }
}
```

重新加载 Cursor MCP 服务，并启用 `open_cursor_model_profile_picker`、`list_cursor_model_profiles` 和 `set_cursor_model_profile`。在 Agent 的 MCP 工具列表中调用一次 **打开模型档位面板**，之后直接在聊天内的面板点选模型、上下文和思考强度，再点击 **保存档位**。这是嵌入聊天的 MCP App，不会打开单独的浏览器网页。控件只显示已配置模型及其真实支持的选项；保存后应用于后续通过网关的请求。MCP 服务仅在本机 stdio 运行，不接收或返回 API Key；请只在可信的 Cursor 会话中启用它。

## macOS LaunchAgent

将 `launchd/com.zebao.cursor-model-router.plist.example` 复制为 `~/Library/LaunchAgents/com.zebao.cursor-model-router.plist`，按实际路径修改后执行：

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.zebao.cursor-model-router.plist
```

停止服务：

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.zebao.cursor-model-router.plist
```

## 安全说明

- `.env` 不要提交到 Git，并设置为仅当前用户可读写（`chmod 600 .env`）。
- 不要在不可信网络上绑定 `0.0.0.0`。公网隧道必须先设置 `gateway_token_env`。
- 网关会把提示词和代码发送到你配置的厂商，和直接配置该厂商 API 的数据流一致。
- 日志只记录请求方法和路径；不要打开会记录密钥或提示词的调试日志。
- Agent 窗口补丁只访问回环地址 `127.0.0.1:18881`；若网关开启鉴权，令牌只保存在当前 Agent 窗口的会话存储中，关闭窗口即清除。
- Agent UI 补丁修改 Cursor 已签名的应用资源，会使代码签名校验失效。macOS 可能提示应用受损或拒绝启动；补丁脚本会在应用支持目录保存带校验值的原版备份，并提供 `uninstall` 回滚。是否安装由使用者自行决定。
- Cursor 更新会覆盖补丁。升级后先运行 `python3 scripts/patch_cursor_agent_ui.py status`；若显示未安装，再阅读 [补丁维护说明](PATCHING.md) 并核对新版本适配。脚本找不到唯一锚点时会停止，绝不盲目写入。
- 本补丁仅修改本机 Cursor，不应把修改后的 Cursor 应用包或其构建文件提交、分发到 GitHub。

## 回滚

将 Cursor Base URL 改回厂商官方地址，停止 LaunchAgent 和隧道；需要时移除本机项目和配置。可在 Cursor 模型设置中移除自定义别名。

## 许可证

MIT，详见 [LICENSE](LICENSE)。

## 厂商官方文档

启用配置前请核对模型 ID 和能力：

- [DeepSeek Chat Completions 与思考控制](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Qwen3.8 Flash 模型限制](https://help.aliyun.com/zh/model-studio/qwen3-8-flash) 与 [OpenAI 兼容推理参数](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [Kimi 模型列表](https://platform.kimi.ai/docs/models) 与 [思考模式](https://platform.kimi.ai/docs/guide/use-thinking-models)
- [MiniMax 模型调用与思考力度](https://platform.minimax.io/docs/guides/text-generation)
- [GLM-5.3 上下文和思考参数](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)
- [Claude 模型总览](https://platform.claude.com/docs/en/models/overview) 与 [思考力度参数](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Cursor MCP 文档](https://docs.cursor.com/context/model-context-protocol)
