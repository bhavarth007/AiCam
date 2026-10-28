// Environment & Global State
const isGitHubPages = window.location.hostname.includes('github.io') || window.location.protocol === 'file:' || window.location.search.includes('demo=true');
let cloudBackendUrl = localStorage.getItem('aicam_cloud_backend') || '';
let currentTab = 'attendance';
let pollInterval = null;
let webcamStream = null;

function getApiUrl(path) {
    if (cloudBackendUrl) {
        return cloudBackendUrl.replace(/\/+$/, '') + path;
    }
    return path;
}

// Initialization on DOM Load
document.addEventListener('DOMContentLoaded', () => {
    initEnvironment();
    initClock();
    initTabs();
    initSourceControls();
    initStaffRegistration();
    initReports();
    initUnknowns();
    initModule2();
    initModule3();

    if (isGitHubPages && !cloudBackendUrl) {
        initGitHubSimulator();
    } else {
        // Start 0.5s background auto-refresh for all site data (zero manual refresh needed!)
        fetchStats();
        fetchRecentEvents();
        fetchTodayReport();
        pollInterval = setInterval(() => {
            fetchStats();
            fetchRecentEvents();
            if (currentTab === 'unknowns') {
                loadUnknownsAuto();
            } else if (currentTab === 'reports') {
                fetchTodayReportAuto();
            }
        }, 500); // 0.5-second live auto-refresh
    }
});

function initEnvironment() {
    const navPill = document.getElementById('navConnPill');
    const btnConnect = document.getElementById('btnConnectLiveBackend');

    if (isGitHubPages) {
        if (cloudBackendUrl) {
            if (navPill) navPill.innerHTML = `🌐 Cloud Connected: <strong style="color: #34d399;">${cloudBackendUrl}</strong>`;
            if (btnConnect) {
                btnConnect.style.display = 'inline-flex';
                btnConnect.textContent = 'Disconnect Cloud';
                btnConnect.onclick = () => {
                    localStorage.removeItem('aicam_cloud_backend');
                    location.reload();
                };
            }
        } else {
            if (navPill) navPill.innerHTML = '🌐 <strong>GitHub Pages Showcase Edition</strong>';
            if (btnConnect) {
                btnConnect.style.display = 'inline-flex';
                btnConnect.textContent = '📡 Connect Live Mill Cam';
                btnConnect.onclick = promptBackendUrl;
            }
        }
    }
}

window.promptBackendUrl = function() {
    const defaultUrl = 'https://silly-concepts-apr-carries.trycloudflare.com';
    const input = prompt(
        "Enter your Live AI Camera Cloud URL (e.g. your Cloudflare Tunnel URL):\nLeave empty to disconnect and use interactive simulator.",
        cloudBackendUrl || defaultUrl
    );
    if (input !== null) {
        const trimmed = input.trim().replace(/\/+$/, '');
        if (trimmed) {
            localStorage.setItem('aicam_cloud_backend', trimmed);
        } else {
            localStorage.removeItem('aicam_cloud_backend');
        }
        location.reload();
    }
};

// ----------------- Clock & Date -----------------
function initClock() {
    const timeEl = document.getElementById('liveTime');
    const dateEl = document.getElementById('liveDate');

    function update() {
        const now = new Date();
        if (timeEl) timeEl.textContent = now.toLocaleTimeString('en-US', { hour12: true });
        if (dateEl) dateEl.textContent = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    }
    update();
    setInterval(update, 1000);
}

// ----------------- Tab Navigation -----------------
function initTabs() {
    const tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabTarget = tab.getAttribute('data-tab');
            switchTab(tabTarget);
        });
    });
}

function switchTab(tabId) {
    currentTab = tabId;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });

    document.querySelectorAll('.tab-content-pane').forEach(pane => {
        pane.style.display = (pane.id === `pane-${tabId}`) ? 'block' : 'none';
    });

    if (tabId === 'staff') {
        loadStaffList();
    } else if (tabId === 'reports') {
        fetchTodayReport();
    } else if (tabId === 'unknowns') {
        loadUnknowns();
    } else if (tabId === 'module2') {
        loadModule2Records();
    } else if (tabId === 'module3') {
        loadModule3Records();
    }
}

// ----------------- Live Camera & Sources -----------------
function initSourceControls() {
    const btnWebcam = document.getElementById('btnSrcWebcam');
    const btnSim = document.getElementById('btnSrcSim');
    const videoInput = document.getElementById('videoFileInput');
    const lineSlider = document.getElementById('linePosSlider');
    const lineVal = document.getElementById('linePosValue');

    if (btnWebcam) {
        btnWebcam.addEventListener('click', () => {
            setVideoSource('webcam');
        });
    }

    if (btnSim) {
        btnSim.addEventListener('click', () => {
            setVideoSource('synthetic');
        });
    }

    if (videoInput) {
        videoInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('video', file);

            const statusBanner = document.getElementById('sourceStatusText');
            if (statusBanner) statusBanner.textContent = 'Uploading gate CCTV video...';

            try {
                const res = await fetch('/api/video/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showNotification('Gate video uploaded and AI stream active!', 'success');
                    reloadCameraStream();
                } else {
                    showNotification('Upload error: ' + (data.detail || 'Failed'), 'error');
                }
            } catch (err) {
                showNotification('Network error uploading video.', 'error');
            }
        });
    }

    if (lineSlider) {
        lineSlider.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            if (lineVal) lineVal.textContent = Math.round(val * 100) + '%';
        });

        lineSlider.addEventListener('change', async (e) => {
            const val = parseFloat(e.target.value);
            const formData = new FormData();
            formData.append('ratio', val);
            formData.append('orientation', 'horizontal');

            await fetch('/api/tracking/set_line', {
                method: 'POST',
                body: formData
            });
            showNotification(`Gate entrance line set to ${Math.round(val * 100)}%`, 'info');
        });
    }

    // Live Counting & Video Controls
    const btnStart = document.getElementById('btnStartCounting');
    const btnStop = document.getElementById('btnStopCounting');
    const btnReset = document.getElementById('btnResetSessionCounts');

    if (btnStart) {
        btnStart.addEventListener('click', () => window.startLiveCounting());
    }
    if (btnStop) {
        btnStop.addEventListener('click', () => window.stopLiveCounting());
    }
    if (btnReset) {
        btnReset.addEventListener('click', () => window.resetSessionCrossings());
    }
}

// Global Video & Counting Controls
window.startLiveCounting = async function() {
    if (isGitHubPages && !cloudBackendUrl) {
        simCounting = true;
        updateCountingStatusUI(true);
        showNotification('▶️ Live Camera & AI Counting Started (Showcase)!', 'success');
        return;
    }
    try {
        const res = await fetch(getApiUrl('/api/video/start_counting'), { method: 'POST' });
        const data = await res.json();
        showNotification('▶️ Video & Live AI Counting Started!', 'success');
        updateCountingStatusUI(true);
        reloadCameraStream();
    } catch (e) {
        showNotification('Failed to start live counting', 'error');
    }
};

window.stopLiveCounting = async function() {
    if (isGitHubPages && !cloudBackendUrl) {
        simCounting = false;
        updateCountingStatusUI(false);
        showNotification('⏸️ Live Camera & AI Counting Paused!', 'warning');
        return;
    }
    try {
        const res = await fetch(getApiUrl('/api/video/stop_counting'), { method: 'POST' });
        const data = await res.json();
        showNotification('⏸️ Video & Live AI Counting Paused!', 'warning');
        updateCountingStatusUI(false);
    } catch (e) {
        showNotification('Failed to pause live counting', 'error');
    }
};

