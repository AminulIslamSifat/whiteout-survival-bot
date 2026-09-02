// WOS-Bot Dashboard Frontend — Sable-inspired UI
const API = '';
let selectedTasks = new Set();
let selectedAccountEmails = new Set();
let selectedCharacters = {};  // email -> Set of player_ids
let botEventSource = null;
let ocrEventSource = null;
let statusInterval = null;
let _accountsCache = [];
let _tasks = [];

// --- Toast ---
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// --- Navigation (Activity Rail) ---
document.querySelectorAll('.rail-btn[data-view]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.rail-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`view-${btn.dataset.view}`).classList.add('active');

        if (btn.dataset.view === 'accounts') refreshAccounts();
        if (btn.dataset.view === 'tasks') renderTaskGrid();
        if (btn.dataset.view === 'settings') loadSettings();
        if (btn.dataset.view === 'logs') {
            setTimeout(() => {
                document.getElementById('botLogContainer').scrollTop = document.getElementById('botLogContainer').scrollHeight;
                document.getElementById('ocrLogContainer').scrollTop = document.getElementById('ocrLogContainer').scrollHeight;
            }, 50);
        }
    });
});

// --- API Helper ---
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
    const isRunning = s.status === 'running' || s.status === 'starting';

    // Status + Version
    document.getElementById('statStatus').innerHTML = `<span class="status-dot ${dotClass}"></span> ${label}`;
    const versionEl = document.getElementById('statVersion');
    if (versionEl) versionEl.textContent = `v${s.version || '0.0.0'}`;

    // ADB Device Status
    const adb = s.adb || {};
    const adbEl = document.getElementById('statAdb');
    const adbDetailEl = document.getElementById('statAdbDetail');

    if (adb.connected) {
        const devIds = (adb.devices || []).map(d => d.id).join(', ');
        if (adbEl) adbEl.innerHTML = `<span class="status-dot running"></span> Connected`;
        if (adbDetailEl) adbDetailEl.textContent = devIds;
    } else {
        const errMsg = adb.error || 'No device detected';
        if (adbEl) adbEl.innerHTML = `<span class="status-dot error"></span> Disconnected`;
        if (adbDetailEl) adbDetailEl.textContent = errMsg;
    }

    // OCR Engine Status + Module Versions (no manual controls — stops with bot)
    const ocrStatus = s.ocr_status || 'stopped';
    const ocrLabel = ocrStatus.charAt(0).toUpperCase() + ocrStatus.slice(1);
    document.getElementById('statOcr').innerHTML = `
        <span class="status-dot ${ocrStatus}"></span> ${ocrLabel}`;

    const ocrModulesEl = document.getElementById('statOcrModules');
    if (ocrModulesEl && s.ocr_modules) {
        const mods = s.ocr_modules;
        const lines = [];
        if (mods.paddleocr) lines.push(`PaddleOCR ${mods.paddleocr}`);
        if (mods.paddlepaddle) lines.push(`Paddle ${mods.paddlepaddle}`);
        if (mods.opencv) lines.push(`OpenCV ${mods.opencv}`);
        if (mods.rapidfuzz) lines.push(`RapidFuzz ${mods.rapidfuzz}`);
        ocrModulesEl.innerHTML = lines.length
            ? lines.map(l => `<div>${l}</div>`).join('')
            : '—';
    }

    // Total Accounts + Characters
    const accountsEl = document.getElementById('statAccounts');
    const charsEl = document.getElementById('statCharacters');
    if (accountsEl) accountsEl.textContent = s.total_accounts ?? 0;
    if (charsEl) charsEl.textContent = `${s.total_characters ?? 0} characters`;

    // Issues banner
    const issuesBanner = document.getElementById('issuesBanner');
    const issuesList = document.getElementById('issuesList');
    const issues = s.issues || [];
    const ready = s.ready !== false;

    if (!ready && issues.length > 0) {
        if (issuesBanner) issuesBanner.style.display = 'block';
        if (issuesList) {
            issuesList.innerHTML = issues.map(i => `<li>${escapeHtml(i)}</li>`).join('');
        }
    } else {
        if (issuesBanner) issuesBanner.style.display = 'none';
    }

    // Button states: hide Start when blocked, show blocked button instead
    const btnStart = document.getElementById('btnStartBot');
    const btnBlocked = document.getElementById('btnStartBlocked');
    const btnStop = document.getElementById('btnStopBot');

    if (isRunning) {
        if (btnStart) btnStart.style.display = 'none';
        if (btnBlocked) btnBlocked.style.display = 'none';
        if (btnStop) btnStop.disabled = false;
    } else if (!ready) {
        // Not ready — hide normal start, show blocked button
        if (btnStart) btnStart.style.display = 'none';
        if (btnBlocked) btnBlocked.style.display = '';
        if (btnStop) btnStop.disabled = true;
    } else {
        // Ready and not running — show normal start
        if (btnStart) { btnStart.style.display = ''; btnStart.disabled = false; }
        if (btnBlocked) btnBlocked.style.display = 'none';
        if (btnStop) btnStop.disabled = true;
    }

    // Update log panel status dots
    const botDot = s.status === 'running' ? 'running' : (s.status === 'starting' ? 'starting' : 'stopped');
    const ocrDot = ocrStatus === 'running' ? 'running' : (ocrStatus === 'starting' ? 'starting' : 'stopped');

    ['logBotDot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.className = `status-dot ${botDot}`;
    });
    ['logOcrDot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.className = `status-dot ${ocrDot}`;
    });
}

