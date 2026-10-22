#!/usr/bin/env python3
"""Loopback OpenAI-compatible gateway for Cursor BYOK -> DeepSeek."""

from __future__ import annotations

import json
import hmac
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tomllib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("CURSOR_MODEL_ROUTER_CONFIG", ROOT / "config.toml"))
ENV_PATH = ROOT / ".env"
MAX_BODY_BYTES = 64 * 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 300


def _load_env_file() -> None:
    """Load simple KEY=value entries without printing or exporting secrets elsewhere."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


_load_env_file()
with CONFIG_PATH.open("rb") as _config_file:
    CONFIG = tomllib.load(_config_file)
MODEL_PRESETS: dict[str, dict[str, object]] = CONFIG.get("models", {})
HOST = str(CONFIG.get("server", {}).get("host", "127.0.0.1"))
PORT = int(CONFIG.get("server", {}).get("port", 18881))
GATEWAY_TOKEN_ENV = str(CONFIG.get("server", {}).get("gateway_token_env", ""))
TOKENIZER_FILE = Path(CONFIG.get("tokenizer_path", ".deepseek-tokenizer.json"))
if not TOKENIZER_FILE.is_absolute():
    TOKENIZER_FILE = ROOT / TOKENIZER_FILE
SELECTION_FILE = Path(
    CONFIG.get("server", {}).get(
        "selection_file", "~/.config/cursor-model-router/selection.json"
    )
).expanduser()

try:
    from tokenizers import Tokenizer

    TOKENIZER = Tokenizer.from_file(str(TOKENIZER_FILE))
except (ImportError, OSError, ValueError):
    TOKENIZER = None

def _text_token_count(value: object) -> int:
    """Count text with the official tokenizer and conservatively budget images."""
    if isinstance(value, str):
        if TOKENIZER is None:
            # Fallback remains conservative enough to prevent gross overflow.
            return max(1, (len(value.encode("utf-8")) + 1) // 2)
        return len(TOKENIZER.encode(value).ids)
    if isinstance(value, list):
        return sum(_text_token_count(item) for item in value)
    if isinstance(value, dict):
        if value.get("type") in ("image_url", "input_image"):
            return 1024
        return sum(_text_token_count(k) + _text_token_count(v) for k, v in value.items())
    return 0


def _message_token_count(message: object) -> int:
    # Account for role, message separators, and tool-call framing.
    return _text_token_count(message) + 8


def _fit_context(body: dict[str, object], context_limit: int, output_reserve: int) -> tuple[int, int]:
    """Drop oldest complete user turns while keeping system prompts and latest turn."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return 0, 0

    static_cost = sum(
        _message_token_count(message)
        for message in messages
        if isinstance(message, dict) and message.get("role") in ("system", "developer")
    )
    static_cost += _text_token_count(body.get("tools", []))

    # A 5% safety margin covers tokenizer framing and provider-side formatting.
    budget = int(max(0, context_limit - output_reserve) * 0.95)

    def total_cost() -> int:
        return static_cost + sum(
            _message_token_count(message)
            for message in messages
            if isinstance(message, dict) and message.get("role") not in ("system", "developer")
        )

    removed_messages = 0
    while total_cost() > budget:
        first_user = next(
            (i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "user"),
            None,
        )
        last_user = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if isinstance(messages[i], dict) and messages[i].get("role") == "user"),
            None,
        )
        if first_user is None or first_user == last_user:
            break

        # Remove the oldest user turn and all assistant/tool messages before
        # the next user turn, preserving system/developer messages in place.
        next_user = next(
            (i for i in range(first_user + 1, len(messages))
             if isinstance(messages[i], dict) and messages[i].get("role") == "user"),
            None,
        )
        if next_user is None or next_user > last_user:
            break
        retained = [
            message for i, message in enumerate(messages)
            if i >= next_user or (isinstance(message, dict) and message.get("role") in ("system", "developer"))
        ]
        removed_messages += len(messages) - len(retained)
        messages[:] = retained

    final_cost = total_cost()
    if final_cost > budget:
        raise ValueError(f"Current prompt is approximately {final_cost:,} tokens; selected context preset allows {budget:,}. Choose a larger context preset or reduce the current prompt.")
    body["messages"] = messages
    return final_cost, removed_messages


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _model_available(preset: dict[str, object]) -> bool:
    """Only advertise configured models; Cursor-key fallback is explicit."""
    if preset.get("hidden_from_picker", False):
        return False
    key_name = str(preset.get("api_key_env", ""))
    if preset.get("requires_api_key", False):
        return bool(key_name and os.environ.get(key_name))
    if key_name and os.environ.get(key_name):
        return True
    return bool(preset.get("cursor_api_key_fallback", False))