window.resetSessionCrossings = async function() {
    if (!confirm('Reset current session gate counts (IN, OUT, Unknowns) to 0 and rewind video?')) return;
    if (isGitHubPages && !cloudBackendUrl) {
        simStats.session_in = 0;
        simStats.session_out = 0;
        simStats.session_unknown = 0;
        renderSimStats();
        showNotification('🔄 Session counts reset to 0!', 'info');
        return;
    }
    try {
        const res = await fetch(getApiUrl('/api/video/reset_session'), { method: 'POST' });
        const data = await res.json();
        showNotification('🔄 Session counts reset to 0! Video rewound.', 'info');
        fetchStats();
        fetchRecentEvents();
        reloadCameraStream();
    } catch (e) {
        showNotification('Failed to reset session counts', 'error');
    }
};

function updateCountingStatusUI(isCounting) {
    const badge = document.getElementById('countingStatusBadge');
    const text = document.getElementById('countingStatusText');
    const btnStart = document.getElementById('btnStartCounting');
    const btnStop = document.getElementById('btnStopCounting');
    const overlay = document.getElementById('cameraStoppedOverlay');
    const headerTitle = document.getElementById('cameraCardHeaderTitle');
    const pulseDot = document.getElementById('cameraPulseDot');

    if (isCounting) {
        if (overlay) overlay.style.display = 'none';
        if (headerTitle) headerTitle.textContent = 'GATE CAMERA 01 - REAL-TIME AI TRACKING FEED (LIVE)';
        if (pulseDot) {
            pulseDot.style.background = '#10b981';
            pulseDot.style.boxShadow = '0 0 10px #10b981';
            pulseDot.style.animation = 'pulseDot 1.5s infinite';
        }
        if (badge && text) {
            badge.style.background = 'rgba(16,185,129,0.15)';
            badge.style.borderColor = 'rgba(16,185,129,0.3)';
            badge.style.color = '#34d399';
            text.textContent = 'LIVE COUNTING ACTIVE';
        }
        if (btnStart) {
            btnStart.style.opacity = '0.45';
            btnStart.disabled = false;
        }
        if (btnStop) {
            btnStop.style.opacity = '1.0';
            btnStop.disabled = false;
        }
    } else {
        if (overlay) overlay.style.display = 'flex';
        if (headerTitle) headerTitle.textContent = 'GATE CAMERA 01 - STREAM STOPPED (OFFLINE)';
        if (pulseDot) {
            pulseDot.style.background = '#f43f5e';
            pulseDot.style.boxShadow = '0 0 8px #f43f5e';
            pulseDot.style.animation = 'none';
        }
        if (badge && text) {
            badge.style.background = 'rgba(244,63,94,0.15)';
            badge.style.borderColor = 'rgba(244,63,94,0.3)';
            badge.style.color = '#fb7185';
            text.textContent = 'CAMERA & COUNTING STOPPED';
        }
        if (btnStart) {
            btnStart.style.opacity = '1.0';
            btnStart.disabled = false;
        }
        if (btnStop) {
            btnStop.style.opacity = '0.45';
            btnStop.disabled = false;
        }
    }
}

