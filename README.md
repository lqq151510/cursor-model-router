# Cursor Model Router

[简体中文](README.zh-CN.md) | English

A model router for **Cursor only**. Cursor sends OpenAI Chat Completions requests to this service; the router selects an upstream provider by the custom model name, applies optional context/reasoning presets, and translates supported protocol formats. The bundled Cursor extension adds a compact status-bar picker for presets, so context and reasoning choices do not need separate model names.

- Upstream protocols: OpenAI Chat Completions compatible APIs and Anthropic Messages.
- Verified profiles in the example config: DeepSeek V4.1 Flash, Qwen3.8 Flash, GLM-5.3, Kimi K3/K2.6, MiniMax M3.1-Flash, and Claude Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Haiku 5.5. OpenAI/GPT models are deliberately not added.
- The server binds to `127.0.0.1` by default and does not log request bodies or authorization headers.
- Provider keys come from `.env` environment variables. When a configured provider key is empty, the router can forward the API key Cursor sends; this supports DeepSeek's direct-key setup. For public access, configure the router bearer token and upstream keys separately where needed.
- `/v1/models` only advertises models allowed by the local config and configured API keys. Example providers stay hidden until their key exists.
- The extension's status-bar Quick Pick updates a local selection file; the gateway applies that selection when Cursor sends the model's base alias.
- Context choices are local request budgets capped by each model's documented context window. They use the DeepSeek tokenizer when installed; other tokenizers fall back to a conservative UTF-8 byte estimate. The upstream provider remains authoritative and may reject a request.

> This is not a provider SDK. Provider model IDs, endpoints, supported parameters, rate limits and context sizes change. Check the provider's current official documentation before enabling a profile. The router hides profiles whose required API key is missing; older custom entries that were manually added to Cursor must be disabled once in **Settings → Models**.

## Quick start (macOS/Linux)

```sh
cd cursor-model-router
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Edit .env and add the API keys for the providers you plan to use.
cp config.example.toml config.toml
./scripts/download-tokenizer.sh
.venv/bin/python gateway.py
```

The health endpoint is `http://127.0.0.1:18881/health`; available aliases are listed at `/v1/models`.

## Cursor connectivity requirement

Cursor currently builds BYOK prompts on Cursor servers. Those servers cannot reach your computer's `localhost` or LAN address, so setting the Base URL to `http://127.0.0.1:18881/v1` returns `Access to private networks is forbidden` before this router receives a request. A Cursor connection requires a publicly reachable HTTPS endpoint.

For local development, use `curl` against the loopback health and models routes. To connect Cursor, use a managed HTTPS host or a tunnel such as Cloudflare Tunnel. A public endpoint exposes a path to paid model APIs, so enable bearer authentication first:

1. Put a strong token in local `.env` as `CURSOR_ROUTER_TOKEN=...` and set `server.gateway_token_env = "CURSOR_ROUTER_TOKEN"` in `config.toml`.
2. Restart the gateway so it requires that token for every chat completion request.
3. Start a tunnel only after the authenticated endpoint is ready. `scripts/start-public-tunnel.sh` starts a temporary Cloudflare quick tunnel to the loopback server; Cloudflare carries requests to this computer, which must stay online.
4. Put the same token in Cursor's OpenAI API Key field and set Base URL to the HTTPS URL printed by `cloudflared`, ending in `/v1`.
5. In Cursor, run **Cursor Model Router: Set Local Router Token** once so the extension can authenticate preset changes against the same router.

The Cursor key is then the router access token. Set each upstream provider key in its named `.env` variable (for example, `DEEPSEEK_API_KEY`); the router token is not a provider key. When using a local gateway without router authentication, the gateway can forward Cursor's provider key as a fallback. Never expose the service without authentication.

The quick tunnel URL is temporary and changes when restarted. It is intended for testing; for a stable setup, use a managed tunnel and restrict ingress to this service. Do not commit `.env` or tunnel credentials.

## Configure Cursor

1. Open **Settings → Models → API Keys** and keep OpenAI-compatible model access enabled.
2. Set the OpenAI Base URL to your public HTTPS tunnel URL, ending in `/v1`.
3. In **Settings → Models**, add one base model alias for each configured provider (for example `deepseek-flash`). Do not add the hidden `deepseek-flash-256k-*` compatibility aliases.
4. Build the dependency-free extension package with `python3 scripts/package_cursor_extension.py`, then use Cursor's **Install from VSIX** command to install the generated `.vsix` file.
5. In the Cursor editor window, click **模型档位** on the status bar (or run **Cursor Model Router: Edit Model Profile**) and choose the model, context, and reasoning effort. Then choose the same base model in Cursor's model picker.

The editor extension keeps the compact picker beside the editor. For Cursor Agent, configure the local MCP server below; Agent can list configured profiles and switch the router selection for subsequent requests. Cursor's built-in Agent model picker still chooses the base model alias, so choose the same model in both places. The router trims oldest complete user turns when needed, while retaining system/developer messages and the latest user turn. If the current prompt itself exceeds the selected budget, the router returns a clear 400 response instead of silently truncating the latest request.

## Providers and protocol adapters

