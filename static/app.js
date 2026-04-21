const state = {
  loggedIn: false,
  lastStatus: null,
  refreshTimer: null,
  refreshSeconds: 8,
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      ...(options.body && !options.form ? {'Content-Type': 'application/json'} : {}),
      ...(options.headers || {}),
    },
    ...options,
    body: options.form ? options.body : (options.body ? JSON.stringify(options.body) : undefined),
  });
  const data = await res.json().catch(() => ({ ok: false, error: 'bad_json' }));
  if (!res.ok || !data.ok) {
    throw new Error(data.message || data.error || `HTTP ${res.status}`);
  }
  return data;
}

function setMessage(el, text, ok = false) {
  if (!el) return;
  el.textContent = text || '';
  el.style.color = ok ? 'var(--success)' : 'var(--warning)';
}

function markConfigFormDirty() {
  const form = $('#configForm');
  if (form) form.dataset.dirty = '1';
}

function isConfigFormDirty() {
  const form = $('#configForm');
  return !!(form && form.dataset && form.dataset.dirty === '1');
}

function clearConfigFormDirty() {
  const form = $('#configForm');
  if (form) form.dataset.dirty = '0';
}

const INTERVAL_UNITS = {
  seconds: { seconds: 1, label: '秒', min: 10, max: 604800, step: 1 },
  minutes: { seconds: 60, label: '分钟', min: 10 / 60, max: 10080, step: 'any' },
  hours: { seconds: 3600, label: '小时', min: 10 / 3600, max: 168, step: 'any' },
};
const MAX_INTERVAL_SECONDS = 604800;

function pickIntervalUnit(seconds) {
  const safe = Number(seconds) > 0 ? Number(seconds) : 60;
  if (safe % 3600 === 0) return 'hours';
  if (safe % 60 === 0) return 'minutes';
  return 'seconds';
}

function syncIntervalEditorConstraints() {
  const form = $('#configForm');
  if (!form) return;
  const display = form.elements.namedItem('interval_display');
  const unit = form.elements.namedItem('interval_unit');
  if (!display || !unit) return;
  const meta = INTERVAL_UNITS[unit.value] || INTERVAL_UNITS.seconds;
  display.min = String(meta.min);
  display.max = String(meta.max);
  display.step = String(meta.step);
}

function formatIntervalDisplayValue(seconds, unitName) {
  const meta = INTERVAL_UNITS[unitName] || INTERVAL_UNITS.seconds;
  const value = Number(seconds) / meta.seconds;
  if (!Number.isFinite(value)) return '';
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

function updateIntervalHint() {
  const form = $('#configForm');
  const hint = $('#intervalHint');
  if (!form || !hint) return;
  const display = form.elements.namedItem('interval_display');
  const unit = form.elements.namedItem('interval_unit');
  const hidden = form.elements.namedItem('interval');
  if (!display || !unit || !hidden) return;
  const seconds = Number(hidden.value);
  const meta = INTERVAL_UNITS[unit.value] || INTERVAL_UNITS.seconds;
  if (!Number.isFinite(seconds) || seconds <= 0) {
    hint.textContent = '支持按秒、分钟或小时编辑，保存时会自动换算为秒。';
    return;
  }
  hint.textContent = `当前为 ${display.value || 0} ${meta.label}，实际保存 ${seconds} 秒。`;
}

function syncIntervalHiddenField() {
  const form = $('#configForm');
  if (!form) return 0;
  const display = form.elements.namedItem('interval_display');
  const unit = form.elements.namedItem('interval_unit');
  const hidden = form.elements.namedItem('interval');
  if (!display || !unit || !hidden) return 0;
  const displayValue = Number(display.value);
  const meta = INTERVAL_UNITS[unit.value] || INTERVAL_UNITS.seconds;
  const seconds = Number.isFinite(displayValue) ? Math.round(displayValue * meta.seconds) : 0;
  hidden.value = seconds > 0 ? String(seconds) : '';
  updateIntervalHint();
  return seconds;
}

function syncIntervalEditor(seconds) {
  const form = $('#configForm');
  if (!form) return;
  const display = form.elements.namedItem('interval_display');
  const unit = form.elements.namedItem('interval_unit');
  const hidden = form.elements.namedItem('interval');
  if (!display || !unit || !hidden) return;
  const safe = Number(seconds) > 0 ? Number(seconds) : 60;
  const pickedUnit = pickIntervalUnit(safe);
  const meta = INTERVAL_UNITS[pickedUnit];
  hidden.value = String(safe);
  unit.value = pickedUnit;
  display.value = formatIntervalDisplayValue(safe, pickedUnit);
  syncIntervalEditorConstraints();
  updateIntervalHint();
}

function handleIntervalUnitChange() {
  const form = $('#configForm');
  if (!form) return;
  const display = form.elements.namedItem('interval_display');
  const unit = form.elements.namedItem('interval_unit');
  const hidden = form.elements.namedItem('interval');
  if (!display || !unit || !hidden) return;
  const currentSeconds = Number(hidden.value) || syncIntervalHiddenField();
  syncIntervalEditorConstraints();
  display.value = formatIntervalDisplayValue(currentSeconds, unit.value);
  hidden.value = currentSeconds > 0 ? String(currentSeconds) : '';
  updateIntervalHint();
}

function syncConfigForm(cfg = {}) {
  const form = $('#configForm');
  if (!form || isConfigFormDirty()) return;

  Object.entries(cfg).forEach(([key, value]) => {
    if (key === 'interval') return;
    const el = form.elements.namedItem(key);
    if (!el) return;
    if (el.type === 'checkbox') {
      el.checked = !!value;
    } else {
      el.value = value ?? '';
    }
  });
  syncIntervalEditor(cfg.interval);
}

function servicePill(label, active, desc = '') {
  const cls = String(active || 'unknown').toLowerCase();
  return `
    <div class="status-row">
      <div>
        <strong>${label}</strong>
        <small>${desc}</small>
      </div>
      <div class="status-pill ${cls}">${active || 'unknown'}</div>
    </div>
  `;
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes)) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function buildSummaryLines(summary = {}) {
  return [
    { icon: '🛹', text: `已删除 ${summary.deleted_401 || 0} 个 401 认证失败账号` },
    { icon: '🚫', text: `已禁用 ${summary.disabled_quota || 0} 个额度耗尽账号` },
    { icon: '✨', text: `复活成功启用 ${summary.revived_enabled || 0} 个账号` },
  ];
}

