// WOS-Bot Dashboard Frontend
const API = '';
let selectedTasks = new Set();
let eventSource = null;
let statusInterval = null;

// --- Navigation ---
document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`view-${btn.dataset.view}`).classList.add('active');

        if (btn.dataset.view === 'accounts') refreshAccounts();
        if (btn.dataset.view === 'tasks') renderTaskGrid();
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
async function pollStatus() {
    try {
        const s = await api('/api/status');
        updateStatusUI(s);
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

    // Dashboard stat card
    document.getElementById('statStatus').innerHTML = `<span class="status-dot ${dotClass}"></span> ${label}`;
    document.getElementById('statPlayer').textContent = s.current_player || '—';
    document.getElementById('statTask').textContent = s.current_task || '—';

    // Button states
    const startBtn = document.getElementById('btnStartBot');
    const stopBtn = document.getElementById('btnStopBot');
    const modalStartBtn = document.getElementById('btnConfirmStart');
    const taskStartBtn = document.getElementById('btnStartWithTasks');

    const isRunning = s.status === 'running' || s.status === 'starting';
    startBtn.disabled = isRunning;
    stopBtn.disabled = !isRunning;
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
    const html = `<div class="log-line ${cssClass}">${escapeHtml(line)}</div>`;

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
    if (l.includes('error') || l.includes('failed') || l.includes('❌')) return 'error';
    if (l.includes('✅') || l.includes('completed') || l.includes('success')) return 'success';
    if (l.includes('[dashboard]') || l.includes('running') || l.includes('navigating')) return 'info';
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
}

// --- Tasks ---
async function loadTasks() {
    const tasks = await api('/api/tasks');
    window._tasks = tasks;
    return tasks;
}

function renderTaskGrid() {
    const tasks = window._tasks || [];
    const grid = document.getElementById('taskGrid');
    const modalGrid = document.getElementById('modalTaskGrid');

    const html = tasks.map(t => `
        <div class="task-card ${selectedTasks.has(t.key) ? 'selected' : ''}" data-key="${t.key}" onclick="toggleTask('${t.key}')">
            <div class="task-check"></div>
            <div class="task-title">${t.title}</div>
            <div class="task-desc">${t.description}</div>
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
});

document.getElementById('btnDeselectAll').addEventListener('click', () => {
    selectedTasks.clear();
    renderTaskGrid();
});

// --- Bot Control ---
document.getElementById('btnStartBot').addEventListener('click', openTaskModal);

document.getElementById('btnStartWithTasks').addEventListener('click', async () => {
    if (selectedTasks.size === 0) return alert('Select at least one task');
    await startBot([...selectedTasks]);
});

document.getElementById('btnConfirmStart').addEventListener('click', async () => {
    if (selectedTasks.size === 0) return alert('Select at least one task');
    closeTaskModal();
    await startBot([...selectedTasks]);
});

document.getElementById('btnStopBot').addEventListener('click', async () => {
    if (!confirm('Stop the bot?')) return;
    try {
        await api('/api/bot/stop', { method: 'POST' });
    } catch (e) {
        alert(e.message);
    }
});

async function startBot(tasks) {
    try {
        await api('/api/bot/start', {
            method: 'POST',
            body: JSON.stringify({ tasks }),
        });
    } catch (e) {
        alert(e.message);
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

// --- Accounts ---
async function refreshAccounts() {
    try {
        const accounts = await api('/api/accounts');
        document.getElementById('statAccounts').textContent = accounts.length;
        renderAccounts(accounts);
    } catch (e) {
        console.error('Failed to load accounts:', e);
    }
}

function renderAccounts(accounts) {
    const list = document.getElementById('accountsList');
    if (!accounts.length) {
        list.innerHTML = '<div style="color:var(--text-muted);padding:20px;">No accounts configured</div>';
        return;
    }
    list.innerHTML = accounts.map(a => `
        <div class="account-card">
            <div class="account-header">
                <span class="account-email">${escapeHtml(a.email)}</span>
                <span class="account-priority">Priority ${a.priority}</span>
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
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">No completion records yet</td></tr>';
        return;
    }
    tbody.innerHTML = records.map(r => `
        <tr>
            <td style="font-weight:600;color:var(--text)">${escapeHtml(r.player_name)}</td>
            <td>${escapeHtml(r.email)}</td>
            <td>${r.last_completed}</td>
            <td>${r.hours_ago}h</td>
            <td><span class="badge ${r.in_cooldown ? 'badge-cooldown' : 'badge-ready'}">${r.in_cooldown ? 'Cooldown' : 'Ready'}</span></td>
        </tr>
    `).join('');
}

// --- Utils ---
function escapeHtml(str) {
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
