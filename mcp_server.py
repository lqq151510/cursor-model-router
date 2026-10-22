#!/usr/bin/env python3
"""Local MCP controls for Cursor Agent model-router presets."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import gateway


def _profiles() -> list[dict[str, Any]]:
    result = []
    for alias, preset in gateway.MODEL_PRESETS.items():
        if not preset.get("selector_enabled") or not gateway._model_available(preset):
            continue
        contexts = preset.get("context_options") or [preset.get("context_tokens", 1_000_000)]
        result.append({
            "id": alias,
            "label": str(preset.get("display_name", alias)),
            "context_options": contexts,
            "reasoning_options": gateway._reasoning_options(preset),
            "default_context_tokens": int(preset.get("context_tokens", 1_000_000)),
            "default_reasoning_effort": str(preset.get("default_reasoning_effort", "")),
        })
    return result


def _select_profile(arguments: dict[str, Any]) -> dict[str, Any]:
    alias = arguments.get("model")
    preset = gateway.MODEL_PRESETS.get(alias) if isinstance(alias, str) else None
    if not isinstance(preset, dict) or not preset.get("selector_enabled") or not gateway._model_available(preset):
        raise ValueError("Model is not configured or its API key is missing")
    contexts = preset.get("context_options") or [preset.get("context_tokens", 1_000_000)]
    context = arguments.get("context_tokens")
    options = preset.get("reasoning_profiles", {})
    effort = arguments.get("reasoning_effort", preset.get("default_reasoning_effort", ""))
    if context not in contexts:
        raise ValueError("Unsupported context budget for this model")
    if options and effort not in options:
        raise ValueError("Unsupported reasoning profile for this model")
    if not options:
        effort = ""

    path = gateway.SELECTION_FILE
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "model": alias,
        "context_tokens": int(context),
        "reasoning_effort": effort,
    }), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return {"model": alias, "context_tokens": int(context), "reasoning_effort": effort}


TOOLS = [
    {
        "name": "list_cursor_model_profiles",
        "description": "List configured Cursor model aliases, real context budgets, and officially supported reasoning profiles. API keys are never returned.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "set_cursor_model_profile",
        "description": "Set the local Cursor Model Router profile for subsequent requests. It does not change Cursor's selected model; choose the same model alias in Cursor first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Configured model alias from list_cursor_model_profiles."},
                "context_tokens": {"type": "integer", "description": "One of the listed context budgets."},
                "reasoning_effort": {"type": "string", "description": "One of the listed profile IDs, or omit to use the model default."},
            },
            "required": ["model", "context_tokens"],
            "additionalProperties": False,
        },
    },
]


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return None
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if method == "initialize":
        result = {
            "protocolVersion": message.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cursor-model-router", "version": "0.2.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        if not isinstance(params, dict):
            params = {}
        name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            if name == "list_cursor_model_profiles":
                content = _profiles()
            elif name == "set_cursor_model_profile":
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                content = _select_profile(arguments)
            else:
                raise ValueError("Unknown tool")
            result = {"content": [{"type": "text", "text": json.dumps(content, ensure_ascii=False)}]}
        except (OSError, TypeError, ValueError) as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    else:
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                continue
            response = handle(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue


if __name__ == "__main__":
    main()
