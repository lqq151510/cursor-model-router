# Cursor Model Router

A model router for **Cursor only**. Cursor sends OpenAI Chat Completions requests to this service; the router selects an upstream provider by the custom model name, applies optional context/reasoning presets, and translates supported protocol formats.

- Upstream protocols: OpenAI Chat Completions compatible APIs and Anthropic Messages.
- Example providers: DeepSeek, Alibaba DashScope/Qwen, Zhipu/GLM, Moonshot/Kimi, MiniMax, Tencent Hunyuan, and Anthropic-compatible APIs.
- The server binds to `127.0.0.1` by default and does not log request bodies or authorization headers.
- Provider keys come from `.env` environment variables. The API key sent by Cursor is used only as a fallback when a model has no `api_key_env` value; it can also serve as the public router bearer token.
- Context limits are local budgets. They use the DeepSeek tokenizer when installed; other tokenizers fall back to a conservative UTF-8 byte estimate. The upstream provider remains authoritative and may reject a request.

> This is not a provider SDK. Provider model IDs, endpoints, supported parameters, rate limits and context sizes change. Check the provider's current official documentation before enabling a profile. A custom profile is visible in Cursor even when its key is not configured.

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

The Cursor key is then the router access token. For DeepSeek, either use that same token as the DeepSeek key, or set `DEEPSEEK_API_KEY` in `.env`. Other upstream provider keys belong in their named `.env` variables. The router checks the bearer token before forwarding requests. Never expose the service without authentication.

The quick tunnel URL is temporary and changes when restarted. It is intended for testing; for a stable setup, use a managed tunnel and restrict ingress to this service. Do not commit `.env` or tunnel credentials.

## Configure Cursor

1. Open **Settings → Models → API Keys** and keep OpenAI-compatible model access enabled.
2. Set the OpenAI Base URL to your public HTTPS tunnel URL, ending in `/v1`.
3. In **Settings → Models**, add the model alias IDs from `config.toml` (for example `deepseek-flash-256k-high` or `qwen-example`).
4. Select the alias in Cursor's model picker.

Cursor currently offers no native context-size control for custom BYOK models. The aliases provide selectable profiles in its model picker. The router trims oldest complete user turns when needed, while retaining system/developer messages and the latest user turn. If the current prompt itself exceeds the selected budget, the router returns a clear 400 response instead of silently truncating the latest request.

## Providers and protocol adapters

Each `[models."alias"]` section defines one Cursor-visible model. For example:

```toml
[models."qwen-example"]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-plus"
api_key_env = "DASHSCOPE_API_KEY"
protocol = "openai-chat-completions"
context_tokens = 131072
max_output_tokens = 16384
```

Anthropic Messages providers use the same Cursor-facing endpoint and are translated by the router:

```toml
[models."anthropic-example"]
base_url = "https://api.anthropic.com"
endpoint = "/v1/messages"
model = "claude-sonnet-4-5"
api_key_env = "ANTHROPIC_API_KEY"
protocol = "anthropic-messages"
anthropic_version = "2023-06-01"
context_tokens = 200000
max_output_tokens = 16384
```

The converter handles text, image URLs/data URLs, function tools, reasoning effort, non-streaming responses, and Anthropic SSE events. Vendor-specific features outside those formats are not automatically translated. Test a profile with the provider before relying on it for coding work.

### DeepSeek presets

`config.example.toml` includes 12 aliases across:

- Context budgets: `256k`, `512k`, `1m`
- Reasoning: `low`, `high`, `max`, `fast`

`fast` means DeepSeek non-thinking mode; it is not Cursor's proprietary Fast tier. The selected context value reserves output tokens and applies a 5% safety margin. Token counting is an estimate, especially for images and tool schemas.

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
- [Alibaba Qwen OpenAI-compatible API quick start](https://docs.qwencloud.com/developer-guides/getting-started/first-api-call)
- [Moonshot/Kimi API overview](https://www.kimi.ai/help/kimi-api/api-overview)
- [Tencent Hunyuan OpenAI-compatible API](https://cloud.tencent.com/document/product/1729/111007)
- [MiniMax API platform](https://platform.minimax.io/)
- [Zhipu BigModel documentation](https://docs.bigmodel.cn/)
