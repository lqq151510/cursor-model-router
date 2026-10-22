import json
import os
import unittest
from unittest.mock import patch

import gateway


class GatewayTests(unittest.TestCase):
    def test_deepseek_context_presets_are_selectable(self):
        for name, limit in (("256k", 262144), ("512k", 524288), ("1m", 1048576)):
            preset = gateway.MODEL_PRESETS[f"deepseek-flash-{name}-high"]
            self.assertEqual(preset["context_tokens"], limit)
            self.assertEqual(preset["reasoning_effort"], "high")

    def test_context_trimming_removes_old_complete_turn(self):
        body = {"messages": [
            {"role": "system", "content": "keep"},
            {"role": "user", "content": "old question " + "a" * 600},
            {"role": "assistant", "content": "old answer " + "b" * 600},
            {"role": "user", "content": "latest"},
        ]}
        gateway._fit_context(body, context_limit=128, output_reserve=8)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(body["messages"][-1]["content"], "latest")

    def test_anthropic_request_converts_tools_and_system(self):
        request = gateway._anthropic_request({
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {"name": "lookup", "arguments": json.dumps({"q": "x"})}}]},
            ],
            "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
            "max_tokens": 64,
            "stream": True,
        }, "claude-test")
        self.assertEqual(request["system"], "rules")
        self.assertEqual(request["tools"][0]["name"], "lookup")
        self.assertEqual(request["messages"][-1]["content"][0]["type"], "tool_use")

    def test_gateway_bearer_auth_is_constant_time_checked(self):
        handler = object.__new__(gateway.GatewayHandler)
        with patch.object(gateway, "GATEWAY_TOKEN_ENV", "CURSOR_ROUTER_TOKEN"), patch.dict(os.environ, {"CURSOR_ROUTER_TOKEN": "secret-token"}):
            handler.headers = {"Authorization": "Bearer secret-token"}
            self.assertTrue(handler._authorized())
            handler.headers = {"Authorization": "Bearer wrong-token"}
            self.assertFalse(handler._authorized())
            handler.headers = {}
            self.assertFalse(handler._authorized())

    def test_anthropic_response_converts_text_and_tools(self):
        converted = gateway._anthropic_to_openai_response({
            "id": "msg-1", "stop_reason": "tool_use",
            "content": [{"type": "text", "text": "go"}, {"type": "tool_use", "id": "t1", "name": "f", "input": {"x": 1}}],
            "usage": {"input_tokens": 4, "output_tokens": 5},
        }, "alias")
        choice = converted["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(choice["message"]["tool_calls"][0]["function"]["name"], "f")
        self.assertEqual(converted["usage"]["total_tokens"], 9)


if __name__ == "__main__":
    unittest.main()
