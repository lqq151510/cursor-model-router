#!/usr/bin/env python3
"""Version-checked, reversible local UI patch for Cursor Agent model profiles."""
from __future__ import annotations
import argparse, hashlib, json, os, plistlib, shutil, sys
from pathlib import Path

ANCHOR = 'var WZr=O({"getSubmitDataFromEditor.js"'
MARKER = '/* CURSOR_MODEL_ROUTER_AGENT_PROFILE_UI_V1 */'
DEFAULT_APP = Path('/Applications/Cursor.app')
STATE_DIR = Path.home() / 'Library/Application Support/CursorModelRouter/patch-backups'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def bundle_for(app: Path) -> Path:
    p = app / 'Contents/Resources/app/out/vs/workbench/workbench.glass.main.js'
    if not p.is_file(): raise SystemExit(f'找不到 Cursor 主界面文件：{p}\nCursor 版本可能改变了文件布局；补丁已停止。')
    return p


def version_for(app: Path) -> str:
    p = app / 'Contents/Info.plist'
    try:
        with p.open('rb') as f: return plistlib.load(f).get('CFBundleShortVersionString', 'unknown')
    except Exception: return 'unknown'


def main() -> None:
    parser = argparse.ArgumentParser(description='为 Cursor Agent 窗口增加本机模型档位按钮。')
    parser.add_argument('action', choices=['install', 'uninstall', 'status'])
    parser.add_argument('--app', type=Path, default=DEFAULT_APP, help='Cursor.app 路径')
    args = parser.parse_args()
    app = args.app.expanduser().resolve(); bundle = bundle_for(app); current_hash = sha(bundle)
    version = version_for(app); manifest = STATE_DIR / f'{version}-{current_hash[:12]}.json'
    text = bundle.read_text(encoding='utf-8')
    if args.action == 'status':
        print(f'Cursor 版本：{version}\n主界面 SHA-256：{current_hash}\n补丁状态：{"已安装" if MARKER in text else "未安装"}')
        return
    if args.action == 'install':
        if MARKER in text:
            print('补丁已存在，无需重复安装。'); return
        if text.count(ANCHOR) != 1:
            raise SystemExit(f'当前 Cursor {version} 的界面锚点与补丁不匹配（找到 {text.count(ANCHOR)} 个）。\n请先检查 Cursor 更新，并按 PATCHING.zh-CN.md 更新补丁；未修改应用文件。')
        ui_path = Path(__file__).with_name('cursor-agent-profile-ui.js')
        ui = ui_path.read_text(encoding='utf-8').strip()
        if not ui.startswith('(() =>') or not ui.endswith('})();'):
            raise SystemExit('界面脚本完整性校验失败，未修改应用文件。')
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        backup = STATE_DIR / f'{version}-{current_hash[:12]}.js'
        if not backup.exists(): shutil.copy2(bundle, backup)
        elif sha(backup) != current_hash: raise SystemExit(f'备份文件校验不匹配：{backup}')
        patched = text.replace(ANCHOR, f'{MARKER}\n;{ui}\n{ANCHOR}', 1)
        temporary = bundle.with_suffix('.js.cmr-tmp')
        temporary.write_text(patched, encoding='utf-8'); shutil.copystat(bundle, temporary); os.replace(temporary, bundle)
        patched_hash = sha(bundle)
        manifest.write_text(json.dumps({'app': str(app), 'bundle': str(bundle), 'version': version, 'original_sha256': current_hash, 'patched_sha256': patched_hash, 'backup': str(backup)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'已为 Cursor {version} 安装 Agent 模型档位按钮。')
        print(f'原版备份：{backup}')
        print('请完全退出并重新打开 Cursor。此补丁修改了已签名应用包，macOS 代码签名校验可能失败；如 Cursor 无法启动，执行 uninstall 恢复。')
        print('Cursor 更新会覆盖补丁；每次更新后先运行 status，再阅读 PATCHING.zh-CN.md。')
        return
    candidates = sorted(STATE_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True) if STATE_DIR.exists() else []
    for item in candidates:
        try: data = json.loads(item.read_text(encoding='utf-8'))
        except Exception: continue
        if Path(data.get('bundle', '')) != bundle: continue
        if current_hash != data.get('patched_sha256'):
            if MARKER not in text:
                print('当前应用已被 Cursor 更新覆盖，本来就没有补丁，不恢复旧版文件。'); return
            raise SystemExit('补丁后的文件校验值已变化；为保护 Cursor 更新或其他改动，拒绝覆盖。请人工检查。')
        backup = Path(data['backup'])
        if sha(backup) != data.get('original_sha256'): raise SystemExit(f'原版备份校验失败：{backup}')
        shutil.copy2(backup, bundle)
        print(f'已恢复 Cursor {data.get("version")} 的原版界面文件。请重新打开 Cursor。')
        return
    if MARKER not in text:
        print('未发现模型档位补丁。'); return
    raise SystemExit('发现补丁，但找不到匹配的备份记录。拒绝盲目替换，请检查维护文档。')

if __name__ == '__main__': main()
