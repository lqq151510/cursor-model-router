(() => {
  if (window.__cursorModelRouterProfileUiInstalled) return;
  window.__cursorModelRouterProfileUiInstalled = true;
  const origin = 'http://127.0.0.1:18881';
  const tokenKey = 'cursor-model-router-agent-session-token';
  const css = `
    #cmr-profile-button{height:32px;min-width:32px;margin-left:6px;padding:0 9px;border:1px solid var(--vscode-button-border,transparent);border-radius:6px;background:var(--vscode-button-secondaryBackground,#333);color:var(--vscode-button-secondaryForeground,#ddd);font:12px var(--vscode-font-family, sans-serif);cursor:pointer}
    #cmr-profile-button:hover{background:var(--vscode-button-secondaryHoverBackground,#444)}
    #cmr-profile-backdrop{position:fixed;inset:0;z-index:2147483000;background:#0008;display:flex;align-items:center;justify-content:center}
    #cmr-profile-dialog{width:min(440px,calc(100vw - 32px));padding:20px;border:1px solid var(--vscode-widget-border,#555);border-radius:12px;background:var(--vscode-editorWidget-background,#252526);color:var(--vscode-foreground,#ddd);box-shadow:0 12px 40px #0008;font:13px var(--vscode-font-family,sans-serif)}
    #cmr-profile-dialog h2{font-size:16px;margin:0 0 14px} #cmr-profile-dialog label{display:block;margin:12px 0 5px;color:var(--vscode-descriptionForeground,#aaa)}
    #cmr-profile-dialog select,#cmr-profile-dialog input{box-sizing:border-box;width:100%;padding:8px;border:1px solid var(--vscode-input-border,#555);border-radius:6px;background:var(--vscode-input-background,#1e1e1e);color:var(--vscode-input-foreground,#ddd)}
    #cmr-profile-dialog .cmr-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px} #cmr-profile-dialog button{padding:7px 12px;border:0;border-radius:6px;cursor:pointer;background:var(--vscode-button-background,#0e639c);color:var(--vscode-button-foreground,#fff)}
    #cmr-profile-dialog button.secondary{background:var(--vscode-button-secondaryBackground,#444);color:var(--vscode-button-secondaryForeground,#ddd)}
    #cmr-profile-message{min-height:18px;margin-top:10px;color:var(--vscode-errorForeground,#f48771);white-space:pre-wrap} #cmr-profile-note{margin-top:12px;color:var(--vscode-descriptionForeground,#aaa);font-size:11px;line-height:1.5}
  `;
  const style = document.createElement('style'); style.textContent = css;
  (document.head || document.documentElement).appendChild(style);
  const fmt = n => n >= 1000000 ? `${Number((n / 1000000).toFixed(2))}M` : `${Math.round(n / 1024)}K`;
  const api = async (path, options = {}) => {
    const token = sessionStorage.getItem(tokenKey) || '';
    const headers = { ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${origin}${path}`, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.error?.message || `路由器返回 HTTP ${response.status}`);
    return data.data;
  };
  const el = (tag, attrs = {}, text = '') => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  };
  let modal;
  async function openPanel() {
    if (modal) modal.remove();
    modal = el('div', { id: 'cmr-profile-backdrop' });
    const box = el('section', { id: 'cmr-profile-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'cmr-profile-title' });
    box.appendChild(el('h2', { id: 'cmr-profile-title' }, '模型档位'));
    const message = el('div', { id: 'cmr-profile-message', role: 'status' });
    box.appendChild(el('label', { for: 'cmr-model' }, '模型')); const model = el('select', { id: 'cmr-model' }); box.appendChild(model);
    box.appendChild(el('label', { for: 'cmr-context' }, '上下文预算')); const context = el('select', { id: 'cmr-context' }); box.appendChild(context);
    box.appendChild(el('label', { for: 'cmr-reasoning' }, '思考模式与强度')); const reasoning = el('select', { id: 'cmr-reasoning' }); box.appendChild(reasoning);
    box.appendChild(el('label', { for: 'cmr-token' }, '本地路由器令牌（仅配置了网关鉴权时填写）'));
    const token = el('input', { id: 'cmr-token', type: 'password', autocomplete: 'off', placeholder: '不会发送到模型厂商' }); token.value = sessionStorage.getItem(tokenKey) || ''; box.appendChild(token);
    box.appendChild(el('div', { id: 'cmr-profile-note' }, '档位会保存到本机路由器，并作用于之后经路由器发送的请求。Cursor Agent 自带模型菜单仍需选择对应基础模型。'));
    const actions = el('div', { class: 'cmr-actions' }); const cancel = el('button', { class: 'secondary', type: 'button' }, '取消'); const save = el('button', { type: 'button' }, '保存档位'); actions.append(cancel, save); box.append(message, actions); modal.appendChild(box); document.body.appendChild(modal);
    cancel.onclick = () => { modal.remove(); modal = null; };
    modal.addEventListener('click', event => { if (event.target === modal) cancel.click(); });
    let profiles = [];
    const renderChoices = (preferredContext, preferredEffort) => {
      const profile = profiles.find(item => item.id === model.value) || profiles[0];
      context.replaceChildren(...(profile.context_options || [profile.default_context_tokens]).map(value => {
        const option = el('option', { value: String(value) }, `${fmt(value)}（${Number(value).toLocaleString()} tokens）`); return option;
      }));
      const ctx = (profile.context_options || []).includes(Number(preferredContext)) ? String(preferredContext) : String(profile.default_context_tokens);
      if (ctx) context.value = ctx;
      const options = profile.reasoning_options || [];
      reasoning.replaceChildren(...options.map(item => el('option', { value: item.id }, item.label + (item.description ? ` — ${item.description}` : ''))));
      if (!options.length) reasoning.appendChild(el('option', { value: '' }, '此模型未配置可调思考档位'));
      reasoning.disabled = !options.length;
      reasoning.value = options.some(item => item.id === preferredEffort) ? preferredEffort : (profile.default_reasoning_effort || '');
    };
    try {
      profiles = await api('/v1/router/profiles');
      if (!profiles.length) throw new Error('没有已配置且密钥可用的模型。先在 .env 配置 API Key，再重启路由器。');
      model.replaceChildren(...profiles.map(item => el('option', { value: item.id }, item.label)));
      const current = await api('/v1/router/selection').catch(() => ({}));
      const selected = profiles.some(item => item.id === current.model) ? current : {};
      if (selected.model) model.value = selected.model;
      renderChoices(selected.context_tokens, selected.reasoning_effort);
      model.onchange = () => renderChoices(undefined, undefined);
      context.onchange = () => {};
      save.onclick = async () => {
        message.textContent = '正在保存…'; save.disabled = true;
        try {
          const value = token.value.trim();
          if (value) sessionStorage.setItem(tokenKey, value); else sessionStorage.removeItem(tokenKey);
          const result = await api('/v1/router/selection', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: model.value, context_tokens: Number(context.value), reasoning_effort: reasoning.value }) });
          message.style.color = 'var(--vscode-testing-iconPassed,#89d185)'; message.textContent = `已保存：${profiles.find(item => item.id === result.model)?.label || result.model} / ${fmt(result.context_tokens)} / ${reasoning.options[reasoning.selectedIndex]?.textContent || '默认'}`;
          setTimeout(() => { if (modal) { modal.remove(); modal = null; } }, 1000);
        } catch (error) { message.style.color = ''; message.textContent = `${error.message}${error.message.includes('401') ? '\n请检查路由器令牌。' : ''}`; }
        finally { save.disabled = false; }
      };
    } catch (error) { message.textContent = `${error.message}\n请确认网关正在运行：http://127.0.0.1:18881/health`; save.disabled = true; }
    box.addEventListener('keydown', event => { if (event.key === 'Escape') cancel.click(); });
  }
  function addButton() {
    const anchor = [...document.querySelectorAll('button[aria-label]')].find(node => /添加智能体、上下文和工具|Add agent, context and tools/i.test(node.getAttribute('aria-label') || ''));
    if (!anchor || document.getElementById('cmr-profile-button')) return;
    const button = el('button', { id: 'cmr-profile-button', type: 'button', title: '手动选择模型、上下文和思考档位', 'aria-label': '模型档位' }, '档位');
    button.onclick = openPanel;
    anchor.insertAdjacentElement('afterend', button);
  }
  const observer = new MutationObserver(addButton);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  addButton();
})();
