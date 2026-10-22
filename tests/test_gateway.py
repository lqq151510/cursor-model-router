import json
import os
import unittest
from unittest.mock import patch

import gateway


class GatewayTests(unittest.TestCase):
    def test_deepseek_context_presets_are_selectable(self):
        for name, limit in (("256k", 262144), ("512k", 524288), ("1m", 1000000)):
            preset = gateway.MODEL_PRESETS[f"deepseek-flash-{name}-high"]
            self.assertEqual(preset["context_tokens"], limit)

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

    def test_provider_profiles_match_real_capabilities(self):
        models = gateway.MODEL_PRESETS
        self.assertEqual(models["qwen3.8-flash"]["context_tokens"], 1_000_000)
        self.assertIn("none", models["qwen3.8-flash"]["reasoning_profiles"])
        self.assertNotIn("none", models["glm-5.3"]["reasoning_profiles"])
        self.assertEqual(models["kimi-k2.6"]["context_tokens"], 262_144)
        self.assertNotIn("fast", models["kimi-k3"]["reasoning_profiles"])
        self.assertNotIn("none", models["minimax-m3.1-flash"]["reasoning_profiles"])
        for name in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"):
            self.assertIn("xhigh", models[name]["reasoning_profiles"])
            self.assertNotIn("fast", models[name]["reasoning_profiles"])

    def test_selected_profile_applies_upstream_parameters(self):
        qwen = gateway.MODEL_PRESETS["qwen3.8-flash"]
        effective = gateway._effective_preset("qwen3.8-flash", qwen)
        none = effective["reasoning_profiles"]["none"]["parameters"]
        body = {"reasoning_effort": "max", "thinking": {"type": "enabled"}}
        gateway._apply_reasoning_parameters(body, {**effective, "reasoning_parameters": none})
        self.assertEqual(body, {"reasoning_effort": "none"})

        glm = gateway.MODEL_PRESETS["glm-5.3"]["reasoning_profiles"]["max"]["parameters"]
        body = {"reasoning_effort": "low", "thinking": {"type": "disabled"}}
        gateway._apply_reasoning_parameters(body, {"reasoning_profiles": {"max": {}}, "reasoning_parameters": glm})
        self.assertEqual(body, {"reasoning_effort": "max", "thinking": {"type": "enabled"}})

    def test_anthropic_request_uses_adaptive_thinking_and_effort(self):
        request = gateway._anthropic_request({
            "messages": [{"role": "user", "content": "review this patch"}],
            "thinking": {"type": "adaptive"},
            "reasoning_effort": "xhigh",
            "max_tokens": 4096,
        }, "claude-sonnet-5-5")
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertEqual(request["output_config"], {"effort": "xhigh"})

    def test_anthropic_signed_thinking_round_trips_across_agent_tool_call(self):
        signed_thinking = {"type": "thinking", "thinking": "inspect files", "signature": "opaque-signature"}
        gateway._cache_anthropic_tool_thinking({
            "content": [signed_thinking, {"type": "tool_use", "id": "tool-use-1", "name": "read_file", "input": {}}]
        })
        request = gateway._anthropic_request({
            "messages": [
                {"role": "assistant", "content": None, "tool_calls": [{"id": "tool-use-1", "function": {"name": "read_file", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "tool-use-1", "content": "file contents"},
                {"role": "user", "content": "continue"},
            ]
        }, "claude-sonnet-5-5")
        self.assertEqual(request["messages"][0]["content"][0], signed_thinking)
        self.assertEqual(request["messages"][0]["content"][1]["type"], "tool_use")

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