// --- Dual SSE Log Streams ---
function connectBotLogStream() {
    if (botEventSource) botEventSource.close();
    botEventSource = new EventSource(`${API}/api/logs/stream`);
    botEventSource.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            appendBotLog(data.line);
        } catch (err) {
            console.error('Bot SSE parse error:', err);
        }
    };
    botEventSource.onerror = () => setTimeout(connectBotLogStream, 3000);
}

function connectOcrLogStream() {
    if (ocrEventSource) ocrEventSource.close();
    ocrEventSource = new EventSource(`${API}/api/ocr/logs/stream`);
    ocrEventSource.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            appendOcrLog(data.line);
        } catch (err) {
            console.error('OCR SSE parse error:', err);
        }
    };
    ocrEventSource.onerror = () => setTimeout(connectOcrLogStream, 3000);
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

function formatLogHtml(line) {
    const cssClass = classifyLogLine(line);
    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    return `<div class="log-line ${cssClass}"><span style="opacity:0.4;margin-right:8px">${time}</span>${escapeHtml(line)}</div>`;
}

function trimLog(container, maxLines) {
    while (container.children.length > maxLines) {
        container.removeChild(container.firstChild);
    }
}

function shouldAutoScroll() {
    return document.getElementById('autoScrollToggle').checked;
}

function isImportantLog(line) {
    const l = line.toLowerCase();
    return l.includes('error') || l.includes('failed') || l.includes('❌') || l.includes('exception')
        || l.includes('✅') || l.includes('completed') || l.includes('success')
        || l.includes('[dashboard]') || l.includes('starting bot') || l.includes('bot stopped')
        || l.includes('running tasks for:') || l.includes('running task:')
        || l.includes('discovered') || l.includes('marked completed')
        || l.includes('ocr') && (l.includes('start') || l.includes('stop') || l.includes('ready') || l.includes('error'));
}

function appendUniversalLog(line, source) {
    if (!isImportantLog(line)) return;
    const tag = source === 'ocr' ? '<span style="color:var(--log-ocr);margin-right:6px">[OCR]</span>' : '<span style="color:var(--log-bot);margin-right:6px">[BOT]</span>';
    const cssClass = classifyLogLine(line);
    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const html = `<div class="log-line ${cssClass}"><span style="opacity:0.4;margin-right:8px">${time}</span>${tag}${escapeHtml(line)}</div>`;
    const el = document.getElementById('universalLog');
    if (!el) return;
    el.insertAdjacentHTML('beforeend', html);
    trimLog(el, 200);
    el.scrollTop = el.scrollHeight;
}

function appendBotLog(line) {
    const html = formatLogHtml(line);
    const botLog = document.getElementById('botLogContainer');
    botLog.insertAdjacentHTML('beforeend', html);
    trimLog(botLog, 1000);
    if (shouldAutoScroll()) botLog.scrollTop = botLog.scrollHeight;
    appendUniversalLog(line, 'bot');
}

function appendOcrLog(line) {
    const html = formatLogHtml(line);
    const ocrLog = document.getElementById('ocrLogContainer');
    ocrLog.insertAdjacentHTML('beforeend', html);
    trimLog(ocrLog, 1000);
    if (shouldAutoScroll()) ocrLog.scrollTop = ocrLog.scrollHeight;
    appendUniversalLog(line, 'ocr');
}

function clearLogView() {
    clearBotLog();
    clearOcrLog();
    showToast('Logs cleared', 'info');
}

function clearBotLog() {
    document.getElementById('botLogContainer').innerHTML = '';
}

