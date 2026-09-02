// WOS-Bot Dashboard Frontend
const API = '';
let selectedTasks = new Set();
let selectedAccountEmails = new Set();  // accounts selected for bot run
let selectedCharacters = {};  // email -> Set of player_ids selected for bot run
let eventSource = null;
let ocrEventSource = null;
let statusInterval = null;
let _accountsCache = [];  // cached for modal selector

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

    // OCR status
    const ocrStatus = s.ocr_status || 'stopped';
    const ocrLabel = ocrStatus.charAt(0).toUpperCase() + ocrStatus.slice(1);
    const ocrEl = document.getElementById('statOcr');
    if (ocrEl) {
        ocrEl.innerHTML = `<span class="status-dot ${ocrStatus}"></span> ${ocrLabel}
            <button class="btn-xs btn-primary" id="btnStartOcr" style="margin-left:8px" onclick="startOcr()" ${ocrStatus !== 'stopped' ? 'disabled' : ''}>Start</button>
            <button class="btn-xs btn-danger" id="btnStopOcr" style="margin-left:4px" onclick="stopOcr()" ${ocrStatus !== 'running' ? 'disabled' : ''}>Stop</button>`;
    }

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
        const payload = { tasks };
        const allEmails = _accountsCache.map(a => a.email);
        const isAllAccounts = allEmails.length > 0 && allEmails.every(e => selectedAccountEmails.has(e));

        // Check if all characters are selected across all accounts
        let isAllChars = true;
        for (const a of _accountsCache) {
            const charSet = selectedCharacters[a.email];
            if (!charSet || charSet.size !== a.players.length) {
                isAllChars = false;
                break;
            }
        }

        // Send account filter if not all accounts selected
        if (!isAllAccounts && selectedAccountEmails.size > 0) {
            payload.accounts = [...selectedAccountEmails];
        }

        // Build characters dict only if some characters are deselected
        if (!isAllChars && selectedAccountEmails.size > 0) {
            const charsDict = {};
            for (const email of selectedAccountEmails) {
                const charSet = selectedCharacters[email];
                if (charSet && charSet.size > 0) {
                    charsDict[email] = [...charSet];
                }
            }
            if (Object.keys(charsDict).length > 0) {
                payload.characters = charsDict;
            }
        }

        await api('/api/bot/start', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        const accMsg = payload.accounts ? ` (${payload.accounts.length} accounts)` : ' (all accounts)';
        const charMsg = payload.characters ? ' + character filter' : '';
        showToast(`Bot started with ${tasks.length} tasks${accMsg}${charMsg}`, 'success');
        document.querySelector('[data-view="dashboard"]').click();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// --- Account/Character Selector (Modal) ---
function renderAccountSelector() {
    const container = document.getElementById('accountSelector');
    if (!_accountsCache.length) {
        container.innerHTML = '<div class="empty-state" style="padding:12px"><div class="empty-text">No accounts configured</div></div>';
        return;
    }

    container.innerHTML = _accountsCache.map(a => {
        const emailChecked = selectedAccountEmails.has(a.email);
        const charSet = selectedCharacters[a.email] || new Set();

        const playerHtml = a.players.map(p => {
            const pChecked = charSet.has(String(p.id));
            return `
                <label class="char-checkbox ${pChecked ? 'checked' : ''}" data-email="${escapeHtml(a.email)}" data-id="${p.id}">
                    <input type="checkbox" ${pChecked ? 'checked' : ''} onchange="toggleCharacter('${escapeHtml(a.email)}', '${p.id}', this.checked)">
                    <span class="player-name">${escapeHtml(p.name)}</span>
                    <span class="player-id">#${p.id}</span>
                </label>
            `;
        }).join('');

        return `
            <div class="account-select-item ${emailChecked ? 'selected' : ''}">
                <label class="account-checkbox">
                    <input type="checkbox" ${emailChecked ? 'checked' : ''} onchange="toggleAccount('${escapeHtml(a.email)}', this.checked)">
                    <span class="account-email">${escapeHtml(a.email)}</span>
                    <span class="account-priority">#${a.priority}</span>
                </label>
                <div class="char-list">${playerHtml}</div>
            </div>
        `;
    }).join('');
}

function toggleAccount(email, checked) {
    if (checked) {
        selectedAccountEmails.add(email);
        // Select all characters for this account
        const acc = _accountsCache.find(a => a.email === email);
        if (acc) {
            selectedCharacters[email] = new Set(acc.players.map(p => String(p.id)));
        }
    } else {
        selectedAccountEmails.delete(email);
        delete selectedCharacters[email];
    }
    renderAccountSelector();
    updateSelectAllAccountsCheckbox();
}

function toggleCharacter(email, playerId, checked) {
    if (!selectedCharacters[email]) selectedCharacters[email] = new Set();
    if (checked) {
        selectedCharacters[email].add(String(playerId));
        selectedAccountEmails.add(email);
    } else {
        selectedCharacters[email].delete(String(playerId));
        // If no chars left for this account, deselect the account too
        if (selectedCharacters[email].size === 0) {
            selectedAccountEmails.delete(email);
            delete selectedCharacters[email];
        }
    }
    renderAccountSelector();
    updateSelectAllAccountsCheckbox();
}

function toggleAllAccounts() {
    const allChecked = document.getElementById('selectAllAccounts').checked;
    selectedAccountEmails.clear();
    selectedCharacters = {};

    if (allChecked) {
        _accountsCache.forEach(a => {
            selectedAccountEmails.add(a.email);
            selectedCharacters[a.email] = new Set(a.players.map(p => String(p.id)));
        });
    }
    renderAccountSelector();
}

function updateSelectAllAccountsCheckbox() {
    const allEmails = _accountsCache.map(a => a.email);
    const allSelected = allEmails.length > 0 && allEmails.every(e => selectedAccountEmails.has(e));
    document.getElementById('selectAllAccounts').checked = allSelected;
}

// --- Modal ---
async function openTaskModal() {
    renderTaskGrid();
    // Refresh accounts cache and initialize selector state
    try {
        _accountsCache = await api('/api/accounts');
    } catch (e) {
        _accountsCache = [];
    }
    // Default: select all accounts + all characters
    selectedAccountEmails.clear();
    selectedCharacters = {};
    _accountsCache.forEach(a => {
        selectedAccountEmails.add(a.email);
        selectedCharacters[a.email] = new Set(a.players.map(p => String(p.id)));
    });
    renderAccountSelector();
    updateSelectAllAccountsCheckbox();
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

let _editingAccountEmail = null;  // tracks which account is being edited

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
                <button class="btn-xs btn-secondary" onclick="openAccountEditModal('${escapeHtml(a.email)}')">✏️ Edit</button>
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

// --- Account Edit Modal ---
function openNewAccountModal() {
    _editingAccountEmail = null;
    document.getElementById('accountEditTitle').textContent = 'Add New Account';
    document.getElementById('editEmail').value = '';
    document.getElementById('editEmail').disabled = false;
    document.getElementById('editPriority').value = '999';
    document.getElementById('editPlayerList').innerHTML = '';
    document.getElementById('btnDeleteAccount').style.display = 'none';
    document.getElementById('accountEditModal').classList.add('open');
}

async function openAccountEditModal(email) {
    try {
        const accounts = await api('/api/accounts');
        const acc = accounts.find(a => a.email === email);
        if (!acc) { showToast('Account not found', 'error'); return; }

        _editingAccountEmail = email;
        document.getElementById('accountEditTitle').textContent = 'Edit Account';
        document.getElementById('editEmail').value = email;
        document.getElementById('editEmail').disabled = true;  // can't rename email
        document.getElementById('editPriority').value = acc.priority;
        document.getElementById('btnDeleteAccount').style.display = '';

        const playerListEl = document.getElementById('editPlayerList');
        playerListEl.innerHTML = acc.players.map((p, i) => `
            <div class="player-edit-row" data-index="${i}">
                <input type="text" class="form-input player-edit-name" value="${escapeHtml(p.name)}" placeholder="Character name">
                <input type="text" class="form-input player-edit-id" value="${escapeHtml(String(p.id))}" placeholder="Player ID">
                <button class="btn-xs btn-danger" onclick="this.parentElement.remove()">✕</button>
            </div>
        `).join('');

        document.getElementById('accountEditModal').classList.add('open');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function closeAccountEditModal() {
    document.getElementById('accountEditModal').classList.remove('open');
    _editingAccountEmail = null;
}

function addPlayerField() {
    const list = document.getElementById('editPlayerList');
    const row = document.createElement('div');
    row.className = 'player-edit-row';
    row.innerHTML = `
        <input type="text" class="form-input player-edit-name" placeholder="Character name">
        <input type="text" class="form-input player-edit-id" placeholder="Player ID">
        <button class="btn-xs btn-danger" onclick="this.parentElement.remove()">✕</button>
    `;
    list.appendChild(row);
}

async function saveAccountEdit() {
    const email = document.getElementById('editEmail').value.trim();
    const priority = parseInt(document.getElementById('editPriority').value) || 999;
    const rows = document.querySelectorAll('.player-edit-row');
    const players = [];
    rows.forEach(row => {
        const name = row.querySelector('.player-edit-name').value.trim();
        const id = row.querySelector('.player-edit-id').value.trim();
        if (name && id) players.push({ name, id });
    });

    if (!email) { showToast('Email is required', 'error'); return; }

    try {
        if (_editingAccountEmail) {
            // Update existing account
            await api(`/api/accounts/${encodeURIComponent(_editingAccountEmail)}`, {
                method: 'PUT',
                body: JSON.stringify({ email, priority, players }),
            });
            showToast('Account updated', 'success');
        } else {
            // Create new account
            await api('/api/accounts', {
                method: 'POST',
                body: JSON.stringify({ email, priority, players }),
            });
            showToast('Account created', 'success');
        }
        closeAccountEditModal();
        await refreshAccounts();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function deleteEditingAccount() {
    if (!_editingAccountEmail) return;
    if (!confirm(`Delete account ${_editingAccountEmail}? This cannot be undone.`)) return;
    try {
        await api(`/api/accounts/${encodeURIComponent(_editingAccountEmail)}`, { method: 'DELETE' });
        showToast('Account deleted', 'success');
        closeAccountEditModal();
        await refreshAccounts();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// Close account edit modal on overlay click
document.getElementById('accountEditModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeAccountEditModal();
});

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