async function setVideoSource(type, path = null) {
    const formData = new FormData();
    formData.append('source_type', type);
    if (path) formData.append('source_path', path);

    try {
        const res = await fetch('/api/video/set_source', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        showNotification(`Switched camera source to ${type.toUpperCase()}`, 'info');
        reloadCameraStream();
    } catch (err) {
        showNotification('Failed to switch source', 'error');
    }
}

function reloadCameraStream() {
    const img = document.getElementById('cameraStream');
    if (img) {
        img.src = getApiUrl('/api/video_feed?t=' + new Date().getTime());
    }
}

// ----------------- Stats & Event Feeds -----------------
async function fetchStats() {
    try {
        const res = await fetch(getApiUrl('/api/stats'));
        const data = await res.json();

        // Update KPIs
        const elTotal = document.getElementById('kpiTotalStaff');
        const elPresent = document.getElementById('kpiPresentToday');
        const elInside = document.getElementById('kpiCurrentlyInside');
        const elAbsent = document.getElementById('kpiAbsentToday');
        const elUnknowns = document.getElementById('kpiUnknownsToday');
        const elFps = document.getElementById('liveFps');
        const elSource = document.getElementById('sourceStatusText');

        if (elTotal) elTotal.textContent = data.total_staff || 0;
        if (elPresent) elPresent.textContent = data.present_today || 0;
        if (elInside) elInside.textContent = data.currently_inside || 0;
        if (elAbsent) elAbsent.textContent = data.absent_today || 0;
        if (elUnknowns) elUnknowns.textContent = data.unknowns_today || 0;
        if (elFps) elFps.textContent = `${data.fps || 25.0} FPS`;

        // Unknowns badge in tab
        const unkBadge = document.getElementById('unknownsCountBadge');
        if (unkBadge) {
            unkBadge.textContent = data.unknowns_today || 0;
            unkBadge.style.display = (data.unknowns_today > 0) ? 'inline-block' : 'none';
        }

        if (elSource) {
            elSource.textContent = `Source: ${data.source_type.toUpperCase()} | Line: ${Math.round(data.line_ratio * 100)}%`;
        }

        if (data.is_counting !== undefined) {
            updateCountingStatusUI(data.is_counting);
        }
    } catch (e) {
        // Silently retry
    }
}

async function fetchRecentEvents() {
    try {
        const res = await fetch(getApiUrl('/api/events/recent'));
        const events = await res.json();
        const container = document.getElementById('recentEventsList');
        if (!container) return;

        if (events.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; color: var(--text-muted); padding: 2rem;">
                    <p>No gate crossing events yet.</p>
                    <p style="font-size: 0.75rem; margin-top: 0.3rem;">Walk past the gate line or run video simulation.</p>
                </div>
            `;
            return;
        }

        let html = '';
        events.forEach(ev => {
            const isUnk = ev.type === 'unknown';
            const isIN = ev.direction === 'IN';
            const cssClass = isUnk ? 'unknown-event' : (isIN ? 'in-event' : 'out-event');
            const badgeBg = isUnk ? '#f43f5e' : (isIN ? '#10b981' : '#f59e0b');

            html += `
                <div class="feed-item ${cssClass}">
                    <div class="feed-content">
                        <div class="feed-top">
                            <span class="feed-name">${escapeHtml(ev.title)}</span>
                            <span class="feed-time">${ev.time}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 6px; margin: 3px 0;">
                            <span style="background: ${badgeBg}; color: #fff; font-size: 0.65rem; font-weight: 700; padding: 1px 6px; border-radius: 4px;">
                                ${ev.badge}
                            </span>
                            <span style="font-size: 0.72rem; color: #cbd5e1; font-family: monospace;">${ev.code}</span>
                        </div>
                        <p class="feed-msg">${escapeHtml(ev.msg)}</p>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch (e) {}
}

// ----------------- Staff Registration & Face ID -----------------
// ----------------- Staff Registration & Face ID -----------------
function initStaffRegistration() {
    const modal = document.getElementById('registerStaffModal');
    const btnOpen = document.getElementById('btnOpenRegister');
    const btnClose = document.getElementById('btnCloseRegister');
    const form = document.getElementById('staffRegisterForm');
    const photoFile = document.getElementById('regPhotoFile');
    const photoPreview = document.getElementById('regPhotoPreview');
    const btnSnap = document.getElementById('btnSnapWebcam');
    const btnLiveSnap = document.getElementById('btnSnapLiveCamera');
    const webcamVideo = document.getElementById('regWebcamVideo');
    const btnClear = document.getElementById('btnClearTestData');
    const editModal = document.getElementById('editStaffModal');
    const btnCloseEdit = document.getElementById('btnCloseEditStaff');
    const editForm = document.getElementById('editStaffForm');

    if (btnOpen) {
        btnOpen.addEventListener('click', () => {
            modal.style.display = 'flex';
            generateAutoStaffCode();
        });
    }

    if (btnClose) {
        btnClose.addEventListener('click', () => {
            stopRegistrationWebcam();
            modal.style.display = 'none';
        });
    }

    if (btnCloseEdit && editModal) {
        btnCloseEdit.addEventListener('click', () => {
            editModal.style.display = 'none';
        });
    }

    // Grab Face Directly from Live Running AI Camera (No browser permissions needed!)
    if (btnLiveSnap) {
        btnLiveSnap.addEventListener('click', async () => {
            btnLiveSnap.textContent = '📸 Grabbing Frame...';
            try {
                const res = await fetch('/api/camera/snapshot?t=' + Date.now());
                if (!res.ok) throw new Error('Camera snapshot failed');
                const blob = await res.blob();
                const reader = new FileReader();
                reader.onload = (e) => {
                    photoPreview.src = e.target.result;
                    photoPreview.style.display = 'block';
                    document.getElementById('regPhotoBase64').value = e.target.result;
                    document.getElementById('regPhotoUrl').value = '';
                    if (webcamVideo) webcamVideo.style.display = 'none';
                    stopRegistrationWebcam();
                    btnLiveSnap.textContent = '📸 Grab Live AI Camera Face';
                    showNotification('Grabbed face directly from live AI camera!', 'success');
                };
                reader.readAsDataURL(blob);
            } catch (err) {
                btnLiveSnap.textContent = '📸 Grab Live AI Camera Face';
                showNotification('Camera frame not ready. Check camera connection.', 'error');
            }
        });
    }

    // Clear Raw / Test Data
    if (btnClear) {
        btnClear.addEventListener('click', async () => {
            if (!confirm('Are you sure you want to clean all dummy/test attendance data?')) return;
            const formData = new FormData();
            formData.append('clear_staff', 'false');
            try {
                const res = await fetch('/api/system/clear_data', { method: 'POST', body: formData });
                const data = await res.json();
                showNotification(data.message, 'success');
                loadStaffList();
                fetchStats();
                fetchTodayReport();
                fetchRecentEvents();
            } catch (e) {
                showNotification('Error clearing data', 'error');
            }
        });
    }

    // Edit Staff Form Submission
    if (editForm) {
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(editForm);
            try {
                const res = await fetch('/api/staff/update', { method: 'POST', body: formData });
                const data = await res.json();
                showNotification(data.message, 'success');
                if (editModal) editModal.style.display = 'none';
                loadStaffList();
                fetchTodayReport();
            } catch (e) {
                showNotification('Failed to update staff', 'error');
            }
        });
    }

    // Photo file change preview
    if (photoFile) {
        photoFile.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (re) => {
                    photoPreview.src = re.target.result;
                    photoPreview.style.display = 'block';
                    document.getElementById('regPhotoUrl').value = '';
                    document.getElementById('regPhotoBase64').value = '';
                    if (webcamVideo) webcamVideo.style.display = 'none';
                };
                reader.readAsDataURL(file);
            }
        });
    }

    // Live Snapshot from Client Camera (Browser getUserMedia fallback)
    if (btnSnap) {
        btnSnap.addEventListener('click', async () => {
            if (!webcamStream) {
                try {
                    webcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
                    webcamVideo.srcObject = webcamStream;
                    webcamVideo.style.display = 'block';
                    photoPreview.style.display = 'none';
                    btnSnap.textContent = '📸 Capture Photo Now';
                } catch (err) {
                    showNotification('Webcam busy or not allowed. Use "Grab Live AI Camera Face" button above!', 'warning');
                }
            } else {
                const canvas = document.createElement('canvas');
                canvas.width = webcamVideo.videoWidth || 640;
                canvas.height = webcamVideo.videoHeight || 480;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);
                const base64 = canvas.toDataURL('image/jpeg');

                photoPreview.src = base64;
                photoPreview.style.display = 'block';
                document.getElementById('regPhotoBase64').value = base64;
                document.getElementById('regPhotoUrl').value = '';

                stopRegistrationWebcam();
                btnSnap.textContent = '📷 Browser Webcam';
            }
        });
    }

    // Submit Registration Form
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btnSubmit = document.getElementById('btnSubmitRegister');
            btnSubmit.disabled = true;
            btnSubmit.textContent = 'AI Extracting Face Embedding...';

            const formData = new FormData(form);

            try {
                const res = await fetch('/api/staff/register', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (res.ok && data.status === 'success') {
                    showNotification(`Registered ${data.name} with Face ID!`, 'success');
                    stopRegistrationWebcam();
                    modal.style.display = 'none';
                    form.reset();
                    photoPreview.style.display = 'none';
                    document.getElementById('regPhotoUrl').value = '';
                    document.getElementById('regPhotoBase64').value = '';
                    loadStaffList();
                    fetchStats();
                    fetchTodayReport();
                } else {
                    showNotification(data.detail || 'Registration failed', 'error');
                }
            } catch (err) {
                showNotification('Network error during registration', 'error');
            } finally {
                btnSubmit.disabled = false;
                btnSubmit.textContent = 'Verify Face & Register Staff';
            }
        });
    }
}

function stopRegistrationWebcam() {
    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
    }
}

function generateAutoStaffCode() {
    const input = document.getElementById('regFaceId');
    if (input && !input.value) {
        const rand = Math.floor(100 + Math.random() * 900);
        input.value = `FC-TXS-${rand}`;
    }
}

