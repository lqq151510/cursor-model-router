const vscode = require('vscode');

const TOKEN_KEY = 'cursorModelRouter.localControlToken';
let readToken = async () => undefined;

function baseUrl() {
  const value = vscode.workspace.getConfiguration('cursorModelRouter').get('baseUrl');
  const url = new URL(value);
  if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname)) {
    throw new Error('baseUrl 必须指向本机回环地址，避免把本地令牌发送到远程主机。');
  }
  return url.toString().replace(/\/$/, '');
}

async function request(path, options = {}) {
  const token = await readToken();
  const headers = { 'content-type': 'application/json', ...(options.headers || {}) };
  if (token) headers.authorization = `Bearer ${token}`;
  const response = await fetch(`${baseUrl()}${path}`, { ...options, headers });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `Router returned HTTP ${response.status}`);
  return data;
}

async function getProfiles() {
  const result = await request('/v1/router/profiles');
  return result.data || [];
}

function contextLabel(value) {
  if (value >= 1000000) return `${Number((value / 1000000).toFixed(2))}M`;
  return `${Math.round(value / 1024)}K`;
}

function reasoningLabel(profile, id) {
  const option = (profile.reasoning_options || []).find(item =>
    (typeof item === 'string' ? item : item.id) === id
  );
  return option ? (typeof option === 'string' ? option : option.label) : (id || '默认');
}

async function refreshStatus(status) {
  try {
    const [profiles, current] = await Promise.all([
      getProfiles(), request('/v1/router/selection'),
    ]);
    const selection = current.data || {};
    const profile = profiles.find(p => p.id === selection.model);
    if (!profile) return;
    const effort = reasoningLabel(profile, selection.reasoning_effort || profile.default_reasoning_effort);
    status.text = `$(tune) ${profile.label} · ${contextLabel(selection.context_tokens)} · ${effort}`;
    status.tooltip = '点击选择模型、真实上下文预算和上游思考档位';
  } catch (_) {
    // The gateway may not be running yet; keep the generic status-bar label.
  }
}

async function editProfile(status) {
  try {
    const profiles = await getProfiles();
    if (!profiles.length) {
      await vscode.window.showWarningMessage('路由器没有已配置可用的模型。请先在 .env 填写对应 API Key。');
      return;
    }
    const model = await vscode.window.showQuickPick(profiles.map(p => ({
      label: p.label,
      description: p.id,
      profile: p,
    })), { title: '选择模型', placeHolder: '只显示已配置 API Key 的模型' });
    if (!model) return;

    const contexts = model.profile.context_options || [model.profile.default_context_tokens];
    const context = await vscode.window.showQuickPick(contexts.map(value => ({
      label: contextLabel(value),
      description: `${value.toLocaleString()} tokens`,
      value,
    })), { title: '选择上下文档位' });
    if (!context) return;

    const efforts = model.profile.reasoning_options || [];
    let effort = model.profile.default_reasoning_effort || '';
    if (efforts.length) {
      const selected = await vscode.window.showQuickPick(efforts.map(value => ({
        label: typeof value === 'string' ? value : value.label,
        description: typeof value === 'string' ? '' : value.description,
        value: typeof value === 'string' ? value : value.id,
      })), { title: '选择思考强度' });
      if (!selected) return;
      effort = selected.value;
    }

    await request('/v1/router/selection', {
      method: 'POST',
      body: JSON.stringify({ model: model.profile.id, context_tokens: context.value, reasoning_effort: effort }),
    });
    const effortText = selectedProfileLabel(model.profile, effort);
    status.text = `$(tune) ${model.profile.label} · ${context.label} · ${effortText || '默认'}`;
    status.tooltip = '点击选择模型、真实上下文预算和上游思考档位';
    await vscode.window.showInformationMessage(
      `已设置 ${model.profile.label}：${context.label} / ${effortText || '模型默认档位'}。请在 Cursor 模型下拉框选择对应模型。`
    );
  } catch (error) {
    await vscode.window.showErrorMessage(`Cursor Model Router: ${error.message}`);
  }
}

function selectedProfileLabel(profile, id) {
  const option = (profile.reasoning_options || []).find(item =>
    (typeof item === 'string' ? item : item.id) === id
  );
  return option ? (typeof option === 'string' ? option : option.label) : id;
}

function activate(context) {
  readToken = () => context.secrets.get(TOKEN_KEY);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = 'cursorModelRouter.editProfile';
  status.text = '$(tune) 模型档位';
  status.tooltip = '选择模型、真实上下文预算和上游思考档位';
  status.show();
  refreshStatus(status);
  const refreshTimer = setInterval(() => refreshStatus(status), 3000);
  context.subscriptions.push({ dispose: () => clearInterval(refreshTimer) });
  context.subscriptions.push(status);

  context.subscriptions.push(vscode.commands.registerCommand(
    'cursorModelRouter.editProfile', () => editProfile(status)
  ));
  context.subscriptions.push(vscode.commands.registerCommand('cursorModelRouter.setToken', async () => {
    const value = await vscode.window.showInputBox({
      prompt: '输入本地路由器令牌（留空可清除）',
      password: true,
      ignoreFocusOut: true,
    });
    if (value === undefined) return;
    if (value) await context.secrets.store(TOKEN_KEY, value);
    else await context.secrets.delete(TOKEN_KEY);
    await vscode.window.showInformationMessage('本地路由器令牌已更新。');
  }));
}

function deactivate() {}

module.exports = { activate, deactivate };
