import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gateway
import mcp_server


class MCPServerTests(unittest.TestCase):
    def test_list_tool_only_exposes_available_profile_metadata(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "local-test-key"}):
            profiles = mcp_server._profiles()
        qwen = next(profile for profile in profiles if profile["id"] == "qwen3.8-flash")
        self.assertEqual(qwen["context_options"], [262144, 524288, 1000000])
        self.assertIn("none", [option["id"] for option in qwen["reasoning_options"]])
        self.assertNotIn("local-test-key", str(profiles))

    def test_set_tool_writes_only_a_valid_local_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            selection_file = Path(temp_dir) / "selection.json"
            with patch.object(gateway, "SELECTION_FILE", selection_file), patch.dict(
                os.environ, {"DASHSCOPE_API_KEY": "local-test-key"}
            ):
                selected = mcp_server._select_profile({
                    "model": "qwen3.8-flash",
                    "context_tokens": 524288,
                    "reasoning_effort": "none",
                })
            self.assertEqual(selected["context_tokens"], 524288)
            self.assertEqual(selection_file.stat().st_mode & 0o777, 0o600)
            with patch.dict(os.environ, {
                "DASHSCOPE_API_KEY": "local-test-key",
                "ZHIPU_API_KEY": "local-test-key",
            }):
                with self.assertRaisesRegex(ValueError, "Unsupported reasoning"):
                    mcp_server._select_profile({
                        "model": "glm-5.3",
                        "context_tokens": 524288,
                        "reasoning_effort": "none",
                    })

    def test_mcp_initialize_and_tool_call_use_json_rpc(self):
        initialized = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "cursor-model-router")
        self.assertIn(
            "io.modelcontextprotocol/ui",
            initialized["result"]["capabilities"]["extensions"],
        )
        called = mcp_server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "set_cursor_model_profile", "arguments": None},
        })
        self.assertTrue(called["result"]["isError"])

    def test_profile_picker_tool_is_linked_to_embedded_app(self):
        tools = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        picker = next(tool for tool in tools if tool["name"] == "open_cursor_model_profile_picker")
        self.assertEqual(picker["_meta"]["ui"]["resourceUri"], mcp_server.APP_RESOURCE_URI)

        resource = mcp_server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "resources/read",
            "params": {"uri": mcp_server.APP_RESOURCE_URI},
        })["result"]["contents"][0]
        self.assertEqual(resource["mimeType"], "text/html;profile=mcp-app")
        self.assertIn('lang="zh-CN"', resource["text"])
        self.assertIn("保存档位", resource["text"])

    def test_open_picker_returns_profile_data_for_agent_app(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "local-test-key"}):
            response = mcp_server.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "open_cursor_model_profile_picker", "arguments": {}},
            })
        self.assertIn("structuredContent", response["result"])
        self.assertIn("profiles", response["result"]["structuredContent"])


if __name__ == "__main__":
    unittest.main()