def _read_selection() -> dict[str, object]:
    try:
        selection = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return selection if isinstance(selection, dict) else {}


def _effective_preset(alias: str, preset: dict[str, object]) -> dict[str, object]:
    """Apply the locally selected context and reasoning to one base model ID."""
    effective = dict(preset)
    selection = _read_selection()
    if selection.get("model") != alias:
        return effective

    context_options = preset.get("context_options", [])
    selected_context = selection.get("context_tokens")
    if isinstance(context_options, list) and selected_context in context_options:
        effective["context_tokens"] = int(selected_context)

    effort_options = preset.get("reasoning_options", [])
    selected_effort = selection.get("reasoning_effort")
    if isinstance(effort_options, list) and selected_effort in effort_options:
        if selected_effort == "fast":
            effective["thinking"] = False
            effective.pop("reasoning_effort", None)
        else:
            effective["thinking"] = True
            effective["reasoning_effort"] = selected_effort
    return effective


def _anthropic_request(body: dict[str, object], model: str) -> dict[str, object]:
    system_parts: list[str] = []
    messages: list[dict[str, object]] = []
    for message in body.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content", "")
        if role in ("system", "developer"):
            system_parts.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
            continue
        if role == "tool":
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""), "content": content}]})
            continue
        if role not in ("user", "assistant"):
            continue
        blocks: list[dict[str, object]] = []
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    image_url = part.get("image_url", {})
                    url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                    if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                        media, data = url[5:].split(";base64,", 1)
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
                    elif isinstance(url, str):
                        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        if role == "assistant":
            for call in message.get("tool_calls", []) if isinstance(message.get("tool_calls", []), list) else []:
                fn = call.get("function", {}) if isinstance(call, dict) else {}
                try:
                    arguments = json.loads(fn.get("arguments", "{}"))
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                blocks.append({"type": "tool_use", "id": call.get("id", ""), "name": fn.get("name", ""), "input": arguments})
        messages.append({"role": role, "content": blocks or [{"type": "text", "text": ""}]})

    result: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_tokens": body.get("max_tokens", 8192),
        "stream": bool(body.get("stream", False)),
    }
    if system_parts:
        result["system"] = "\n\n".join(system_parts)
    for key in ("temperature", "top_p", "metadata"):
        if key in body:
            result[key] = body[key]
    if "stop" in body:
        result["stop_sequences"] = body["stop"]
    if "tools" in body and isinstance(body["tools"], list):
        result["tools"] = [
            {"name": tool.get("function", {}).get("name", ""),
             "description": tool.get("function", {}).get("description", ""),
             "input_schema": tool.get("function", {}).get("parameters", {"type": "object", "properties": {}})}
            for tool in body["tools"] if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        ]
    if "tool_choice" in body:
        choice = body["tool_choice"]
        if choice == "auto":
            result["tool_choice"] = {"type": "auto"}
        elif choice == "none":
            result.pop("tools", None)
        elif choice == "required":
            result["tool_choice"] = {"type": "any"}
        elif isinstance(choice, dict):
            result["tool_choice"] = {"type": "tool", "name": choice.get("function", {}).get("name", "")}
    effort = body.get("reasoning_effort")
    if isinstance(effort, str):
        result["output_config"] = {"effort": effort}
    return result