async function loadStaffList() {
    const container = document.getElementById('staffGridContainer');
    if (!container) return;

    try {
        const res = await fetch('/api/staff');
        const staffList = await res.json();

        if (staffList.length === 0) {
            container.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 3rem; color: var(--text-muted);">
                    <h3>No Staff Registered Yet</h3>
                    <p style="margin-top: 0.5rem;">Click "Register New Staff" to add Name, Designation, and Face ID.</p>
                </div>
            `;
            return;
        }

        let html = '';
        staffList.forEach(s => {
            const photoUrl = s.photo_path || '/static/img/avatar_placeholder.png';
            html += `
                <div class="kpi-card" style="flex-direction: column; align-items: flex-start; gap: 0.85rem;">
                    <div style="display: flex; gap: 0.85rem; width: 100%; align-items: center;">
                        <img src="${photoUrl}" class="staff-thumb" style="width: 54px; height: 54px; border-radius: 10px;" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'54\\' height=\\'54\\' fill=\\'%2364748b\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%231e293b\\'/><text x=\\'50%\\' y=\\'55%\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\' fill=\\'%2394a3b8\\' font-size=\\'20\\'>👤</text></svg>'">
                        <div style="flex: 1;">
                            <h4 style="font-size: 0.95rem; font-weight: 700; color: #fff;">${escapeHtml(s.name)}</h4>
                            <p style="font-size: 0.78rem; color: var(--accent-cyan); font-weight: 600;">${escapeHtml(s.designation)}</p>
                            <span style="font-size: 0.72rem; color: var(--text-muted); font-family: monospace;">${s.staff_code} | Face ID: ${s.face_id}</span>
                        </div>
                    </div>
                    <div style="display: flex; justify-content: space-between; width: 100%; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.6rem; flex-wrap: wrap; gap: 0.4rem;">
                        <span class="status-badge badge-completed">AI Face Active</span>
                        <div style="display: flex; gap: 0.35rem; align-items: center;">
                            <button class="btn btn-secondary" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="openEditStaffModal(${s.id}, '${escapeHtml(s.name)}', '${escapeHtml(s.designation)}')">✏️ Edit</button>
                            <button class="btn btn-secondary" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="simulateGatePass(${s.id}, 'IN')">IN</button>
                            <button class="btn btn-secondary" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="simulateGatePass(${s.id}, 'OUT')">OUT</button>
                            <button class="btn btn-rose" style="padding: 0.25rem 0.45rem; font-size: 0.72rem;" onclick="deleteStaffMember(${s.id})">✕</button>
                        </div>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch (e) {
        showNotification('Failed to load staff list', 'error');
    }
}

window.openEditStaffModal = function(staffId, name, desig) {
    const idInput = document.getElementById('editStaffId');
    const nameInput = document.getElementById('editStaffName');
    const desigInput = document.getElementById('editStaffDesignation');
    const modal = document.getElementById('editStaffModal');
    if (idInput) idInput.value = staffId;
    if (nameInput) nameInput.value = name;
    if (desigInput) desigInput.value = desig;
    if (modal) modal.style.display = 'flex';
};

async function simulateGatePass(staffId, direction) {
    const formData = new FormData();
    formData.append('staff_id', staffId);
    formData.append('direction', direction);

    try {
        const res = await fetch('/api/attendance/manual_event', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        showNotification(data.message, 'success');
        fetchStats();
        fetchRecentEvents();
        fetchTodayReport();
    } catch (e) {
        showNotification('Error recording simulation', 'error');
    }
}

async function deleteStaffMember(staffId) {
    if (!confirm('Are you sure you want to deactivate this staff member?')) return;
    try {
        await fetch(`/api/staff/${staffId}`, { method: 'DELETE' });
        showNotification('Staff member removed.', 'info');
        loadStaffList();
        fetchStats();
    } catch (e) {
        showNotification('Delete failed', 'error');
    }
}

// ----------------- Daily Reports & Working Hours -----------------
function initReports() {
    const dateInput = document.getElementById('reportDatePicker');
    const btnFilter = document.getElementById('btnFilterReport');
    const btnPrint = document.getElementById('btnPrintReport');
    const searchInput = document.getElementById('reportSearchInput');

    if (dateInput) {
        dateInput.value = new Date().toISOString().split('T')[0];
    }

    if (btnFilter) {
        btnFilter.addEventListener('click', () => {
            fetchTodayReport(dateInput.value);
        });
    }

    if (btnPrint) {
        btnPrint.addEventListener('click', () => {
            window.print();
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            filterReportTable(searchInput.value.toLowerCase());
        });
    }
}

let lastReportSig = "";

async function fetchTodayReportAuto() {
    const dateInput = document.getElementById('reportDatePicker');
    const customDate = dateInput && dateInput.value ? dateInput.value : null;
    const url = customDate ? `/api/attendance/report?date=${customDate}` : '/api/attendance/today';

    try {
        const res = await fetch(url);
        const data = await res.json();
        const records = data.records || [];
        const sig = JSON.stringify(records.map(r => `${r.id}-${r.in_count}-${r.out_count}-${r.status}-${r.live_hours || r.total_hours}`));
        if (sig !== lastReportSig) {
            lastReportSig = sig;
            renderAttendanceReportTable(records, data.date);
        }
    } catch (e) {}
}

async function fetchTodayReport(customDate = null) {
    const url = customDate ? `/api/attendance/report?date=${customDate}` : '/api/attendance/today';
    try {
        const res = await fetch(url);
        const data = await res.json();
        const records = data.records || [];
        lastReportSig = JSON.stringify(records.map(r => `${r.id}-${r.in_count}-${r.out_count}-${r.status}-${r.live_hours || r.total_hours}`));
        renderAttendanceReportTable(records, data.date);
    } catch (e) {
        console.error('Failed to load report:', e);
    }
}

function renderAttendanceReportTable(records, reportDate) {
    const tableBody = document.getElementById('attendanceTableBody');
    if (!tableBody) return;

    const printDateEl = document.getElementById('printReportDate');
    if (printDateEl) printDateEl.textContent = reportDate;

    if (records.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="11" style="text-align: center; color: var(--text-muted); padding: 2.5rem;">
                    No attendance recorded for ${reportDate}. Staff will automatically appear here when crossing the gate camera.
                </td>
            </tr>
        `;
        return;
    }

    let html = '';
    records.forEach((r, idx) => {
        const photo = r.photo_path || '';
        const statusClass = (r.status === 'Working') ? 'badge-working' :
                           (r.status === 'Completed' ? 'badge-completed' :
                           (r.status === 'Overtime' ? 'badge-overtime' : 'badge-half'));

        // Live or calculated hours
        const hoursVal = r.live_hours !== undefined ? r.live_hours : r.total_hours;
        const isOutside = (r.status === 'Outside' || (r.out_time && r.status !== 'Working'));

        // In / Out Counts Badge
        const inCnt = r.in_count || 1;
        const outCnt = r.out_count || 0;
        const countColHtml = `
            <div style="font-family: monospace; font-size: 0.78rem; display: flex; flex-direction: column; gap: 3px;">
                <span style="color: #34d399; font-weight: 700; background: rgba(16,185,129,0.12); padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(16,185,129,0.25);">
                    🟢 IN: ${inCnt}x
                </span>
                <span style="color: #fbbf24; font-weight: 700; background: rgba(245,158,11,0.12); padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(245,158,11,0.25);">
                    🚪 OUT: ${outCnt}x
                </span>
            </div>
        `;

        // Out Time column handling
        let outTimeHtml = '';
        if (isOutside) {
            outTimeHtml = `
                <div style="font-family: monospace; color: #fbbf24; font-weight: 700;">🚪 ${r.out_time}</div>
                <div style="font-size: 0.72rem; color: #f59e0b; font-weight: 600;">(Outside: ${r.hours_outside || 0} hrs)</div>
            `;
        } else {
            outTimeHtml = `<span class="status-badge" style="background: rgba(16,185,129,0.18); color: #34d399; font-weight:700;">🟢 Inside Office</span>`;
        }

        // Working hours display
        const hoursDisplay = (r.status === 'Working') ? `⏳ ${hoursVal} hrs (Ongoing)` : `✓ ${hoursVal} hrs`;

        // Status badge display
        const statusBadge = isOutside ?
            `<span class="status-badge" style="background: rgba(245,158,11,0.2); color: #fbbf24; font-weight: 700;">🚪 Outside Gate</span>` :
            `<span class="status-badge ${statusClass}">${r.status}</span>`;

        html += `
            <tr data-name="${escapeHtml(r.name).toLowerCase()}" data-desig="${escapeHtml(r.designation).toLowerCase()}">
                <td style="font-weight: 600; color: var(--text-muted);">${idx + 1}</td>
                <td>
                    <img src="${photo}" class="staff-thumb" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'38\\' height=\\'38\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%231e293b\\'/><text x=\\'50%\\' y=\\'55%\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\' fill=\\'%2394a3b8\\' font-size=\\'14\\'>👤</text></svg>'">
                </td>
                <td style="font-family: monospace; font-weight: 700; color: var(--accent-cyan);">${r.staff_code}</td>
                <td style="font-weight: 700; color: #fff;">${escapeHtml(r.name)}</td>
                <td style="color: #cbd5e1;">${escapeHtml(r.designation)}</td>
                <td style="font-family: monospace; font-weight: 600; color: #94a3b8;">${r.date}</td>
                <td>${countColHtml}</td>
                <td style="font-family: monospace; color: #34d399; font-weight: 600;">${r.in_time || '--:--'}</td>
                <td>${outTimeHtml}</td>
                <td style="font-weight: 700; font-family: monospace; color: #e2e8f0;">${hoursDisplay}</td>
                <td>${statusBadge}</td>
            </tr>
        `;
    });
    tableBody.innerHTML = html;
}

function filterReportTable(query) {
    const rows = document.querySelectorAll('#attendanceTableBody tr');
    rows.forEach(row => {
        const name = row.getAttribute('data-name') || '';
        const desig = row.getAttribute('data-desig') || '';
        if (name.includes(query) || desig.includes(query)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

// ----------------- Unknown Visitors Log (Date Folders & Deletion) -----------------
function initUnknowns() {
    const datePicker = document.getElementById('unknownDatePicker');
    const btnFilter = document.getElementById('btnFilterUnknowns');
    const btnClearDate = document.getElementById('btnClearDateUnknowns');
    const btnClearAll = document.getElementById('btnDeleteAllUnknownsTotal');

    if (datePicker && !datePicker.value) {
        datePicker.value = new Date().toISOString().split('T')[0];
    }
    if (btnFilter) {
        btnFilter.addEventListener('click', () => window.filterUnknownsByDate());
    }
    if (btnClearDate) {
        btnClearDate.addEventListener('click', () => window.deleteAllUnknownsForDate());
    }
    if (btnClearAll) {
        btnClearAll.addEventListener('click', () => window.deleteAllUnknownsCompletely());
    }
}

window.filterUnknownsByDate = function() {
    const datePicker = document.getElementById('unknownDatePicker');
    loadUnknowns(datePicker ? datePicker.value : null, true);
};

let lastUnknownsSig = "";

async function loadUnknownsAuto() {
    const datePicker = document.getElementById('unknownDatePicker');
    const targetDate = datePicker && datePicker.value ? datePicker.value.trim() : null;
    const url = targetDate ? `/api/unknowns?date=${encodeURIComponent(targetDate)}` : '/api/unknowns';

    try {
        const res = await fetch(url);
        const list = await res.json();
        const sig = JSON.stringify((list || []).map(x => `${x.id}-${x.timestamp}`));
        if (sig !== lastUnknownsSig) {
            lastUnknownsSig = sig;
            renderUnknownsGallery(list, targetDate);
        }
    } catch (e) {}
}

async function loadUnknowns(filterDate = null, force = false) {
    const datePicker = document.getElementById('unknownDatePicker');
    const targetDate = filterDate || (datePicker && datePicker.value ? datePicker.value.trim() : null);
    const url = targetDate ? `/api/unknowns?date=${encodeURIComponent(targetDate)}` : '/api/unknowns';

    try {
        const res = await fetch(url);
        const list = await res.json();
        const sig = JSON.stringify((list || []).map(x => `${x.id}-${x.timestamp}`));
        if (force || sig !== lastUnknownsSig) {
            lastUnknownsSig = sig;
            renderUnknownsGallery(list, targetDate);
        }
    } catch (e) {
        showNotification('Failed to load unknown snapshots', 'error');
    }
}

function renderUnknownsGallery(list, targetDate) {
    const container = document.getElementById('unknownsGallery');
    if (!container) return;

    if (!list || list.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 3rem; color: var(--text-muted);">
                <h3>No Unknown Persons for ${targetDate || 'Today'}</h3>
                <p style="margin-top: 0.5rem;">Unregistered visitor face snapshots are saved in folder <code>/data/unknown_snapshots/${targetDate || 'YYYY-MM-DD'}/</code>.</p>
            </div>
        `;
        return;
    }

    let html = '';
    list.forEach(item => {
        const snap = item.snapshot_path || '';
        const full = item.full_path || snap;
        html += `
            <div class="snapshot-card" id="unknown-card-${item.id}">
                <div style="position: relative; overflow: hidden; cursor: pointer;" onclick="openImageLightbox('${snap}', '${full}', '${item.date}', '${item.timestamp}', ${item.id})" title="Click to view full screen without opening new tab">
                    <img src="${snap}" class="snapshot-img" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'240\\' height=\\'180\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%231e293b\\'/><text x=\\'50%\\' y=\\'50%\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\' fill=\\'%23f43f5e\\' font-size=\\'18\\'>⚠️ Unknown Face</text></svg>'">
                    <span style="position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,0.75); color: #fff; font-size: 0.7rem; font-weight: 700; padding: 2px 7px; border-radius: 4px; pointer-events: none; border: 1px solid rgba(255,255,255,0.25);">
                        🔍 4K View
                    </span>
                </div>
                <div class="snapshot-footer">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span class="status-badge" style="background: rgba(244,63,94,0.2); color: #fb7185;">Unregistered</span>
                        <span style="font-size: 0.72rem; color: var(--text-muted); font-family: monospace;">${item.timestamp.split(' ')[1] || ''}</span>
                    </div>
                    <p style="font-size: 0.75rem; color: #cbd5e1; margin-top: 0.2rem;">Folder: <code>/${item.date}/</code></p>
                    <div style="display: flex; gap: 0.4rem; margin-top: 0.5rem;">
                        <button class="btn btn-primary" style="flex: 2; font-size: 0.75rem; justify-content: center; padding: 0.35rem 0.6rem;" onclick="registerFromUnknown('${snap}')">
                            ➕ Register Staff
                        </button>
                        <button class="btn btn-rose" style="flex: 1; font-size: 0.75rem; justify-content: center; padding: 0.35rem 0.5rem;" onclick="deleteUnknown(${item.id})">
                            🗑️ Delete
                        </button>
                    </div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

// ----------------- Interactive Fullscreen In-Page Lightbox -----------------
let currentLightboxItem = null;
let lightboxShowingFull = false;

window.openImageLightbox = function(portraitUrl, fullUrl, date, timestamp, id) {
    currentLightboxItem = { portraitUrl, fullUrl, date, timestamp, id };
    lightboxShowingFull = false;

    const modal = document.getElementById('imageLightboxModal');
    const img = document.getElementById('lightboxImage');
    const dateEl = document.getElementById('lightboxDateTime');
    const toggleBtn = document.getElementById('btnLightboxToggleView');
    const toggleText = document.getElementById('lightboxToggleText');
    const subtext = document.getElementById('lightboxSubtext');

    if (img) img.src = portraitUrl;
    if (dateEl) dateEl.textContent = `Date: ${date} | Time: ${timestamp} (Ultra-Clear 4K)`;
    if (subtext) subtext.textContent = 'Camera: Gate Cam 01 | View: Ultra-HD Framed Portrait';
    if (toggleText) toggleText.textContent = (fullUrl && fullUrl !== portraitUrl) ? 'Show Full 4K Gate View' : 'Ultra-HD Portrait';
    if (toggleBtn) toggleBtn.style.display = (fullUrl && fullUrl !== portraitUrl) ? 'inline-flex' : 'none';

    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
};

window.closeImageLightbox = function(event = null) {
    if (event && event.target && event.target.id !== 'imageLightboxModal' && !event.target.classList.contains('lightbox-close-btn')) {
        return;
    }
    const modal = document.getElementById('imageLightboxModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
    }
    currentLightboxItem = null;
};

window.toggleLightboxFullView = function() {
    if (!currentLightboxItem) return;
    const img = document.getElementById('lightboxImage');
    const toggleText = document.getElementById('lightboxToggleText');
    const subtext = document.getElementById('lightboxSubtext');

    lightboxShowingFull = !lightboxShowingFull;
    if (lightboxShowingFull) {
        img.src = currentLightboxItem.fullUrl || currentLightboxItem.portraitUrl;
        if (toggleText) toggleText.textContent = 'Show Framed Portrait';
        if (subtext) subtext.textContent = 'Camera: Gate Cam 01 | View: Full 4K Gate Perspective';
    } else {
        img.src = currentLightboxItem.portraitUrl;
        if (toggleText) toggleText.textContent = 'Show Full 4K Gate View';
        if (subtext) subtext.textContent = 'Camera: Gate Cam 01 | View: Ultra-HD Framed Portrait';
    }
};

window.registerFromLightbox = function() {
    if (!currentLightboxItem) return;
    const url = currentLightboxItem.portraitUrl;
    closeImageLightbox();
    registerFromUnknown(url);
};

window.deleteFromLightbox = async function() {
    if (!currentLightboxItem) return;
    const id = currentLightboxItem.id;
    closeImageLightbox();
    await deleteUnknown(id);
};

// Global escape key listener to close lightbox
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        window.closeImageLightbox();
    }
});

// Global Delete Functions for Unknowns
window.deleteUnknown = async function(id) {
    if (!confirm('Are you sure you want to delete this unknown person snapshot?')) return;
    try {
        const res = await fetch(`/api/unknowns/${id}`, { method: 'DELETE' });
        const data = await res.json();
        showNotification(data.message || 'Snapshot deleted.', 'info');
        const card = document.getElementById(`unknown-card-${id}`);
        if (card) {
            card.style.transition = 'all 0.25s ease';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.8)';
            setTimeout(() => card.remove(), 250);
        }
        lastUnknownsSig = ""; // Force reload on next 0.5s auto-poll
        fetchStats();
    } catch (e) {
        showNotification('Failed to delete unknown snapshot', 'error');
    }
};

window.deleteAllUnknownsForDate = async function() {
    const datePicker = document.getElementById('unknownDatePicker');
    const targetDate = datePicker && datePicker.value ? datePicker.value.trim() : null;
    if (!targetDate) {
        showNotification('Please pick a date first, or use "Delete ALL Unknowns".', 'warning');
        return;
    }
    if (!confirm(`Are you sure you want to delete all unknown snapshots for folder ${targetDate}?`)) return;

    try {
        let res = await fetch(`/api/unknowns?date=${encodeURIComponent(targetDate)}`, { method: 'DELETE' });
        if (!res.ok) {
            const fd = new FormData();
            fd.append('date_str', targetDate);
            res = await fetch('/api/unknowns/clear_all', { method: 'POST', body: fd });
        }
        const data = await res.json();
        showNotification(data.message || 'Deleted snapshots for date.', 'success');
        lastUnknownsSig = "";
        loadUnknowns(targetDate, true);
        fetchStats();
    } catch (e) {
        showNotification('Error deleting snapshots: ' + e.message, 'error');
    }
};

window.deleteAllUnknownsCompletely = async function() {
    if (!confirm('💥 Are you sure you want to delete ALL unknown visitor records and photos across ALL dates? This cannot be undone.')) return;

    try {
        let res = await fetch('/api/unknowns', { method: 'DELETE' });
        if (!res.ok) {
            res = await fetch('/api/unknowns/clear_all', { method: 'POST' });
        }
        const data = await res.json();
        showNotification(data.message || 'All unknown snapshots deleted successfully!', 'success');
        
        lastUnknownsSig = "[]";
        const container = document.getElementById('unknownsGallery');
        if (container) {
            container.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 3rem; color: var(--text-muted);">
                    <h3>No Unknown Persons</h3>
                    <p style="margin-top: 0.5rem;">All unknown visitor snapshots have been completely cleared.</p>
                </div>
            `;
        }
        const elUnknowns = document.getElementById('kpiUnknownsToday');
        if (elUnknowns) elUnknowns.textContent = '0';
        const unkBadge = document.getElementById('unknownsCountBadge');
        if (unkBadge) unkBadge.style.display = 'none';

        fetchStats();
    } catch (e) {
        showNotification('Error deleting all snapshots: ' + e.message, 'error');
    }
};

window.loadUnknowns = loadUnknowns;
window.registerFromUnknown = registerFromUnknown;

function registerFromUnknown(snapshotUrl) {
    switchTab('staff');
    const modal = document.getElementById('registerStaffModal');
    if (modal) modal.style.display = 'flex';

    const photoPreview = document.getElementById('regPhotoPreview');
    if (photoPreview) {
        photoPreview.src = snapshotUrl;
        photoPreview.style.display = 'block';
    }
    // Set the hidden input photo_url to this snapshot
    document.getElementById('regPhotoUrl').value = snapshotUrl;
    document.getElementById('regPhotoBase64').value = '';
    const fileInput = document.getElementById('regPhotoFile');
    if (fileInput) fileInput.value = '';

    generateAutoStaffCode();
    const nameInput = document.getElementById('regName');
    if (nameInput) nameInput.focus();
    showNotification('Pre-filled unknown person face snapshot. Enter Name and Designation to complete registration.', 'info');
}

// ----------------- Module 2: Sarees & Taka Bunch Counter -----------------
function initModule2() {
    const form = document.getElementById('sareeTakaForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const payload = {
                challan_no: document.getElementById('m2ChallanNo').value,
                party_name: document.getElementById('m2PartyName').value,
                delivery_boy: document.getElementById('m2DeliveryBoy').value,
                product_type: document.getElementById('m2ProductType').value,
                expected_qty: parseInt(document.getElementById('m2ExpectedQty').value) || 0,
                counted_qty: parseInt(document.getElementById('m2CountedQty').value) || 0,
                signed_by: document.getElementById('m2SignedBy').value || null,
                notes: document.getElementById('m2Notes').value || ''
            };

            try {
                const res = await fetch('/api/module2/record', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showNotification('Challan & Saree count verified!', 'success');
                    form.reset();
                    loadModule2Records();
                }
            } catch (err) {
                showNotification('Error logging record', 'error');
            }
        });
    }
}

