/* PulseForge dashboard — zero build step and no client-side dependencies. */
'use strict';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  monitors: [], incidents: [], overview: null,
  view: 'overview', search: '', filter: 'ALL', selectedId: null, editingId: null,
  token: sessionStorage.getItem('pulseforge_token') || '',
};

const ESCAPES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ESCAPES[character]);
}
function fmtTime(dateString) {
  if (!dateString) return 'Not checked yet';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  const elapsed = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (elapsed < 60) return `${elapsed}s ago`;
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)}h ago`;
  return date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
}
function fullTime(timestamp) {
  return timestamp ? new Date(timestamp).toLocaleString() : '—';
}
function compact(value, unit = '') {
  return value == null ? '—' : `${value}${unit}`;
}
function monitorStatus(monitor) {
  return !monitor.enabled ? 'PAUSED' : monitor.state;
}
function statusBadge(status) {
  const label = {UP: '● ONLINE', DOWN: '● DOWN', PENDING: '◌ PENDING', PAUSED: 'Ⅱ PAUSED'}[status] || status;
  const type = {UP: '', DOWN: 'down', PENDING: 'pending', PAUSED: 'paused'}[status] || 'pending';
  return `<span class="status-pill ${type}">${label}</span>`;
}
async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (state.token) headers['X-API-Key'] = state.token;
  if (options.body) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(path, {...options, headers});
  } catch (_error) {
    throw new Error('Could not reach the backend. Is PulseForge running?');
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) throw new Error('API authorization required. Select the key icon in the top bar to enter your access token.');
    const detail = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).join('; ') : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return data;
}
async function downloadCsv(path, filename) {
  const headers = state.token ? {'X-API-Key': state.token} : {};
  const response = await fetch(path, {headers});
  if (!response.ok) {
    if (response.status === 401) throw new Error('API authorization required to export data.');
    throw new Error(`Export failed (${response.status}).`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function toast(message, error = false) {
  const node = document.createElement('div');
  node.className = `toast ${error ? 'error' : ''}`;
  node.textContent = message;
  $('#toastArea').append(node);
  setTimeout(() => node.remove(), 5000);
}
function showError(message) {
  const banner = $('#globalError');
  banner.textContent = message;
  banner.hidden = false;
}
function clearError() { $('#globalError').hidden = true; }

async function refresh(silent = false) {
  try {
    const [overview, monitors, incidents] = await Promise.all([
      api('/api/overview'), api('/api/monitors'), api('/api/incidents?limit=100'),
    ]);
    state.overview = overview;
    state.monitors = monitors;
    state.incidents = incidents;
    clearError();
    renderDashboard();
    if (state.selectedId !== null) await renderDrawer(state.selectedId);
    $('#lastUpdated').textContent = `SYNCED ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    showError(error.message);
    if (!silent) toast(error.message, true);
  }
}