Each `[models."alias"]` section defines one Cursor-visible model. The example config contains actual provider model IDs and advertises each only when its corresponding API key is present. For example:

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

Anthropic Messages providers use the same Cursor-facing endpoint and are translated by the router:

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

The converter handles text, image URLs/data URLs, function tools, adaptive thinking, reasoning effort, non-streaming responses, and Anthropic SSE events. For Claude tool loops, the gateway keeps signed thinking blocks in process memory keyed by tool-call ID and replays them unchanged on the following tool result request. A gateway restart clears this short-lived cache. Vendor-specific features outside those formats are not automatically translated. Test a profile with the provider before relying on it for coding work.

### DeepSeek presets

The `deepseek-flash` base alias provides a selectable profile across:

- Context budgets: `256k`, `512k`, `1m`
- Reasoning effort: `low`, `high`, `max`, plus `非思考` (DeepSeek thinking disabled)

The non-thinking choice sends DeepSeek's documented `thinking.type=disabled`; it is not Cursor's proprietary Fast tier. The selected context value reserves output tokens and applies a 5% safety margin. Token counting is an estimate, especially for images and tool schemas. Compatibility aliases remain in the example config for older chats but are hidden from the advertised model list.

### Provider-specific capabilities

The selector displays only options configured for that exact upstream model:

| Provider model | Context budgets | Thinking controls |
|---|---|---|
| DeepSeek V4.1 Flash | 256K / 512K / 1M | non-thinking, low / high / max |
| Qwen3.8 Flash | 256K / 512K / 1M | non-thinking, low / medium / xhigh |
| GLM-5.3 | 256K / 512K / 1M | low / high / max; cannot disable thinking |
| Kimi K3 | 256K / 512K / 1M | low / high / max; thinking always enabled |
| Kimi K2.6 | 128K / 256K | thinking / non-thinking; no effort levels |
| MiniMax M3.1-Flash | 256K / 512K / 1M | low / medium / high / xhigh / max; cannot disable thinking |
| Claude Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5 | 256K / 512K / 1M | adaptive thinking and supported effort levels; no non-thinking toggle |

These are request-time controls forwarded to each provider API. The router does not manufacture context capacity or provider speed modes. Low effort can reduce reasoning work, but it is not labeled as a separate Fast mode unless the provider documents one.

### Cursor extension

`cursor-extension/` contains a dependency-free VS Code extension that runs in Cursor's editor window. It reads configured profiles from `GET /v1/router/profiles` and writes the selected profile to `POST /v1/router/selection`. The selection endpoint uses the same optional bearer-token check as chat requests. When no API key is configured for a model marked `requires_api_key`, the model is hidden from both the selector and `/v1/models`.

### Cursor Agent MCP control

Agent can change the model-router profile through local MCP tools. Add this server to `~/.cursor/mcp.json` (merge into an existing `mcpServers` object and replace the path with the absolute path to your clone):

```json
{
  "mcpServers": {
    "cursor-model-router": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/cursor-model-router/mcp_server.py"]
    }
  }
}
```

Reload Cursor MCP servers. In Agent, enable `list_cursor_model_profiles` and `set_cursor_model_profile`. Ask Agent to list profiles, then set an available model alias, context budget, and a listed reasoning profile ID. The choice applies to subsequent calls routed through the gateway. Keep the local MCP server available only to trusted local Cursor sessions; provider API keys stay in your router `.env`.

## Run as a macOS LaunchAgent

Copy `launchd/com.zebao.cursor-model-router.plist.example` to `~/Library/LaunchAgents/com.zebao.cursor-model-router.plist`, edit paths if needed, then:

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.zebao.cursor-model-router.plist
```

To stop it:

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.zebao.cursor-model-router.plist
```

## Security notes

- Keep `.env` out of Git and restrict it to your user (`chmod 600 .env`).
- Do not bind to `0.0.0.0` on an untrusted network. Configure `gateway_token_env` before enabling any public tunnel.
- The router forwards prompts and code to the configured provider, as Cursor would when configured directly.
- Logs contain request method/path only; never enable HTTP debug logging around credentials or prompts.
- This project cannot add capabilities that Cursor itself does not expose and does not modify Cursor's application bundle.

## Roll back

Set Cursor's Base URL back to the provider's official URL, stop the LaunchAgent, and remove the local project/configuration if desired. Custom aliases can be removed in Cursor's model settings.

## License

MIT. See [LICENSE](LICENSE).

## Official provider documentation

Verify model IDs and feature compatibility against the provider before using a profile:

- [DeepSeek Chat Completions and reasoning controls](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Qwen3.8 Flash model limits](https://help.aliyun.com/zh/model-studio/qwen3-8-flash) and [OpenAI-compatible reasoning controls](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [Kimi model list](https://platform.kimi.ai/docs/models) and [thinking controls](https://platform.kimi.ai/docs/guide/use-thinking-models)
- [MiniMax model invocation and thinking effort](https://platform.minimax.io/docs/guides/text-generation)
- [GLM-5.3 context and thinking controls](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)
- [Claude model overview](https://platform.claude.com/docs/en/models/overview) and [effort controls](https://platform.claude.com/docs/en/build-with-claude/effort)