async function loadModule2Records() {
    const body = document.getElementById('module2TableBody');
    if (!body) return;

    try {
        const res = await fetch('/api/module2/records');
        const list = await res.json();

        if (list.length === 0) {
            body.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">No Saree/Taka counting records yet.</td></tr>';
            return;
        }

        let html = '';
        list.forEach((r, i) => {
            const diff = r.difference;
            const diffBadge = diff === 0 ? '<span style="color: #34d399; font-weight: 700;">✓ 0 (Exact)</span>' :
                              (diff > 0 ? `<span style="color: #38bdf8; font-weight: 700;">+${diff} (Extra)</span>` :
                              `<span style="color: #f87171; font-weight: 700;">${diff} (Short)</span>`);

            html += `
                <tr>
                    <td>${i + 1}</td>
                    <td style="font-family: monospace; font-weight: 700; color: #38bdf8;">${escapeHtml(r.challan_no)}</td>
                    <td style="font-weight: 700; color: #fff;">${escapeHtml(r.party_name)}</td>
                    <td>${escapeHtml(r.delivery_boy)}</td>
                    <td style="color: #cbd5e1;">${escapeHtml(r.product_type)}</td>
                    <td style="font-family: monospace;">${r.expected_qty}</td>
                    <td style="font-family: monospace; font-weight: 700; color: #34d399;">${r.counted_qty}</td>
                    <td>${diffBadge}</td>
                    <td><span class="status-badge ${diff === 0 ? 'badge-completed' : 'badge-half'}">${r.status}</span></td>
                </tr>
            `;
        });
        body.innerHTML = html;
    } catch (e) {}
}