function renderDashboard() {
  const o = state.overview;
  if (!o) return;
  $('#statTotal').textContent = o.total;
  $('#statUp').textContent = o.up;
  $('#statDown').textContent = o.down;
  $('#statUptime').textContent = compact(o.uptime_24h, '%');
  $('#statChecks').textContent = o.checks_24h.toLocaleString();
  $('#sectionMonitorCount').textContent = o.total;
  $('#sidebarMonitorCount').textContent = o.total;
  $('#sidebarIncidentCount').textContent = o.active_incidents;
  const strip = $('.health-strip');
  strip.classList.toggle('attention', o.down > 0);
  if (o.down > 0) {
    $('#healthHeadline').textContent = `${o.down} endpoint${o.down !== 1 ? 's' : ''} need${o.down === 1 ? 's' : ''} your attention`;
    $('#healthSubtitle').textContent = `${o.active_incidents} active incident${o.active_incidents === 1 ? '' : 's'} in the monitoring system.`;
    $('#healthStatus').textContent = 'DEGRADED';
  } else if (o.up > 0) {
    $('#healthHeadline').textContent = 'All confirmed endpoints operational';
    $('#healthSubtitle').textContent = `${o.up} healthy · ${o.pending} pending · ${o.paused} paused · Last 24h: ${o.checks_24h} checks.`;
    $('#healthStatus').textContent = 'OPERATIONAL';
  } else {
    $('#healthHeadline').textContent = o.total ? 'Waiting for first successful checks' : 'Your control room is ready';
    $('#healthSubtitle').textContent = o.total ? 'Monitors are configured and the engine will probe them shortly.' : 'Create a monitor to begin collecting real availability data.';
    $('#healthStatus').textContent = o.total ? 'CHECKING' : 'AWAITING DATA';
  }
  renderMonitors();
  renderIncidents();
}
function renderMonitors() {
  const filtered = state.monitors.filter((m) => {
    const status = monitorStatus(m);
    return (state.filter === 'ALL' || status === state.filter)
      && `${m.name} ${m.url}`.toLowerCase().includes(state.search.toLowerCase());
  });
  const grid = $('#monitorGrid');
  if (!filtered.length) {
    const empty = state.monitors.length === 0;
    grid.innerHTML = `<div class="empty-state"><div class="empty-symbol">⌁</div><h3>${empty ? 'No monitors yet' : 'No matching monitors'}</h3><p>${empty ? 'Build your monitoring stack. Add a live HTTP endpoint, and PulseForge will start checking it automatically.' : 'Try another filter or search to find your endpoint.'}</p>${empty ? '<button class="primary-btn" type="button" data-action="add">+ Create first monitor</button>' : ''}</div>`;
    return;
  }
  grid.innerHTML = filtered.map((m) => `
    <article class="monitor-card">
      <div class="monitor-card-top"><div class="monitor-icon">${escapeHTML(m.name.slice(0, 1).toUpperCase())}</div>${statusBadge(monitorStatus(m))}</div>
      ${m.maintenance_active ? `<div class="maintenance-note">◷ Maintenance until ${escapeHTML(fullTime(m.maintenance_until))}</div>` : ''}
      <h3 title="${escapeHTML(m.name)}">${escapeHTML(m.name)}</h3><div class="monitor-url" title="${escapeHTML(m.url)}">${escapeHTML(m.url)}</div>
      <div class="mini-stats"><div><span>24H SUCCESS</span><strong>${compact(m.uptime_24h, '%')}</strong></div><div><span>LAST LATENCY</span><strong>${compact(m.last_latency_ms)} <span class="small-unit">ms</span></strong></div></div>
      <div class="monitor-card-bottom"><span class="last-checked">◷ ${fmtTime(m.last_checked_at)}</span><button class="text-button" type="button" data-action="details" data-id="${m.id}">View details ↗</button></div>
    </article>
  `).join('');
}
function renderIncidents() {
  const target = $('#incidentList');
  if (!state.incidents.length) {
    target.innerHTML = '<div class="incident-empty"><strong>Nothing to report.</strong>No incidents have been recorded. When a monitor crosses its failure threshold, an incident will appear here.</div>';
    return;
  }
  target.innerHTML = `<table class="incident-table"><thead><tr><th>Service</th><th>Status</th><th>Started</th><th>Duration / resolved</th><th>Response</th></tr></thead><tbody>${state.incidents.map((i) => `
    <tr><td><strong>${escapeHTML(i.monitor_name)}</strong><br><span class="monitor-url">${escapeHTML(i.monitor_url)}</span></td>
      <td>${i.resolved_at ? '<span class="status-pill">● RESOLVED</span>' : '<span class="status-pill down">● ACTIVE</span>'}</td>
      <td>${escapeHTML(fullTime(i.started_at))}</td>
      <td>${i.resolved_at ? escapeHTML(fullTime(i.resolved_at)) : 'Ongoing'}</td>
      <td>${i.acknowledged_at ? `<span class="green-text">✓ Acknowledged</span>` : `<button class="text-button" data-action="ack" data-id="${i.id}" type="button">Acknowledge ↗</button>`}</td></tr>`).join('')}</tbody></table>`;
}
function setView(view) {
  const effective = view === 'monitors' ? 'overview' : view;
  state.view = view;
  $$('.nav-link[data-view]').forEach((link) => link.classList.toggle('active', link.dataset.view === view));
  $('#overviewView').hidden = effective !== 'overview';
  $('#incidentsView').hidden = effective !== 'incidents';
  $('#aboutView').hidden = effective !== 'about';
  const titles = {overview: 'System overview', monitors: 'Endpoint monitors', incidents: 'Incident response', about: 'About PulseForge'};
  const descriptions = {
    overview: 'Real-time visibility into the services that keep your business running.',
    monitors: 'Every service, every request, one unified view.',
    incidents: 'Your complete outage and recovery audit trail.',
    about: 'A hands-on project built with software reliability in mind.',
  };
  $('#pageTitle').innerHTML = `${titles[view]}<span class="title-dot">.</span>`;
  $('#pageDescription').textContent = descriptions[view];
  $('#crumbCurrent').textContent = titles[view];
  $('#addMonitorButton').hidden = view === 'about' || view === 'incidents';
}
function openAddModal(monitor = null) {
  state.editingId = monitor ? monitor.id : null;
  const form = $('#monitorForm');
  form.reset();
  if (monitor) {
    for (const key of ['name', 'url', 'method', 'expected_status', 'interval_seconds', 'timeout_seconds', 'failure_threshold']) {
      form.elements[key].value = monitor[key];
    }
    form.elements.enabled.checked = monitor.enabled;
  }
  $('#modalTitle').textContent = monitor ? 'Edit monitor' : 'Create monitor';
  $('#saveMonitorBtn').textContent = monitor ? 'Save changes' : 'Create monitor';
  $('#monitorDialog').showModal();
}
async function submitMonitor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    name: form.elements.name.value,
    url: form.elements.url.value,
    method: form.elements.method.value,
    expected_status: Number(form.elements.expected_status.value),
    interval_seconds: Number(form.elements.interval_seconds.value),
    timeout_seconds: Number(form.elements.timeout_seconds.value),
    failure_threshold: Number(form.elements.failure_threshold.value),
    enabled: form.elements.enabled.checked,
  };
  const editing = state.editingId;
  $('#saveMonitorBtn').disabled = true;
  try {
    await api(editing ? `/api/monitors/${editing}` : '/api/monitors', {
      method: editing ? 'PATCH' : 'POST', body: JSON.stringify(payload),
    });
    $('#monitorDialog').close();
    toast(editing ? 'Monitor updated.' : 'Monitor created. Automatic checks will begin shortly.');
    await refresh(true);
  } catch (error) { toast(error.message, true); }
  finally { $('#saveMonitorBtn').disabled = false; }
}
function buildChart(checks) {
  if (!checks.length) return '<div class="chart-empty">History appears here after the first check.</div>';
  const data = [...checks].reverse().filter((c) => c.latency_ms !== null);
  if (!data.length) return '<div class="chart-empty">No latency measurements recorded yet.</div>';
  const width = 400, height = 140, padding = 15;
  const maxLatency = Math.max(100, ...data.map((c) => c.latency_ms)) * 1.2;
  const x = (i) => padding + i * ((width - padding * 2) / Math.max(1, data.length - 1));
  const y = (c) => height - padding - c.latency_ms / maxLatency * (height - padding * 2);
  const points = data.map((c, i) => `${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(' ');
  const last = data[data.length - 1];
  const first = data[0];
  const pathPoints = data.length === 1 ? `${x(0) + 1},${y(last).toFixed(1)}` : points;
  const failures = data.map((c, i) => c.ok ? '' : `<circle cx="${x(i)}" cy="${y(c)}" r="4" fill="#ff848e" stroke="#15263b" stroke-width="2" />`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recent HTTP check latency graph in milliseconds">
    <line x1="15" y1="35" x2="385" y2="35" stroke="#29445b" stroke-dasharray="3 6" stroke-width="1"/>
    <line x1="15" y1="90" x2="385" y2="90" stroke="#29445b" stroke-dasharray="3 6" stroke-width="1"/>
    <polyline points="${points}${data.length === 1 ? ' ' + pathPoints : ''}" fill="none" stroke="#88eab4" stroke-width="2.8" stroke-linejoin="round" stroke-linecap="round" />
    ${failures}<circle cx="${x(data.length - 1)}" cy="${y(last)}" r="4" fill="#91f0b8"/>
    <text x="17" y="126" font-size="10" fill="#7796a8" stroke="none">${Math.round(first.latency_ms)} ms first</text>
    <text x="385" y="126" text-anchor="end" font-size="10" fill="#a0dbb9" stroke="none">${Math.round(last.latency_ms)} ms last</text>
  </svg>`;
}
async function renderDrawer(id) {
  const m = state.monitors.find((item) => item.id === id);
  if (!m) { closeDrawer(); return; }
  const [history, windows] = await Promise.all([
    api(`/api/monitors/${id}/history?limit=40`),
    api(`/api/monitors/${id}/maintenance`),
  ]);
  const content = $('#drawerContent');
  content.innerHTML = `<h2 class="drawer-name">${escapeHTML(m.name)}</h2><div class="drawer-url">${escapeHTML(m.url)}</div>
    <div style="margin-top:17px">${statusBadge(monitorStatus(m))}${m.maintenance_active ? `<span class="status-pill maintenance-pill">◷ MAINTENANCE</span>` : ''}</div>
    <div class="drawer-metrics"><div class="drawer-metric"><span>24H SUCCESS</span><strong>${compact(m.uptime_24h, '%')}</strong></div><div class="drawer-metric"><span>LATENCY</span><strong>${compact(m.last_latency_ms, ' ms')}</strong></div><div class="drawer-metric"><span>HTTP CODE</span><strong>${compact(m.last_http_status)}</strong></div></div>
    ${m.last_error ? `<div class="error-banner" style="margin-top:20px">${escapeHTML(m.last_error)}</div>` : ''}
    <div class="drawer-section"><h3>Recent latency <span style="color:#7890a7;font-weight:400">/ milliseconds</span></h3><div class="drawer-chart">${buildChart(history)}</div></div>
    <div class="drawer-section"><h3>Configuration</h3><div class="check-row">HTTP method <span class="check-time">${escapeHTML(m.method)}</span></div><div class="check-row">Expected code <span class="check-time">${m.expected_status}</span></div><div class="check-row">Check interval <span class="check-time">${m.interval_seconds}s</span></div><div class="check-row">Failure threshold <span class="check-time">${m.failure_threshold} checks</span></div></div>
    <div class="drawer-section"><h3>Maintenance windows</h3>
      <p class="drawer-hint">Checks and incidents remain visible. New outage notifications are suppressed inside the scheduled interval.</p>
      ${windows.length ? windows.map((w) => `<div class="maintenance-entry"><div><strong>${escapeHTML(fullTime(w.starts_at))} – ${escapeHTML(fullTime(w.ends_at))}</strong>${w.active ? '<span class="status-pill maintenance-pill">ACTIVE</span>' : ''}<small>${escapeHTML(w.reason || 'Planned maintenance')}</small></div><button class="text-button" type="button" data-action="cancel-maintenance" data-id="${w.id}" data-monitor="${m.id}">Remove</button></div>`).join('') : '<p class="drawer-hint">No maintenance scheduled.</p>'}
    </div>
    <div class="drawer-section"><h3>Check history</h3><div class="drawer-checks">${history.length ? history.slice(0, 10).map((h) => `<div class="check-row ${h.ok ? '' : 'failed'}"><span class="check-icon">${h.ok ? '●' : '●'}</span><span>${h.ok ? `HTTP ${h.status_code}` : escapeHTML(h.error || 'Failed')}</span><span class="check-time">${fmtTime(h.checked_at)}</span></div>`).join('') : '<p style="color:#8298b2;font-size:12px">No checks have been recorded yet.</p>'}</div></div>
    <div class="drawer-actions"><button class="primary-btn" type="button" data-action="check" data-id="${m.id}" ${m.enabled ? '' : 'disabled'}>↻ Run check now</button><button class="outline-btn" type="button" data-action="maintenance" data-id="${m.id}">Schedule maintenance</button><button class="outline-btn" type="button" data-action="export" data-id="${m.id}">Export CSV</button><button class="outline-btn" type="button" data-action="edit" data-id="${m.id}">Edit</button><button class="danger-button" type="button" data-action="delete" data-id="${m.id}">Delete</button></div>`;
}
function openDrawer(id) {
  state.selectedId = id;
  $('#detailDrawer').classList.add('open');
  $('#detailDrawer').setAttribute('aria-hidden', 'false');
  $('#drawerBackdrop').hidden = false;
  renderDrawer(id).catch((error) => toast(error.message, true));
}
function closeDrawer() {
  state.selectedId = null;
  $('#detailDrawer').classList.remove('open');
  $('#detailDrawer').setAttribute('aria-hidden', 'true');
  $('#drawerBackdrop').hidden = true;
}
function localDateTimeInput(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}
function openMaintenanceDialog(monitorId) {
  state.maintenanceMonitorId = monitorId;
  const form = $('#maintenanceForm');
  form.reset();
  const start = new Date(Date.now() + 5 * 60000);
  form.elements.starts_at.value = localDateTimeInput(start);
  form.elements.ends_at.value = localDateTimeInput(new Date(start.getTime() + 60 * 60000));
  $('#maintenanceDialog').showModal();
}
async function submitMaintenance(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const start = new Date(form.elements.starts_at.value);
  const end = new Date(form.elements.ends_at.value);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) {
    toast('Choose a valid end time after the start time.', true);
    return;
  }
  const button = $('#saveMaintenanceBtn');
  button.disabled = true;
  try {
    await api(`/api/monitors/${state.maintenanceMonitorId}/maintenance`, {
      method: 'POST',
      body: JSON.stringify({starts_at: start.toISOString(), ends_at: end.toISOString(), reason: form.elements.reason.value}),
    });
    $('#maintenanceDialog').close();
    toast('Maintenance scheduled. Checks will continue throughout the window.');
    await refresh(true);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}
async function handleAction(action, id, monitorId = null) {
  if (action === 'add') return openAddModal();
  if (action === 'maintenance') return openMaintenanceDialog(id);
  if (action === 'cancel-maintenance') {
    if (!window.confirm('Remove this maintenance window? Any active outage may trigger an alert on its next check.')) return;
    try {
      await api(`/api/monitors/${monitorId}/maintenance/${id}`, {method: 'DELETE'});
      toast('Maintenance window removed.');
      await refresh(true);
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'details') return openDrawer(id);
  if (action === 'edit') { const m = state.monitors.find((item) => item.id === id); if (m) openAddModal(m); return; }
  if (action === 'check') {
    try { const result = await api(`/api/monitors/${id}/check`, {method: 'POST'});
      toast(result.result.ok ? 'Check passed — endpoint is responding.' : `Check failed: ${result.result.error}`,
        !result.result.ok); await refresh(true);
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'export') {
    try { await downloadCsv(`/api/monitors/${id}/history.csv`, `pulseforge-monitor-${id}-history.csv`); }
    catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'ack') {
    try { await api(`/api/incidents/${id}/acknowledge`, {method: 'POST'}); toast('Incident acknowledged.'); await refresh(true); }
    catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'delete') {
    const m = state.monitors.find((item) => item.id === id);
    if (!m || !window.confirm(`Delete "${m.name}" and all of its history and incidents? This cannot be undone.`)) return;
    try { await api(`/api/monitors/${id}`, {method: 'DELETE'}); closeDrawer(); toast('Monitor and its history deleted.'); await refresh(true); }
    catch (error) { toast(error.message, true); }
  }
}

$('#addMonitorButton').addEventListener('click', () => openAddModal());
$('#refreshButton').addEventListener('click', () => refresh());
$('#incidentRefresh').addEventListener('click', () => refresh());
$('#incidentExport').addEventListener('click', async () => {
  try { await downloadCsv('/api/incidents.csv', 'pulseforge-incidents.csv'); }
  catch (error) { toast(error.message, true); }
});
$('#tokenButton').addEventListener('click', () => { $('#tokenForm').elements.token.value = state.token; $('#tokenDialog').showModal(); });
$('#monitorForm').addEventListener('submit', submitMonitor);
$('#maintenanceForm').addEventListener('submit', submitMaintenance);
$('#tokenForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  state.token = event.currentTarget.elements.token.value.trim();
  if (state.token) sessionStorage.setItem('pulseforge_token', state.token);
  else sessionStorage.removeItem('pulseforge_token');
  $('#tokenDialog').close();
  await refresh();
});
$$('[data-close-dialog]').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
$$('.nav-link[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
$('#searchInput').addEventListener('input', (event) => { state.search = event.target.value; renderMonitors(); });
$('#stateFilter').addEventListener('change', (event) => { state.filter = event.target.value; renderMonitors(); });
$('#monitorGrid').addEventListener('click', (event) => { const btn = event.target.closest('[data-action]'); if (btn) handleAction(btn.dataset.action, Number(btn.dataset.id)); });
$('#incidentList').addEventListener('click', (event) => { const btn = event.target.closest('[data-action]'); if (btn) handleAction(btn.dataset.action, Number(btn.dataset.id)); });
$('#drawerContent').addEventListener('click', (event) => { const btn = event.target.closest('[data-action]'); if (btn) handleAction(btn.dataset.action, Number(btn.dataset.id), Number(btn.dataset.monitor)); });
$('#closeDrawer').addEventListener('click', closeDrawer);
$('#drawerBackdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });
setInterval(() => refresh(true), 15000);
refresh(true);