def _anthropic_to_openai_response(payload: dict[str, object], model_alias: str) -> dict[str, object]:
    content: list[str] = []
    tool_calls: list[dict[str, object]] = []
    for block in payload.get("content", []) if isinstance(payload.get("content", []), list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            content.append(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            tool_calls.append({"id": block.get("id", ""), "type": "function", "function": {"name": block.get("name", ""), "arguments": json.dumps(block.get("input", {}), ensure_ascii=False)}})
    finish = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length"}.get(payload.get("stop_reason"), "stop")
    message: dict[str, object] = {"role": "assistant", "content": "".join(content) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = payload.get("usage", {})
    return {"id": payload.get("id", "chatcmpl-cursor-router"), "object": "chat.completion", "created": 0, "model": model_alias,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)}}


def _openai_chunk(model: str, chunk: dict[str, object]) -> bytes:
    return ("data: " + json.dumps({"id": "chatcmpl-cursor-router", "object": "chat.completion.chunk", "created": 0, "model": model, "choices": [{"index": 0, **chunk}]}, ensure_ascii=False) + "\n\n").encode()


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep operational logs free of request bodies and authorization data.
        super().log_message(fmt, *args)

    def _send_json(self, status: int, payload: object) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        """Optionally require a shared bearer token before allowing paid requests."""
        if not GATEWAY_TOKEN_ENV:
            return True
        expected = os.environ.get(GATEWAY_TOKEN_ENV, "")
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self._send_json(200, {"ok": True, "service": "cursor-model-router"})
            return
        if self.path.rstrip("/") == "/v1/router/profiles":
            profiles = []
            for alias, preset in MODEL_PRESETS.items():
                if preset.get("selector_enabled") and _model_available(preset):
                    profiles.append({
                        "id": alias,
                        "label": str(preset.get("display_name", alias)),
                        "context_options": preset.get("context_options", [preset.get("context_tokens", 1_048_576)]),
                        "default_context_tokens": int(preset.get("context_tokens", 1_048_576)),
                        "reasoning_options": preset.get("reasoning_options", []),
                        "default_reasoning_effort": preset.get("reasoning_effort", "high") if preset.get("reasoning_options") else "",
                    })
            self._send_json(200, {"data": profiles})
            return
        if self.path.rstrip("/") == "/v1/router/selection":
            selection = _read_selection()
            preset = MODEL_PRESETS.get(selection.get("model")) if isinstance(selection.get("model"), str) else None
            if not isinstance(preset, dict) or not _model_available(preset):
                selection = {}
            self._send_json(200, {"data": selection})
            return
        if self.path.rstrip("/") == "/v1/models":
            models = [
                {"id": alias, "object": "model", "owned_by": "cursor-model-router"}
                for alias, preset in MODEL_PRESETS.items()
                if _model_available(preset)
            ]
            self._send_json(200, {"object": "list", "data": models})
            return
        self._send_json(404, {"error": {"message": "Not found"}})

    def do_POST(self) -> None:
        if self.path == "/v1/router/selection":
            if not self._authorized():
                self._send_json(401, {"error": {"message": "Invalid or missing gateway bearer token"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    self._send_json(413, {"error": {"message": "Selection body is empty or too large"}})
                    return
                selection = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": {"message": "Selection must be valid JSON"}})
                return
            if not isinstance(selection, dict):
                self._send_json(400, {"error": {"message": "Selection must be a JSON object"}})
                return
            alias = selection.get("model")
            preset = MODEL_PRESETS.get(alias) if isinstance(alias, str) else None
            if not isinstance(preset, dict) or not preset.get("selector_enabled") or not _model_available(preset):
                self._send_json(400, {"error": {"message": "Model is not configured or available"}})
                return
            context_options = preset.get("context_options", [])
            effort_options = preset.get("reasoning_options", [])
            if not context_options:
                context_options = [preset.get("context_tokens", 1_048_576)]
            selected_effort = selection.get("reasoning_effort", "")
            if not effort_options and selected_effort:
                selected_effort = ""
            if selection.get("context_tokens") not in context_options or (effort_options and selected_effort not in effort_options):
                self._send_json(400, {"error": {"message": "Unsupported context or reasoning preset"}})
                return
            try:
                SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = SELECTION_FILE.with_suffix(".tmp")
                temporary.write_bytes(json_bytes({
                    "model": alias,
                    "context_tokens": int(selection["context_tokens"]),
                    "reasoning_effort": selected_effort,
                }))
                os.chmod(temporary, 0o600)
                temporary.replace(SELECTION_FILE)
            except OSError:
                self._send_json(500, {"error": {"message": "Could not save model selection"}})
                return
            self._send_json(200, {"ok": True, "data": selection})
            return
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": {"message": "Not found"}})
            return
        if not self._authorized():
            self._send_json(401, {"error": {"message": "Invalid or missing gateway bearer token"}})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": {"message": "Invalid Content-Length"}})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": {"message": "Request body is empty or too large"}})
            return

        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": {"message": "Request body must be valid JSON"}})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": {"message": "Request body must be a JSON object"}})
            return

        alias = body.get("model")
        preset = MODEL_PRESETS.get(alias)
        if not isinstance(alias, str) or preset is None:
            self._send_json(400, {"error": {"message": "Unknown model alias; check config.toml"}})
            return

        preset = _effective_preset(alias, preset)
        protocol = preset.get("protocol", "openai-chat-completions")
        if protocol not in ("openai-chat-completions", "anthropic-messages"):
            self._send_json(501, {"error": {"message": f"Unsupported upstream protocol: {protocol}"}})
            return
        upstream = str(preset.get("base_url", "")).rstrip("/")
        upstream_model = str(preset.get("model", ""))
        if not upstream.startswith("https://") or not upstream_model:
            self._send_json(500, {"error": {"message": f"Invalid provider configuration for {alias}"}})
            return
        body["model"] = upstream_model
        if "max_completion_tokens" in body and "max_tokens" not in body:
            body["max_tokens"] = body.pop("max_completion_tokens")
        else:
            body.pop("max_completion_tokens", None)

        # Keep output (including reasoning tokens) inside the selected total
        # context window. The provider supports up to 384k output tokens.
        try:
            requested_output = int(body.get("max_tokens", 8192))
        except (TypeError, ValueError):
            requested_output = 8192
        context_limit = int(preset.get("context_tokens", 1024 * 1024))
        output_reserve = min(max(1, requested_output), int(preset.get("max_output_tokens", 384_000)), context_limit // 2)
        body["max_tokens"] = output_reserve
        try:
            _fit_context(body, context_limit, output_reserve)
        except ValueError as exc:
            self._send_json(400, {"error": {"message": str(exc), "type": "context_length_exceeded"}})
            return

        if "thinking" in preset and protocol == "openai-chat-completions":
            body["thinking"] = {"type": "enabled" if preset["thinking"] else "disabled"}
        if preset.get("reasoning_effort"):
            body["reasoning_effort"] = preset["reasoning_effort"]
        elif protocol == "openai-chat-completions":
            body.pop("reasoning_effort", None)

        key_name = str(preset.get("api_key_env", ""))
        api_key = os.environ.get(key_name, "") if key_name else ""
        authorization = f"Bearer {api_key}" if api_key else self.headers.get("Authorization")
        headers = {"Content-Type": "application/json", "User-Agent": "cursor-model-router/0.1"}
        if protocol == "anthropic-messages":
            headers["anthropic-version"] = str(preset.get("anthropic_version", "2023-06-01"))
            headers["Accept"] = "text/event-stream" if body.get("stream") else "application/json"
            if api_key:
                headers["x-api-key"] = api_key
            elif authorization:
                headers["x-api-key"] = authorization.removeprefix("Bearer ")
            upstream_body = _anthropic_request(body, upstream_model)
            endpoint = str(preset.get("endpoint", "/v1/messages"))
            request_url = upstream + (endpoint if endpoint.startswith("/") else "/" + endpoint)
        else:
            headers["Accept"] = self.headers.get("Accept", "application/json")
            if authorization:
                headers["Authorization"] = authorization
            upstream_body = body
            request_url = f"{upstream}/chat/completions"

        request = Request(
            request_url,
            data=json_bytes(upstream_body),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=UPSTREAM_TIMEOUT_SECONDS) as response:
                if protocol == "anthropic-messages" and body.get("stream"):
                    self._relay_anthropic_stream(response, alias)
                elif protocol == "anthropic-messages":
                    payload = json.loads(response.read(MAX_BODY_BYTES))
                    self._send_json(response.status, _anthropic_to_openai_response(payload, alias))
                else:
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    while chunk := response.read(64 * 1024):
                        self.wfile.write(chunk)
                        self.wfile.flush()
        except HTTPError as exc:
            # Relay provider status/body for Cursor diagnostics, without logging.
            payload = exc.read(MAX_BODY_BYTES)
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (TimeoutError, URLError, OSError) as exc:
            reason = "Upstream request timed out" if isinstance(exc, TimeoutError) else "Could not reach the configured provider"
            self._send_json(502, {"error": {"message": reason}})

    def _relay_anthropic_stream(self, response: object, model: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(chunk: dict[str, object]) -> None:
            self.wfile.write(_openai_chunk(model, chunk))
            self.wfile.flush()

        emit({"delta": {"role": "assistant"}, "finish_reason": None})
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "tool_use":
                    emit({"delta": {"tool_calls": [{"index": event.get("index", 0), "id": block.get("id", ""), "type": "function", "function": {"name": block.get("name", ""), "arguments": ""}}]}, "finish_reason": None})
            elif kind == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    emit({"delta": {"content": delta.get("text", "")}, "finish_reason": None})
                elif delta.get("type") == "thinking_delta":
                    emit({"delta": {"reasoning_content": delta.get("thinking", "")}, "finish_reason": None})
                elif delta.get("type") == "input_json_delta":
                    emit({"delta": {"tool_calls": [{"index": event.get("index", 0), "function": {"arguments": delta.get("partial_json", "")}}]}, "finish_reason": None})
            elif kind == "message_delta":
                finish = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length"}.get(event.get("delta", {}).get("stop_reason"), "stop")
                emit({"delta": {}, "finish_reason": finish})
            elif kind == "message_stop":
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), GatewayHandler)
    server.daemon_threads = True
    server.serve_forever()
