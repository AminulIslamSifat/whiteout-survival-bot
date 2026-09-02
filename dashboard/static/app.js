// WOS-Bot Dashboard Frontend
const API = '';
let selectedTasks = new Set();
let eventSource = null;
let statusInterval = null;

// --- Toast Notifications ---
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// --- Navigation ---
document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`view-${btn.dataset.view}`).classList.add('active');

        if (btn.dataset.view === 'accounts') refreshAccounts();
        if (btn.dataset.view === 'tasks') renderTaskGrid();
        if (btn.dataset.view === 'logs') {
            // Scroll to bottom when switching to logs
            setTimeout(() => {
                const c = document.getElementById('fullLogContainer');
                c.scrollTop = c.scrollHeight;
            }, 50);
        }
    });
});

// --- API Helpers ---
async function api(path, opts = {}) {
    const res = await fetch(`${API}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Request failed');
    }
    return res.json();
}

// --- Status Polling ---
let lastStatus = 'stopped';

async function pollStatus() {
    try {
        const s = await api('/api/status');
        updateStatusUI(s);

        // Notify on status change
        if (s.status !== lastStatus) {
            if (s.status === 'running') showToast('Bot started successfully', 'success');
            else if (s.status === 'stopped' && lastStatus === 'running') showToast('Bot stopped', 'info');
            else if (s.status === 'error') showToast('Bot encountered an error', 'error');
            lastStatus = s.status;
        }
    } catch (e) {
        console.error('Status poll failed:', e);
    }
}

function updateStatusUI(s) {
    const dotClass = s.status;
    const label = s.status.charAt(0).toUpperCase() + s.status.slice(1);

    // Sidebar mini status
    const sidebarDot = document.querySelector('#sidebarStatus .status-dot');
    sidebarDot.className = `status-dot ${dotClass}`;
    document.querySelector('#sidebarStatus .status-label').textContent = label;

    // Dashboard stat cards
    document.getElementById('statStatus').innerHTML = `<span class="status-dot ${dotClass}"></span> ${label}`;
    document.getElementById('statPlayer').textContent = s.current_player || '—';
    document.getElementById('statTask').textContent = s.current_task || '—';

    // Button states
    const isRunning = s.status === 'running' || s.status === 'starting';
    document.getElementById('btnStartBot').disabled = isRunning;
    document.getElementById('btnStopBot').disabled = !isRunning;
    const modalStartBtn = document.getElementById('btnConfirmStart');
    const taskStartBtn = document.getElementById('btnStartWithTasks');
    if (modalStartBtn) modalStartBtn.disabled = isRunning;
    if (taskStartBtn) taskStartBtn.disabled = isRunning;
}

// --- SSE Log Stream ---
function connectLogStream() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource(`${API}/api/logs/stream`);
    eventSource.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            appendLogLine(data.line);
        } catch (err) {
            console.error('SSE parse error:', err);
        }
    };
    eventSource.onerror = () => {
        setTimeout(connectLogStream, 3000);
    };
}

function appendLogLine(line) {
    const cssClass = classifyLogLine(line);
    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const html = `<div class="log-line ${cssClass}"><span style="opacity:0.4;margin-right:8px">${time}</span>${escapeHtml(line)}</div>`;

    // Dashboard log
    const dashLog = document.getElementById('dashLogLines');
    dashLog.insertAdjacentHTML('beforeend', html);
    trimLog(dashLog, 200);

    // Full log
    const fullLog = document.getElementById('fullLogLines');
    fullLog.insertAdjacentHTML('beforeend', html);
    trimLog(fullLog, 1000);

    // Auto-scroll
    if (document.getElementById('autoScrollToggle').checked) {
        const container = document.getElementById('fullLogContainer');
        container.scrollTop = container.scrollHeight;
    }
    const dashContainer = document.getElementById('dashLogContainer');
    dashContainer.scrollTop = dashContainer.scrollHeight;
}

function classifyLogLine(line) {
    const l = line.toLowerCase();
    if (l.includes('error') || l.includes('failed') || l.includes('❌') || l.includes('exception')) return 'error';
    if (l.includes('✅') || l.includes('completed') || l.includes('marked completed') || l.includes('success')) return 'success';
    if (l.includes('[dashboard]') || l.includes('starting bot') || l.includes('discovered')) return 'info';
    if (l.includes('pressed on') || l.includes('tap') || l.includes('swipe')) return 'action';
    if (l.includes('homepage') || l.includes('navigating') || l.includes('switching') || l.includes('recalibrate')) return 'nav';
    if (l.includes('running tasks for:') || l.includes('running task:')) return 'info';
    if (l.includes('skipping')) return 'nav';
    return '';
}

function trimLog(container, maxLines) {
    while (container.children.length > maxLines) {
        container.removeChild(container.firstChild);
    }
}

function clearLogView() {
    document.getElementById('dashLogLines').innerHTML = '';
    document.getElementById('fullLogLines').innerHTML = '';
    showToast('Logs cleared', 'info');
}

// --- Tasks ---
async function loadTasks() {
    try {
        const tasks = await api('/api/tasks');
        window._tasks = tasks;
        return tasks;
    } catch (e) {
        console.error('Failed to load tasks:', e);
        showToast('Failed to load tasks', 'error');
        return [];
    }
}

function renderTaskGrid() {
    const tasks = window._tasks || [];
    const grid = document.getElementById('taskGrid');
    const modalGrid = document.getElementById('modalTaskGrid');

    if (!tasks.length) {
        const empty = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No tasks discovered</div></div>';
        grid.innerHTML = empty;
        if (modalGrid) modalGrid.innerHTML = empty;
        return;
    }

    const html = tasks.map(t => `
        <div class="task-card ${selectedTasks.has(t.key) ? 'selected' : ''}" data-key="${t.key}" onclick="toggleTask('${t.key}')">
            <div class="task-title">${escapeHtml(t.title)}</div>
            <div class="task-desc">${escapeHtml(t.description)}</div>
            <div class="task-key">${escapeHtml(t.key)}</div>
        </div>
    `).join('');

    grid.innerHTML = html;
    if (modalGrid) modalGrid.innerHTML = html;
}

function toggleTask(key) {
    if (selectedTasks.has(key)) selectedTasks.delete(key);
    else selectedTasks.add(key);
    renderTaskGrid();
}

document.getElementById('btnSelectAll').addEventListener('click', () => {
    (window._tasks || []).forEach(t => selectedTasks.add(t.key));
    renderTaskGrid();
    showToast(`Selected all ${selectedTasks.size} tasks`, 'info');
});

document.getElementById('btnDeselectAll').addEventListener('click', () => {
    selectedTasks.clear();
    renderTaskGrid();
    showToast('Cleared selection', 'info');
});

// --- Bot Control ---
document.getElementById('btnStartBot').addEventListener('click', openTaskModal);

document.getElementById('btnStartWithTasks').addEventListener('click', async () => {
    if (selectedTasks.size === 0) {
        showToast('Select at least one task first', 'error');
        return;
    }
    await startBot([...selectedTasks]);
});

document.getElementById('btnConfirmStart').addEventListener('click', async () => {
    if (selectedTasks.size === 0) {
        showToast('Select at least one task', 'error');
        return;
    }
    closeTaskModal();
    await startBot([...selectedTasks]);
});

document.getElementById('btnStopBot').addEventListener('click', async () => {
    try {
        await api('/api/bot/stop', { method: 'POST' });
        showToast('Stopping bot...', 'info');
    } catch (e) {
        showToast(e.message, 'error');
    }
});

async function startBot(tasks) {
    try {
        await api('/api/bot/start', {
            method: 'POST',
            body: JSON.stringify({ tasks }),
        });
        showToast(`Bot started with ${tasks.length} tasks`, 'success');
        // Switch to dashboard to see live status
        document.querySelector('[data-view="dashboard"]').click();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// --- Modal ---
function openTaskModal() {
    renderTaskGrid();
    document.getElementById('taskModal').classList.add('open');
}

function closeTaskModal() {
    document.getElementById('taskModal').classList.remove('open');
}

// Close modal on overlay click
document.getElementById('taskModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeTaskModal();
});

// Close modal on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeTaskModal();
});

// --- Accounts ---
async function refreshAccounts() {
    try {
        const accounts = await api('/api/accounts');
        document.getElementById('statAccounts').textContent = accounts.length;
        renderAccounts(accounts);
    } catch (e) {
        console.error('Failed to load accounts:', e);
        showToast('Failed to load accounts', 'error');
    }
}

function renderAccounts(accounts) {
    const list = document.getElementById('accountsList');
    if (!accounts.length) {
        list.innerHTML = '<div class="empty-state"><div class="empty-icon">👤</div><div class="empty-text">No accounts configured</div></div>';
        return;
    }
    list.innerHTML = accounts.map(a => `
        <div class="account-card">
            <div class="account-header">
                <span class="account-email">${escapeHtml(a.email)}</span>
                <span class="account-priority">#${a.priority}</span>
            </div>
            <div class="player-list">
                ${a.players.map(p => `
                    <div class="player-chip">
                        <span class="player-name">${escapeHtml(p.name)}</span>
                        <span class="player-id">#${p.id}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

// --- Completion ---
async function refreshCompletion() {
    try {
        const records = await api('/api/completion');
        renderCompletion(records);
    } catch (e) {
        console.error('Failed to load completion:', e);
    }
}

function renderCompletion(records) {
    const tbody = document.querySelector('#completionTable tbody');
    if (!records.length) {
        tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state" style="padding:24px"><div class="empty-icon">📊</div><div class="empty-text">No completion records yet</div></div></td></tr>';
        return;
    }
    tbody.innerHTML = records.map(r => `
        <tr>
            <td style="font-weight:700;color:var(--text)">${escapeHtml(r.player_name)}</td>
            <td>${escapeHtml(r.email)}</td>
            <td style="font-family:var(--mono);font-size:12px">${r.last_completed}</td>
            <td style="font-family:var(--mono);font-size:12px">${formatDuration(r.hours_ago)}</td>
            <td><span class="badge ${r.in_cooldown ? 'badge-cooldown' : 'badge-ready'}">${r.in_cooldown ? '⏳ Cooldown' : '✓ Ready'}</span></td>
        </tr>
    `).join('');
}

function formatDuration(hours) {
    if (hours < 1) return `${Math.round(hours * 60)}m ago`;
    if (hours < 24) return `${Math.round(hours)}h ago`;
    return `${Math.round(hours / 24)}d ago`;
}

// --- Utils ---
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// --- Init ---
async function init() {
    await loadTasks();
    await pollStatus();
    await refreshAccounts();
    await refreshCompletion();
    connectLogStream();
    statusInterval = setInterval(pollStatus, 3000);
}

init();
