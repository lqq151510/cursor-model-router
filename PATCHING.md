# Cursor Agent UI Patch Maintenance / Cursor Agent 界面补丁维护

## 中文

### 能做什么

补丁在 Cursor Agent 输入框旁增加“档位”按钮。点击后，直接从本机路由器加载已经配置且密钥可用的模型，并显示该模型实际配置的上下文档位与思考选项。保存后只影响之后经过本路由器的请求；Agent 自己的模型菜单仍需选择同一个基础模型。补丁不会打开浏览器，也不需要向 Agent 发自然语言指令。

### 警告

- 这是对 Cursor 已打包前端代码的本机修改，不是 Cursor 官方扩展接口。汉化包和本补丁都依赖 Cursor 内部实现，升级后可能失效。
- 修改会使 `Cursor.app` 的代码签名校验失效。macOS 安全机制或 Cursor 自检可能阻止启动/更新，或提示应用已损坏。安装前请确保可以重新下载官方 Cursor 安装包。
- 脚本会把原始主界面文件复制到 `~/Library/Application Support/CursorModelRouter/patch-backups/`，按 Cursor 版本和 SHA-256 命名；卸载前不要删除该目录。
- Agent 面板只向 `127.0.0.1:18881` 发送请求。若启用了 `gateway_token_env`，需要在面板输入路由器令牌；它仅保存在当前窗口 `sessionStorage`，不会写进项目或发送到模型厂商。
- `/v1/router/profiles` 仅展示本机已配置且密钥可用的模型。档位标签来自模型配置；这不能证明厂商服务当前可用，真实限制以 API 响应为准。
- 不要把修改后的 Cursor.app、修改后的大体积 bundle、令牌或个人配置提交到 GitHub。

### 安装

1. 完全退出 Cursor，先保存其他窗口中的工作。
2. 在仓库根目录运行：

   ```sh
   python3 scripts/patch_cursor_agent_ui.py status
   python3 scripts/patch_cursor_agent_ui.py install
   ```

3. 重新打开 Cursor；在 Agent 输入框旁点击“档位”。
4. 若面板无法读取路由器，检查服务状态：`http://127.0.0.1:18881/health`。该地址只用于本机诊断，不要把它配置为公网服务地址。

### 每次 Cursor 更新后

1. 先运行 `python3 scripts/patch_cursor_agent_ui.py status`。
2. 若 Cursor 更新覆盖了补丁，运行脚本的 `install`。脚本会对新版本文件单独备份。
3. 若脚本提示“界面锚点与补丁不匹配”，停止操作。打开新版本的 `workbench.glass.main.js`，定位 Agent 输入框按钮组件，更新 `scripts/patch_cursor_agent_ui.py` 中的唯一锚点，并检查 `scripts/cursor-agent-profile-ui.js` 的按钮定位规则。不要用全局替换或忽略 SHA-256 校验。
4. 在临时副本上验证新锚点只匹配一次，再验证补丁和还原都能成功；更新 README 中确认过的版本说明。若 Cursor 的 DOM 或请求策略变化，同时检查按钮是否出现、弹窗、鉴权、CORS 与保存结果。
5. 新版本适配完成后才把补丁脚本和维护文档提交到项目。Cursor.app 本身永远不进入仓库。

### 卸载和恢复

完全退出 Cursor 后运行：

```sh
python3 scripts/patch_cursor_agent_ui.py uninstall
```

脚本会校验当前补丁文件和备份 SHA-256 后恢复对应版本。校验不匹配时会拒绝覆盖，以免误删 Cursor 更新或其他人的改动。若 Cursor 更新已经覆盖补丁，脚本会提示无需从旧版本恢复。恢复后重新打开 Cursor。

---

## English

### What it does

The patch adds a **Profiles** button beside the Cursor Agent composer. It reads configured, credential-ready models and their actual context and reasoning options from the local router. Saving affects subsequent requests routed through this project. Cursor's own model menu still selects the matching base model. The patch opens an in-window dialog; it does not open a browser or require a natural-language prompt.

### Warnings

- This modifies Cursor's bundled frontend locally. It is not a supported Cursor extension API and may break after any Cursor update.
- Editing the bundle invalidates the app's code signature. macOS security checks or Cursor self-checks may block launch or updates, or report that the app is damaged. Make sure you can reinstall Cursor from its official installer before applying the patch.
- The original bundle is backed up under `~/Library/Application Support/CursorModelRouter/patch-backups/`, keyed by Cursor version and SHA-256. Keep this directory until uninstallation is complete.
- The Agent dialog talks only to `127.0.0.1:18881`. If gateway authentication is enabled, enter the router token in the dialog. It is held in the current window's `sessionStorage`, not written to the repository or sent to model vendors.
- Profiles are based on local configuration and available credentials. Labels do not prove current upstream availability; the provider's API response remains authoritative.
- Never commit or distribute the modified Cursor app, its large bundle, tokens, or personal configuration.

### Install

Quit Cursor completely and save work in other windows. From the repository root:

```sh
python3 scripts/patch_cursor_agent_ui.py status
python3 scripts/patch_cursor_agent_ui.py install
```

Relaunch Cursor and click **档位** beside the Agent composer. If the dialog cannot reach the router, check `http://127.0.0.1:18881/health` locally.

### After each Cursor update

Run `status` first. If the update removed the patch, run `install` to back up and patch the new bundle. If the script reports that the UI anchor does not match, stop. Locate the new Agent composer component, update the unique anchor and button locator, then test install and restore against a disposable copy. Recheck button rendering, dialog behavior, authentication, CORS, and persistence. Never use broad replacement or bypass SHA-256 checks. Update this project only after compatibility is verified; never add `Cursor.app` to the repository.

### Uninstall and recovery

Quit Cursor and run:

```sh
python3 scripts/patch_cursor_agent_ui.py uninstall
```

The script restores only when both the patched bundle and backup hashes match. If validation fails, it refuses to overwrite the file. Relaunch Cursor after restoration.