function clearOcrLog() {
    document.getElementById('ocrLogContainer').innerHTML = '';
}

function clearUniversalLog() {
    const el = document.getElementById('universalLog');
    if (el) el.innerHTML = '';
}

// --- Tasks ---
async function loadTasks() {
    try {
        _tasks = await api('/api/tasks');
        window._tasks = _tasks;
        return _tasks;
    } catch (e) {
        console.error('Failed to load tasks:', e);
        showToast('Failed to load tasks', 'error');
        return [];
    }
}

function renderTaskGrid() {
    const tasks = _tasks || [];
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

function selectAllTasks() {
    (_tasks || []).forEach(t => selectedTasks.add(t.key));
    renderTaskGrid();
    showToast(`Selected all ${selectedTasks.size} tasks`, 'info');
}

function deselectAllTasks() {
    selectedTasks.clear();
    renderTaskGrid();
    showToast('Cleared selection', 'info');
}

document.getElementById('btnSelectAll').addEventListener('click', selectAllTasks);
document.getElementById('btnDeselectAll').addEventListener('click', deselectAllTasks);

// --- Bot Control ---
document.getElementById('btnStartBot').addEventListener('click', openTaskModal);
document.getElementById('btnStartBlocked').addEventListener('click', () => {
    // Scroll to status cards and flash the issues banner
    const banner = document.getElementById('issuesBanner');
    if (banner) {
        banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
        banner.classList.add('flash');
        setTimeout(() => banner.classList.remove('flash'), 1200);
    }
});

document.getElementById('btnStartWithTasks').addEventListener('click', async () => {
    const tasks = selectedTasks.size > 0 ? [...selectedTasks] : _tasks.map(t => t.key);
    await startBot(tasks);
});

document.getElementById('btnConfirmStart').addEventListener('click', async () => {
    const tasks = selectedTasks.size > 0 ? [...selectedTasks] : _tasks.map(t => t.key);
    closeTaskModal();
    await startBot(tasks);
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

        let isAllChars = true;
        for (const a of _accountsCache) {
            const charSet = selectedCharacters[a.email];
            if (!charSet || charSet.size !== a.players.length) {
                isAllChars = false;
                break;
            }
        }

        if (!isAllAccounts && selectedAccountEmails.size > 0) {
            payload.accounts = [...selectedAccountEmails];
        }

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
        // Switch to dashboard view
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

document.getElementById('taskModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeTaskModal();
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeTaskModal();
        closeAccountEditModal();
    }
});

// --- Accounts ---
async function refreshAccounts() {
    try {
        const accounts = await api('/api/accounts');
        const totalChars = accounts.reduce((sum, a) => sum + (a.players?.length || 0), 0);
        const accountsEl = document.getElementById('statAccounts');
        const charsEl = document.getElementById('statCharacters');
        if (accountsEl) accountsEl.textContent = accounts.length;
        if (charsEl) charsEl.textContent = `${totalChars} characters`;
        renderAccounts(accounts);
    } catch (e) {
        console.error('Failed to load accounts:', e);
        showToast('Failed to load accounts', 'error');
    }
}

let _editingAccountEmail = null;

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
        document.getElementById('editEmail').disabled = true;
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
            await api(`/api/accounts/${encodeURIComponent(_editingAccountEmail)}`, {
                method: 'PUT',
                body: JSON.stringify({ email, priority, players }),
            });
            showToast('Account updated', 'success');
        } else {
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
            <td style="font-family:var(--font-mono);font-size:12px">${r.last_completed}</td>
            <td style="font-family:var(--font-mono);font-size:12px">${formatDuration(r.hours_ago)}</td>
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

// --- Settings ---
async function loadSettings() {
    try {
        const s = await api('/api/settings');
        document.getElementById('settingCaptureTool').value = s.ocr_capture_tool || 'adb';
    } catch (e) {
        console.error('Failed to load settings:', e);
    }
}

async function saveSettings() {
    try {
        const payload = {
            ocr_capture_tool: document.getElementById('settingCaptureTool').value,
        };
        await api('/api/settings', { method: 'PUT', body: JSON.stringify(payload) });
        showToast('Settings saved', 'success');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

document.getElementById('btnSaveSettings').addEventListener('click', saveSettings);

// --- Init ---
async function init() {
    await loadTasks();
    await pollStatus();
    await refreshAccounts();
    await refreshCompletion();
    connectBotLogStream();
    connectOcrLogStream();
    statusInterval = setInterval(pollStatus, 3000);
}

init();