// ----------------- Module 3: Yarn Boxes & Rapier Bimps -----------------
function initModule3() {
    const btnBoxIn = document.getElementById('btnCountBoxIn');
    const btnBoxOut = document.getElementById('btnCountBoxOut');
    const btnBimpIn = document.getElementById('btnCountBimpIn');
    const btnBimpOut = document.getElementById('btnCountBimpOut');

    if (btnBoxIn) btnBoxIn.addEventListener('click', () => logInventory('Yarn Carton Box', 'IN'));
    if (btnBoxOut) btnBoxOut.addEventListener('click', () => logInventory('Yarn Carton Box', 'OUT'));
    if (btnBimpIn) btnBimpIn.addEventListener('click', () => logInventory('Rapier Bimp (Beam)', 'IN'));
    if (btnBimpOut) btnBimpOut.addEventListener('click', () => logInventory('Rapier Bimp (Beam)', 'OUT'));
}

async function logInventory(material, direction) {
    const payload = {
        material_type: material,
        direction: direction,
        batch_count: 1,
        notes: `AI Gate count ${direction}`
    };

    try {
        const res = await fetch('/api/module3/record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            showNotification(`Logged ${material} ${direction}! Anti-double-count lock active.`, 'success');
            loadModule3Records();
        } else if (data.status === 'blocked') {
            showNotification('🔒 Double count prevented by Lock System!', 'warning');
        }
    } catch (err) {
        showNotification('Error logging inventory', 'error');
    }
}