function openReportModal(title, summary = {}) {
  $('#reportModalTitle').textContent = title;
  $('#reportSummaryCards').innerHTML = buildSummaryLines(summary).map(item => `
    <div class="summary-line">
      <span class="summary-icon">${item.icon}</span>
      <span>${item.text}</span>
    </div>
  `).join('');
  $('#reportModal').classList.remove('hidden');
  $('#reportModal').setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
}

function closeReportModal() {
  $('#reportModal').classList.add('hidden');
  $('#reportModal').setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
}

async function viewReport(name) {
  try {
    const data = await api(`/CLIProxyAPI-cleaner/api/report?name=${encodeURIComponent(name)}`);
    openReportModal(name, data.data?.summary || {});
  } catch (err) {
    setMessage($('#actionMsg'), `打开报告失败：${err.message}`);
  }
}

function buildReportItem(item) {
  const time = new Date(item.mtime * 1000).toLocaleString('zh-CN');
  const summary = item.summary || {};
  return `
    <button class="report-item" type="button" data-report-name="${item.name}" aria-label="查看报告 ${item.name}">
      <div class="report-item-main">
        <div class="report-name">${item.name}</div>
        <div class="report-meta">${time} · ${formatSize(item.size)}</div>
      </div>
      <div class="report-inline-summary">
        <span class="mini-pill">401 删除 ${summary.deleted_401 || 0}</span>
        <span class="mini-pill">额度禁用 ${summary.disabled_quota || 0}</span>
        <span class="mini-pill">复活 ${summary.revived_enabled || 0}</span>
      </div>
    </button>
  `;
}

function renderReports(reports = []) {
  const root = $('#reportList');
  const topFive = reports.slice(0, 5);
  $('#reportCount').textContent = String(topFive.length || 0);
  if (!topFive.length) {
    root.innerHTML = '<div class="tip">暂无报告</div>';
    return;
  }
  root.innerHTML = topFive.map(buildReportItem).join('');
  root.querySelectorAll('.report-item').forEach((btn) => {
    btn.addEventListener('click', () => viewReport(btn.dataset.reportName));
  });
}

function applyAutoRefresh(seconds) {
  const safe = Number(seconds) > 0 ? Number(seconds) : 8;
  state.refreshSeconds = safe;
  $('#refreshIntervalText').textContent = `${safe}s`;
  $('#autoRefreshText').textContent = `自动刷新中 · 每 ${safe}s`;
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => {
    if (state.loggedIn) refreshStatus(true);
  }, safe * 1000);
}

function renderStatus(data) {
  state.lastStatus = data;
  state.loggedIn = true;
  $('#loginCard').classList.add('hidden');
  $('#app').classList.remove('hidden');
  $('#logoutBtn').classList.remove('hidden');

  $('#serviceStatus').innerHTML = [
    servicePill('清理器服务', data.cleaner_service?.active, '负责账户检测、禁用、删除、复活'),
    servicePill('控制台服务', data.web_service?.active, '负责当前可视化控制面板'),
  ].join('');

  $('#cleanerActive').textContent = String(data.cleaner_service?.active || '-');
  $('#webActive').textContent = String(data.web_service?.active || '-');
  $('#commandPreview').textContent = (data.command_preview || []).join(' ');
  $('#cleanerLog').textContent = data.cleaner_log_tail || '(暂无日志)';
  $('#webLog').textContent = data.web_log_tail || '(暂无日志)';
  renderReports(data.reports || []);
  applyAutoRefresh(data.auto_refresh_seconds || 8);

  const cfg = data.config || {};
  syncConfigForm(cfg);
}