async function loadModule3Records() {
    const body = document.getElementById('module3TableBody');
    if (!body) return;

    try {
        const res = await fetch('/api/module3/records');
        const list = await res.json();

        if (list.length === 0) {
            body.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">No inventory material counts yet.</td></tr>';
            return;
        }

        let html = '';
        list.forEach((r, i) => {
            const isIN = r.direction === 'IN';
            html += `
                <tr>
                    <td>${i + 1}</td>
                    <td style="font-family: monospace; color: var(--text-muted);">${r.timestamp}</td>
                    <td style="font-weight: 700; color: #fff;">${escapeHtml(r.material_type)}</td>
                    <td>
                        <span class="status-badge ${isIN ? 'badge-completed' : 'badge-half'}">${r.direction}</span>
                    </td>
                    <td style="font-family: monospace; font-weight: 700; color: var(--accent-cyan);">+${r.batch_count}</td>
                    <td style="font-family: monospace; font-size: 0.72rem; color: #64748b;">${escapeHtml(r.lock_token || 'LOCKED')}</td>
                </tr>
            `;
        });
        body.innerHTML = html;
    } catch (e) {}
}

// ----------------- Toast Notifications -----------------
function showNotification(msg, type = 'info') {
    const toast = document.createElement('div');
    const colors = {
        success: '#10b981',
        error: '#f43f5e',
        warning: '#f59e0b',
        info: '#06b6d4'
    };

    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        background: rgba(17, 24, 39, 0.95);
        color: #fff;
        border-left: 4px solid ${colors[type] || colors.info};
        border-radius: 8px;
        padding: 0.85rem 1.25rem;
        box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        font-size: 0.85rem;
        font-weight: 600;
        z-index: 1000;
        backdrop-filter: blur(8px);
        transform: translateY(20px);
        opacity: 0;
        transition: all 0.25s ease;
    `;
    toast.textContent = msg;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.transform = 'translateY(0)';
        toast.style.opacity = '1';
    }, 10);

    setTimeout(() => {
        toast.style.transform = 'translateY(20px)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ==================== GitHub Pages Showcase Simulator ====================
let simCounting = true;
let simStats = {
    total_staff: 1,
    present_today: 1,
    currently_inside: 1,
    absent_today: 0,
    unknowns_today: 1,
    fps: 29.8,
    source_type: "showcase",
    session_in: 4,
    session_out: 3,
    session_unknown: 1,
    line_ratio: 0.55,
    is_counting: true,
    is_paused: false
};

let simWorkers = [
    { x: 380, y: 140, dir: 1, speed: 2.2, color: '#38bdf8', label: '[TXS-001] Bhavarth Hapani - Software Developer' },
    { x: 590, y: 420, dir: -1, speed: 1.8, color: '#fb7185', label: 'Unknown Visitor [Snapshot Captured]' }
];

function initGitHubSimulator() {
    const canvas = document.getElementById('cameraCanvasSimulator');
    const img = document.getElementById('cameraStream');
    if (img) img.style.display = 'none';
    if (canvas) {
        canvas.style.display = 'block';
        startCanvasSimulation(canvas);
    }

    renderSimStats();
    renderSimEvents();
    renderSimReports();
    renderSimUnknowns();

    // Regular interval to refresh simulated stats
    setInterval(() => {
        if (!simCounting) return;
        renderSimStats();
    }, 500);
}

function startCanvasSimulation(canvas) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    const lineY = h * 0.55;

    function draw() {
        // Dark background
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, w, h);

        // Factory gate doorway
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(160, 60, w - 320, h - 80);
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 4;
        ctx.strokeRect(160, 60, w - 320, h - 80);

        // Header sign
        ctx.fillStyle = '#0b1120';
        ctx.fillRect(260, 20, w - 520, 48);
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(260, 20, w - 520, 48);
        ctx.fillStyle = '#38bdf8';
        ctx.font = 'bold 15px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('TEXTILE MILL - MAIN ENTRANCE GATE [SIMULATOR]', w / 2, 50);

        // Virtual Crossing Gate Line
        ctx.strokeStyle = simCounting ? '#facc15' : '#94a3b8';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(100, lineY);
        ctx.lineTo(w - 100, lineY);
        ctx.stroke();

        ctx.font = 'bold 13px sans-serif';
        ctx.fillStyle = '#facc15';
        ctx.textAlign = 'left';
        ctx.fillText('▲ ENTRANCE / OUTSIDE', 110, lineY - 10);
        ctx.fillStyle = '#34d399';
        ctx.fillText('▼ OFFICE / MILL INTERIOR', 110, lineY + 22);

        if (simCounting) {
            // Update and draw moving workers
            simWorkers.forEach((p, idx) => {
                p.y += p.dir * p.speed;
                if (p.dir > 0 && p.y > h - 130) {
                    p.dir = -1;
                    simStats.session_in++;
                    simStats.present_today = 1;
                    simStats.currently_inside = 1;
                    addSimEvent(p.label, 'in');
                } else if (p.dir < 0 && p.y < 120) {
                    p.dir = 1;
                    simStats.session_out++;
                    simStats.currently_inside = 0;
                    addSimEvent(p.label, 'out');
                }

                // Draw person avatar
                const pw = 120;
                const ph = 180;
                const px = p.x - pw / 2;
                const py = p.y - 40;

                // Head
                ctx.fillStyle = '#fde047';
                ctx.beginPath();
                ctx.arc(p.x, py + 25, 20, 0, Math.PI * 2);
                ctx.fill();

                // Body
                ctx.fillStyle = p.color;
                ctx.fillRect(p.x - 24, py + 48, 48, 65);

                // Legs
                ctx.fillStyle = '#334155';
                ctx.fillRect(p.x - 20, py + 113, 16, 50);
                ctx.fillRect(p.x + 4, py + 113, 16, 50);

                // AI Detection Bounding Box
                ctx.strokeStyle = (idx === 0) ? '#22c55e' : '#f59e0b';
                ctx.lineWidth = 2.5;
                ctx.strokeRect(px, py, pw, ph);

                // Label tag
                ctx.fillStyle = (idx === 0) ? '#22c55e' : '#f59e0b';
                ctx.fillRect(px, py - 24, pw + 120, 24);
                ctx.fillStyle = '#000';
                ctx.font = 'bold 12px sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText(p.label, px + 6, py - 7);
            });
        } else {
            // Paused banner
            ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
            ctx.fillRect(0, 0, w, h);
            ctx.fillStyle = '#f43f5e';
            ctx.font = 'bold 22px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('⏸️ CAMERA & AI COUNTING STOPPED', w / 2, h / 2 - 10);
            ctx.fillStyle = '#94a3b8';
            ctx.font = '14px sans-serif';
            ctx.fillText('Click [Start Camera & Live Counting] below to resume live tracking.', w / 2, h / 2 + 25);
        }

        requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
}

function renderSimStats() {
    const elTotal = document.getElementById('kpiTotalStaff');
    const elPresent = document.getElementById('kpiPresentToday');
    const elInside = document.getElementById('kpiCurrentlyInside');
    const elAbsent = document.getElementById('kpiAbsentToday');
    const elUnknowns = document.getElementById('kpiUnknownsToday');
    const elFps = document.getElementById('liveFps');
    const elSource = document.getElementById('sourceStatusText');

    if (elTotal) elTotal.textContent = simStats.total_staff;
    if (elPresent) elPresent.textContent = simStats.present_today;
    if (elInside) elInside.textContent = simStats.currently_inside;
    if (elAbsent) elAbsent.textContent = simStats.absent_today;
    if (elUnknowns) elUnknowns.textContent = simStats.unknowns_today;
    if (elFps) elFps.textContent = `${simStats.fps} FPS`;
    if (elSource) elSource.textContent = `Source: CLOUD SHOWCASE | Line: 55%`;
}

let simRecentEvents = [
    { type: 'staff', name: 'Bhavarth Hapani (Software Developer)', direction: 'IN', time: '17:31:33', detail: 'Checked IN at 17:31:33. Work timer started.' },
    { type: 'staff', name: 'Bhavarth Hapani (Software Developer)', direction: 'OUT', time: '17:28:47', detail: 'Checked OUT at 17:28:47. Work timer stopped.' },
    { type: 'unknown', name: 'Unknown Visitor', direction: 'IN', time: '17:25:24', detail: 'High-Res snapshot captured & logged to 2026-10-28 folder.' }
];

function addSimEvent(name, dir) {
    const timeStr = new Date().toLocaleTimeString();
    const isStaff = name.includes('Bhavarth');
    simRecentEvents.unshift({
        type: isStaff ? 'staff' : 'unknown',
        name: isStaff ? 'Bhavarth Hapani (Software Developer)' : 'Unknown Visitor',
        direction: dir.toUpperCase(),
        time: timeStr,
        detail: isStaff ? `Checked ${dir.toUpperCase()} at ${timeStr}.` : `High-Res snapshot captured & logged.`
    });
    if (simRecentEvents.length > 8) simRecentEvents.pop();
    renderSimEvents();
}

function renderSimEvents() {
    const container = document.getElementById('recentEventsList');
    if (!container) return;
    container.innerHTML = simRecentEvents.map(e => `
        <div class="feed-item ${e.type === 'staff' ? (e.direction === 'IN' ? 'in-event' : 'out-event') : 'unknown-event'}">
            <div class="feed-content">
                <div class="feed-top">
                    <span class="feed-name">${escapeHtml(e.name)}</span>
                    <span class="feed-time">${e.time}</span>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; margin: 3px 0;">
                    <span style="background: ${e.direction === 'IN' ? '#10b981' : '#f59e0b'}; color: #fff; font-size: 0.65rem; font-weight: 700; padding: 1px 6px; border-radius: 4px;">
                        GATE ${e.direction}
                    </span>
                    <span style="font-size: 0.72rem; color: #cbd5e1; font-family: monospace;">TXS-001</span>
                </div>
                <p class="feed-msg">${escapeHtml(e.detail)}</p>
            </div>
        </div>
    `).join('');
}

function renderSimReports() {
    const tbody = document.getElementById('attendanceTableBody');
    if (!tbody) return;
    tbody.innerHTML = `
        <tr>
            <td style="font-weight: 600; color: var(--text-muted);">1</td>
            <td>
                <div style="width: 38px; height: 38px; border-radius: 8px; background: #1e293b; display: flex; align-items: center; justify-content: center; font-size: 1.1rem;">👨‍💻</div>
            </td>
            <td style="font-family: monospace; font-weight: 700; color: var(--accent-cyan);">TXS-001</td>
            <td style="font-weight: 700; color: #fff;">Bhavarth Hapani</td>
            <td style="color: #cbd5e1;">Software Developer</td>
            <td style="font-family: monospace; font-weight: 600; color: #94a3b8;">${new Date().toISOString().split('T')[0]}</td>
            <td>
                <div style="display: flex; gap: 4px; font-family: monospace; font-size: 0.72rem;">
                    <span style="background: rgba(16,185,129,0.2); color: #34d399; padding: 1px 5px; border-radius: 3px; font-weight: 700;">IN: 4</span>
                    <span style="background: rgba(245,158,11,0.2); color: #fbbf24; padding: 1px 5px; border-radius: 3px; font-weight: 700;">OUT: 3</span>
                </div>
            </td>
            <td style="font-family: monospace; color: #34d399; font-weight: 600;">09:15 AM</td>
            <td style="font-family: monospace; color: #fbbf24; font-weight: 600;">05:30 PM</td>
            <td style="font-weight: 700; font-family: monospace; color: #e2e8f0;">8 hrs 15 mins</td>
            <td><span class="status-badge badge-active">Inside Office</span></td>
        </tr>
    `;
}

function renderSimUnknowns() {
    const grid = document.getElementById('unknownsGalleryGrid');
    if (!grid) return;
    const samplePortraitSvg = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400"><rect width="400" height="400" fill="%231e293b"/><circle cx="200" cy="160" r="70" fill="%23f59e0b"/><rect x="110" y="240" width="180" height="140" rx="30" fill="%2338bdf8"/><text x="200" y="320" fill="%23ffffff" font-size="18" text-anchor="middle" font-family="sans-serif">Visitor 4K Snapshot</text></svg>';

    grid.innerHTML = `
        <div class="snapshot-card" onclick="openImageLightbox('${samplePortraitSvg}', '2026-10-28 17:25:24', 101, '${samplePortraitSvg}')">
            <div style="position: relative;">
                <img src="${samplePortraitSvg}" class="snapshot-img" alt="Captured Visitor" />
                <span style="position: absolute; top: 8px; right: 8px; background: rgba(244,63,94,0.9); color: #fff; font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 4px;">4K CAPTURE</span>
            </div>
            <div class="snapshot-footer">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; font-size: 0.85rem; color: #fff;">Visitor #101</span>
                    <span style="font-size: 0.72rem; color: #94a3b8;">17:25:24</span>
                </div>
                <div style="display: flex; gap: 0.4rem; margin-top: 0.5rem;">
                    <button class="btn btn-secondary" style="flex: 1; font-size: 0.72rem; padding: 0.3rem 0.5rem;">🔍 Full View</button>
                    <button class="btn btn-primary" style="flex: 1; font-size: 0.72rem; padding: 0.3rem 0.5rem;">➕ Add Staff</button>
                </div>
            </div>
        </div>
    `;
}