async function refreshStatus(silent = false) {
  try {
    const data = await api('/CLIProxyAPI-cleaner/api/status');
    renderStatus(data.data);
    if (!silent) setMessage($('#actionMsg'), '状态已刷新', true);
  } catch (err) {
    if (!silent) setMessage($('#actionMsg'), err.message);
    if (/登录|unauthorized/i.test(err.message)) {
      state.loggedIn = false;
      $('#loginCard').classList.remove('hidden');
      $('#app').classList.add('hidden');
      $('#logoutBtn').classList.add('hidden');
      if (state.refreshTimer) clearInterval(state.refreshTimer);
    }
  }
}

$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = new URLSearchParams();
  body.set('password', fd.get('password') || '');
  try {
    await api('/CLIProxyAPI-cleaner/api/login', { method: 'POST', body, form: true });
    setMessage($('#loginMsg'), '登录成功', true);
    e.target.reset();
    await refreshStatus(true);
    clearConfigFormDirty();
  } catch (err) {
    setMessage($('#loginMsg'), err.message);
  }
});

$('#logoutBtn').addEventListener('click', async () => {
  try { await api('/CLIProxyAPI-cleaner/api/logout', { method: 'POST', body: {} }); } catch (_) {}
  state.loggedIn = false;
  $('#loginCard').classList.remove('hidden');
  $('#app').classList.add('hidden');
  $('#logoutBtn').classList.add('hidden');
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  setMessage($('#loginMsg'), '已退出');
});

const configForm = $('#configForm');
configForm.addEventListener('input', markConfigFormDirty);
configForm.addEventListener('change', markConfigFormDirty);
configForm.elements.namedItem('interval_display')?.addEventListener('input', syncIntervalHiddenField);
configForm.elements.namedItem('interval_unit')?.addEventListener('change', handleIntervalUnitChange);
clearConfigFormDirty();
syncIntervalEditorConstraints();
syncIntervalHiddenField();
configForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const intervalSeconds = syncIntervalHiddenField();
  const payload = {
    base_url: form.base_url.value,
    management_key: form.management_key.value,
    console_password: form.console_password.value,
    interval: intervalSeconds,
    enable_api_call_check: form.enable_api_call_check.checked,
    api_call_url: form.api_call_url.value,
    api_call_method: form.api_call_method.value,
    api_call_account_id: form.api_call_account_id.value,
    api_call_user_agent: form.api_call_user_agent.value,
    api_call_body: form.api_call_body.value,
    api_call_providers: form.api_call_providers.value,
    api_call_max_per_run: Number(form.api_call_max_per_run.value),
    api_call_sleep_min: Number(form.api_call_sleep_min.value),
    api_call_sleep_max: Number(form.api_call_sleep_max.value),
    revival_wait_days: Number(form.revival_wait_days.value),
    revival_probe_interval_hours: Number(form.revival_probe_interval_hours.value),
    retention_keep_reports: Number(form.retention_keep_reports.value),
    retention_report_max_age_days: Number(form.retention_report_max_age_days.value),
    retention_backup_max_age_days: Number(form.retention_backup_max_age_days.value),
    retention_log_max_size_mb: Number(form.retention_log_max_size_mb.value),
  };
  try {
    if (!Number.isFinite(intervalSeconds) || intervalSeconds < 10 || intervalSeconds > MAX_INTERVAL_SECONDS) {
      throw new Error('轮询间隔需在 10 秒到 168 小时之间');
    }
    const data = await api('/CLIProxyAPI-cleaner/api/config/save', { method: 'POST', body: payload });
    setMessage($('#configMsg'), data.message || '配置已保存', true);
    form.management_key.value = '';
    form.console_password.value = '';
    clearConfigFormDirty();
    await refreshStatus(true);
  } catch (err) {
    setMessage($('#configMsg'), err.message);
  }
});

document.querySelectorAll('[data-action]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const action = btn.dataset.action;
    const target = btn.dataset.target;
    try {
      const data = await api(`/CLIProxyAPI-cleaner/api/service/${action}`, { method: 'POST', body: { target } });
      renderStatus(data.data);
      setMessage($('#actionMsg'), `${target} ${action} 成功`, true);
    } catch (err) {
      setMessage($('#actionMsg'), err.message);
    }
  });
});

$('#runOnceBtn').addEventListener('click', async () => {
  try {
    const data = await api('/CLIProxyAPI-cleaner/api/run-once', { method: 'POST', body: {} });
    setMessage($('#actionMsg'), data.message, true);
    $('#cleanerLog').textContent = data.output || '(无输出)';
  } catch (err) {
    setMessage($('#actionMsg'), err.message);
  }
});

$('#refreshBtn').addEventListener('click', () => refreshStatus(false));
$('#closeReportModal').addEventListener('click', closeReportModal);
$('#reportModal').addEventListener('click', (e) => {
  if (e.target.dataset.closeModal === '1') closeReportModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeReportModal();
});

refreshStatus(true);
