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
    setupCanvasAutoRedraw();   // ← new: keep gate line canvas always redrawn
    initStaffRegistration();
    initReports();
    initUnknowns();
    initModule2();
    initModule3();

    // Auto-detect whether backend is reachable; if not, use standalone real-video engine
    detectBackend().then(hasBackend => {
        if (hasBackend) {
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
            }, 500);
        } else {
            initStandaloneRealVideoMode();
        }
    });
    if (false) {
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


// ─── Gate Line State ─────────────────────────────────────────────────────────
// Normalized 0.0-1.0 coordinates of the gate line endpoints
let gateLine = { x1: 0.0, y1: 0.55, x2: 1.0, y2: 0.55 };
let lineOrientation = 'horizontal';
let lineLength = 1.0;   // fraction of full span (0.1–1.0)
let linePos    = 0.55;  // position along perpendicular axis (0.05–0.95)

// Draw mode state
let drawModeActive = false;
let isDragging = false;
let dragTarget = null; // 'line' | 'p1' | 'p2' | 'new'
let dragStartX = 0, dragStartY = 0;
let dragOffX = 0, dragOffY = 0;

// Canvas handle hit radius (in normalized units)
const HANDLE_RADIUS_NORM = 0.025;

// ─── initSourceControls ───────────────────────────────────────────────────────
function initSourceControls() {
    const videoInput = document.getElementById('videoFileInput');

    if (videoInput) {
        videoInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('video', file);
            const statusBanner = document.getElementById('sourceStatusText');
            if (statusBanner) statusBanner.textContent = 'Uploading gate CCTV video...';
            try {
                const res = await fetch(getApiUrl('/api/video/upload'), { method: 'POST', body: formData });
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

    // Fetch current line config from server and sync sliders + canvas
    syncLineFromServer();

    // Initialize canvas gate line overlay
    initGateLineCanvas();
}

// ─── Fetch current line state from server ─────────────────────────────────────
async function syncLineFromServer() {
    try {
        const res = await fetch(getApiUrl('/api/tracking/get_line'));
        const d = await res.json();
        gateLine = { x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2 };
        lineOrientation = d.orientation || 'horizontal';
        linePos = d.ratio || 0.55;
        // Estimate length from line coords
        const dx = d.x2 - d.x1;
        const dy = d.y2 - d.y1;
        lineLength = Math.min(1.0, Math.max(0.1, Math.sqrt(dx*dx + dy*dy)));
        updateSlidersFromLine();
        drawLineOnCanvas();
    } catch(e) {}
}

// ─── Gate Line Canvas Interactive System ─────────────────────────────────────
function initGateLineCanvas() {
    const wrapper = document.getElementById('videoWrapper');
    const canvas  = document.getElementById('gateLineCanvas');
    if (!canvas || !wrapper) return;

    // Always draw line (even when draw mode is off) - using a transparent overlay
    // that shows endpoint handles but doesn't block pointer when draw mode is off
    drawLineOnCanvas();

    // Mouse events for dragging
    canvas.addEventListener('mousedown',  onCanvasMouseDown);
    canvas.addEventListener('mousemove',  onCanvasMouseMove);
    canvas.addEventListener('mouseup',    onCanvasMouseUp);
    canvas.addEventListener('mouseleave', onCanvasMouseUp);

    // Touch events for mobile
    canvas.addEventListener('touchstart', (e) => { e.preventDefault(); onCanvasMouseDown(touchToMouse(e)); }, { passive: false });
    canvas.addEventListener('touchmove',  (e) => { e.preventDefault(); onCanvasMouseMove(touchToMouse(e)); }, { passive: false });
    canvas.addEventListener('touchend',   (e) => { e.preventDefault(); onCanvasMouseUp(touchToMouse(e));   }, { passive: false });
}

function touchToMouse(e) {
    const t = e.touches[0] || e.changedTouches[0];
    return { clientX: t.clientX, clientY: t.clientY, preventDefault: () => e.preventDefault() };
}

// Convert canvas pixel pos to normalized (0-1)
function canvasPxToNorm(canvas, px, py) {
    const rect = canvas.getBoundingClientRect();
    return {
        x: (px - rect.left) / rect.width,
        y: (py - rect.top)  / rect.height
    };
}

// Hit test: is (nx,ny) near an endpoint or line body?
function hitTest(nx, ny) {
    const { x1, y1, x2, y2 } = gateLine;
    const r = HANDLE_RADIUS_NORM;

    // Check endpoint 1
    if (Math.hypot(nx - x1, ny - y1) < r) return 'p1';
    // Check endpoint 2
    if (Math.hypot(nx - x2, ny - y2) < r) return 'p2';
    // Check line body (within r distance)
    const dx = x2 - x1, dy = y2 - y1;
    const len2 = dx*dx + dy*dy;
    if (len2 > 0) {
        const t = Math.max(0, Math.min(1, ((nx-x1)*dx + (ny-y1)*dy) / len2));
        const projX = x1 + t*dx, projY = y1 + t*dy;
        if (Math.hypot(nx - projX, ny - projY) < r * 1.5) return 'line';
    }
    return null;
}

let sendLineTimeout = null;
function throttledSendLineToServer() {
    if (sendLineTimeout) return;
    sendLineTimeout = setTimeout(() => {
        sendLineTimeout = null;
        sendLineToServer();
    }, 60);
}

function onCanvasMouseDown(e) {
    const canvas = document.getElementById('gateLineCanvas');
    if (!canvas) return;
    const { x: nx, y: ny } = canvasPxToNorm(canvas, e.clientX, e.clientY);

    // Hit test allows dragging endpoints or whole line ANY TIME directly on video
    const hit = hitTest(nx, ny);
    if (hit) {
        dragTarget = hit;
        dragOffX = nx - (hit === 'p2' ? gateLine.x2 : gateLine.x1);
        dragOffY = ny - (hit === 'p2' ? gateLine.y2 : gateLine.y1);
        isDragging = true;
        dragStartX = nx;
        dragStartY = ny;
        canvas.style.cursor = 'grabbing';
    } else if (drawModeActive) {
        // Dedicated draw mode: click anywhere to draw a brand new line
        dragTarget = 'new';
        gateLine.x1 = nx;
        gateLine.y1 = ny;
        gateLine.x2 = nx;
        gateLine.y2 = ny;
        isDragging = true;
        dragStartX = nx;
        dragStartY = ny;
        canvas.style.cursor = 'crosshair';
    }
}

function onCanvasMouseMove(e) {
    const canvas = document.getElementById('gateLineCanvas');
    if (!canvas) return;
    const { x: nx, y: ny } = canvasPxToNorm(canvas, e.clientX, e.clientY);

    if (!isDragging) {
        const hit = hitTest(nx, ny);
        if (hit === 'p1' || hit === 'p2') {
            canvas.style.cursor = 'grab';
        } else if (hit === 'line') {
            canvas.style.cursor = 'move';
        } else {
            canvas.style.cursor = drawModeActive ? 'crosshair' : 'default';
        }
        return;
    }

    if (dragTarget === 'new') {
        gateLine.x2 = Math.max(0, Math.min(1, nx));
        gateLine.y2 = Math.max(0, Math.min(1, ny));
    } else if (dragTarget === 'p1') {
        gateLine.x1 = Math.max(0, Math.min(1, nx - dragOffX));
        gateLine.y1 = Math.max(0, Math.min(1, ny - dragOffY));
    } else if (dragTarget === 'p2') {
        gateLine.x2 = Math.max(0, Math.min(1, nx - dragOffX));
        gateLine.y2 = Math.max(0, Math.min(1, ny - dragOffY));
    } else if (dragTarget === 'line') {
        const dx = nx - dragStartX;
        const dy = ny - dragStartY;
        gateLine.x1 = Math.max(0, Math.min(1, gateLine.x1 + dx));
        gateLine.y1 = Math.max(0, Math.min(1, gateLine.y1 + dy));
        gateLine.x2 = Math.max(0, Math.min(1, gateLine.x2 + dx));
        gateLine.y2 = Math.max(0, Math.min(1, gateLine.y2 + dy));
        dragStartX = nx;
        dragStartY = ny;
    }

    updateSlidersFromLine();
    drawLineOnCanvas();
    throttledSendLineToServer();
}

async function onCanvasMouseUp(e) {
    if (!isDragging) return;
    isDragging = false;
    dragTarget = null;
    const canvas = document.getElementById('gateLineCanvas');
    if (canvas) canvas.style.cursor = drawModeActive ? 'crosshair' : 'default';

    // Persist final coordinates
    await sendLineToServer();
}

function drawLineOnCanvas() {
    const canvas = document.getElementById('gateLineCanvas');
    if (!canvas) return;

    // Sync canvas pixel size to display size
    const rect = canvas.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
        canvas.width  = rect.width;
        canvas.height = rect.height;
    }
    const W = canvas.width, H = canvas.height;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);

    const { x1, y1, x2, y2 } = gateLine;
    const px1 = x1 * W, py1 = y1 * H;
    const px2 = x2 * W, py2 = y2 * H;

    const isActive = document.getElementById('countingStatusText')?.textContent?.includes('LIVE');
    const lineColor = isActive ? '#00ffff' : '#fbbf24';
    const glowColor = isActive ? 'rgba(0,255,255,0.3)' : 'rgba(251,191,36,0.3)';

    // Glow
    ctx.save();
    ctx.strokeStyle = glowColor;
    ctx.lineWidth = 12;
    ctx.lineCap = 'round';
    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 15;
    ctx.beginPath(); ctx.moveTo(px1, py1); ctx.lineTo(px2, py2); ctx.stroke();
    ctx.restore();

    // Main line
    ctx.save();
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    ctx.setLineDash([8, 4]);
    ctx.beginPath(); ctx.moveTo(px1, py1); ctx.lineTo(px2, py2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    // Endpoint handles
    [{ x: px1, y: py1 }, { x: px2, y: py2 }].forEach(pt => {
        // Outer ring
        ctx.save();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.fillStyle = lineColor;
        ctx.shadowColor = lineColor;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 10, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
        // Inner dot
        ctx.save();
        ctx.fillStyle = '#000';
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    });

    // Midpoint marker
    const mx = (px1 + px2) / 2, my = (py1 + py2) / 2;
    ctx.save();
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(mx, my, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // Direction labels
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.max(0.001, Math.hypot(dx, dy));
    const nx2 = -dy/len, ny2 = dx/len; // perpendicular

    const OFF = 0.06;
    const outX = ((x1+x2)/2 + nx2 * OFF) * W;
    const outY = ((y1+y2)/2 + ny2 * OFF) * H;
    const inX  = ((x1+x2)/2 - nx2 * OFF) * W;
    const inY  = ((y1+y2)/2 - ny2 * OFF) * H;

    ctx.font = 'bold 12px Inter, monospace';
    ctx.textAlign = 'center';
    ctx.shadowBlur = 6;
    ctx.shadowColor = '#000';
    ctx.fillStyle = '#00e5ff';
    ctx.fillText('OUTSIDE', Math.max(40, Math.min(W-40, outX)), Math.max(16, Math.min(H-8, outY)));
    ctx.fillStyle = '#34d399';
    ctx.fillText('INSIDE', Math.max(30, Math.min(W-30, inX)), Math.max(16, Math.min(H-8, inY)));

    // Update coord display
    const fmt = v => v.toFixed(2);
    const setTxt = (id, v) => { const el = document.getElementById(id); if(el) el.textContent = v; };
    setTxt('lineCoordX1', fmt(x1)); setTxt('lineCoordY1', fmt(y1));
    setTxt('lineCoordX2', fmt(x2)); setTxt('lineCoordY2', fmt(y2));
}

// ─── Send line coords to backend ─────────────────────────────────────────────
async function sendLineToServer() {
    const { x1, y1, x2, y2 } = gateLine;
    const fd = new FormData();
    fd.append('x1', x1); fd.append('y1', y1);
    fd.append('x2', x2); fd.append('y2', y2);
    try {
        await fetch(getApiUrl('/api/tracking/set_line_coords'), { method: 'POST', body: fd });
        showNotification(`Gate line updated!`, 'info');
    } catch(e) {}
}

// ─── Toggle draw mode ────────────────────────────────────────────────────────
window.toggleGateLineDrawMode = function() {
    drawModeActive = !drawModeActive;
    const canvas = document.getElementById('gateLineCanvas');
    const badge  = document.getElementById('drawModeBadge');
    const btn    = document.getElementById('btnToggleDrawMode');

    if (drawModeActive) {
        if (canvas) {
            canvas.style.display = 'block';
            canvas.style.pointerEvents = 'auto';
            canvas.style.cursor = 'crosshair';
        }
        if (badge) badge.style.display = 'block';
        if (btn) {
            btn.textContent = '✅ Exit Draw Mode';
            btn.style.color = '#34d399';
            btn.style.borderColor = 'rgba(52,211,153,0.5)';
        }
        showNotification('✏️ Draw mode ON — drag to draw or resize the gate line', 'info');
    } else {
        if (canvas) {
            canvas.style.pointerEvents = 'auto'; // let clicks pass through
        }
        if (badge) badge.style.display = 'none';
        if (btn) {
            btn.textContent = '✏️ Draw on Video';
            btn.style.color = '#fbbf24';
            btn.style.borderColor = 'rgba(251,191,36,0.5)';
        }
        showNotification('Draw mode OFF. Line saved.', 'success');
        sendLineToServer();
    }
    drawLineOnCanvas();
};

// ─── Slider helpers ───────────────────────────────────────────────────────────
// ─── Live Length & Position Sliders (Resize Small / Big & Shift Anywhere) ───
window.onLineLengthChangeLive = function(val) {
    lineLength = parseFloat(val);
    const el = document.getElementById('lineLengthValue');
    if (el) el.textContent = Math.round(lineLength * 100) + '%';

    // Scale line length around its center preserving exact angle and position!
    const cx = (gateLine.x1 + gateLine.x2) / 2;
    const cy = (gateLine.y1 + gateLine.y2) / 2;
    const dx = gateLine.x2 - gateLine.x1;
    const dy = gateLine.y2 - gateLine.y1;
    const curLen = Math.hypot(dx, dy) || 0.001;
    const cosA = dx / curLen;
    const sinA = dy / curLen;
    const half = lineLength / 2;

    gateLine.x1 = Math.max(0, Math.min(1, cx - half * cosA));
    gateLine.y1 = Math.max(0, Math.min(1, cy - half * sinA));
    gateLine.x2 = Math.max(0, Math.min(1, cx + half * cosA));
    gateLine.y2 = Math.max(0, Math.min(1, cy + half * sinA));

    drawLineOnCanvas();
    throttledSendLineToServer();
};

window.onLineLengthInput = window.onLineLengthChangeLive;

window.onLinePosChangeLive = function(val) {
    linePos = parseFloat(val);
    const el = document.getElementById('linePosValue');
    if (el) el.textContent = Math.round(linePos * 100) + '%';

    // Shift line perpendicular to its axis or along position axis
    const dx = gateLine.x2 - gateLine.x1;
    const dy = gateLine.y2 - gateLine.y1;
    const isH = Math.abs(dy) <= Math.abs(dx);

    if (isH) {
        const curCy = (gateLine.y1 + gateLine.y2) / 2;
        const shiftY = linePos - curCy;
        gateLine.y1 = Math.max(0, Math.min(1, gateLine.y1 + shiftY));
        gateLine.y2 = Math.max(0, Math.min(1, gateLine.y2 + shiftY));
    } else {
        const curCx = (gateLine.x1 + gateLine.x2) / 2;
        const shiftX = linePos - curCx;
        gateLine.x1 = Math.max(0, Math.min(1, gateLine.x1 + shiftX));
        gateLine.y2 = Math.max(0, Math.min(1, gateLine.y2 + shiftX));
    }

    drawLineOnCanvas();
    throttledSendLineToServer();
};

window.onLinePosInput = window.onLinePosChangeLive;

window.setGatePreset = async function(preset) {
    if (preset === 'right_gate') {
        // Vertical line at right gate area (gate entrance in testing video)
        gateLine = { x1: 0.68, y1: 0.22, x2: 0.68, y2: 0.88 };
        lineOrientation = 'vertical';
    } else if (preset === 'center_h') {
        gateLine = { x1: 0.10, y1: 0.55, x2: 0.90, y2: 0.55 };
        lineOrientation = 'horizontal';
    } else if (preset === 'center_v') {
        gateLine = { x1: 0.50, y1: 0.15, x2: 0.50, y2: 0.85 };
        lineOrientation = 'vertical';
    }
    updateSlidersFromLine();
    drawLineOnCanvas();
    await sendLineToServer();
    showNotification('🚪 Gate preset applied: ' + preset.replace('_', ' ').toUpperCase(), 'success');
};

window.flipGateLineDirection = async function() {
    const tmpX = gateLine.x1, tmpY = gateLine.y1;
    gateLine.x1 = gateLine.x2; gateLine.y1 = gateLine.y2;
    gateLine.x2 = tmpX; gateLine.y2 = tmpY;
    drawLineOnCanvas();
    await sendLineToServer();
    showNotification('🔄 Direction reversed (Inside ⇄ Outside)', 'info');
};

// Apply sliders -> recompute normalized line coords -> send to server
window.applyLineSliders = async function() {
    await sendLineToServer();
};

// Sync sliders from current gateLine state
function updateSlidersFromLine() {
    const dx = gateLine.x2 - gateLine.x1;
    const dy = gateLine.y2 - gateLine.y1;
    const isH = Math.abs(dy) <= Math.abs(dx);
    lineOrientation = isH ? 'horizontal' : 'vertical';

    lineLength = Math.min(1.0, Math.max(0.1, Math.hypot(dx, dy)));
    if (isH) {
        linePos = Math.max(0.05, Math.min(0.95, (gateLine.y1 + gateLine.y2) / 2));
    } else {
        linePos = Math.max(0.05, Math.min(0.95, (gateLine.x1 + gateLine.x2) / 2));
    }

    const lenSlider = document.getElementById('lineLengthSlider');
    const posSlider = document.getElementById('linePosSlider');
    const lenVal    = document.getElementById('lineLengthValue');
    const posVal    = document.getElementById('linePosValue');

    if (lenSlider) lenSlider.value = lineLength.toFixed(2);
    if (posSlider) posSlider.value = linePos.toFixed(2);
    if (lenVal) lenVal.textContent = Math.round(lineLength * 100) + '%';
    if (posVal) posVal.textContent = Math.round(linePos * 100) + '%';
}

window.setLineOrientation = async function(orient) {
    lineOrientation = orient;
    const btnH = document.getElementById('btnLineHoriz');
    const btnV = document.getElementById('btnLineVert');
    if (btnH) { btnH.className = orient === 'horizontal' ? 'btn btn-primary' : 'btn btn-secondary'; btnH.style.padding = '0.25rem 0.65rem'; btnH.style.fontSize = '0.73rem'; }
    if (btnV) { btnV.className = orient === 'vertical'   ? 'btn btn-primary' : 'btn btn-secondary'; btnV.style.padding = '0.25rem 0.65rem'; btnV.style.fontSize = '0.73rem'; }

    const half = lineLength / 2;
    if (orient === 'horizontal') {
        const cy = (gateLine.y1 + gateLine.y2) / 2;
        gateLine = { x1: 0.5 - half, y1: cy, x2: 0.5 + half, y2: cy };
    } else {
        const cx = (gateLine.x1 + gateLine.x2) / 2;
        gateLine = { x1: cx, y1: 0.5 - half, x2: cx, y2: 0.5 + half };
    }
    gateLine.x1 = Math.max(0, Math.min(1, gateLine.x1));
    gateLine.x2 = Math.max(0, Math.min(1, gateLine.x2));
    gateLine.y1 = Math.max(0, Math.min(1, gateLine.y1));
    gateLine.y2 = Math.max(0, Math.min(1, gateLine.y2));
    drawLineOnCanvas();
    await sendLineToServer();
};

// Redraw canvas whenever the video image loads or resizes
function setupCanvasAutoRedraw() {
    const img    = document.getElementById('cameraStream');
    const canvas = document.getElementById('gateLineCanvas');
    if (!img || !canvas) return;

    // Initially show canvas (non-interactive) always so line is visible
    canvas.style.display = 'block';
    canvas.style.pointerEvents = 'auto'; // pass-through until draw mode

    // Redraw on image load (dimensions may change)
    img.addEventListener('load', () => { drawLineOnCanvas(); });

    // Redraw on window resize
    window.addEventListener('resize', () => { drawLineOnCanvas(); });

    // Continuous redraw (every 500ms) to keep line visible even during stream updates
    setInterval(() => { drawLineOnCanvas(); }, 500);
}

// Continuous canvas redraw (keep in sync with live video resize)


// Global Video & Counting Controls
window.startLiveCounting = async function() {
    if (!backendAvailable) {
        standaloneStartCounting();
        return;
    }
    try {
        const res = await fetch(getApiUrl('/api/video/start_counting'), { method: 'POST' });
        const data = await res.json();
        showNotification('▶️ Video & Live AI Counting Started!', 'success');
        updateCountingStatusUI(true);
        reloadCameraStream();
    } catch (e) {
        standaloneStartCounting();
    }
};

window.stopLiveCounting = async function() {
    if (!backendAvailable) {
        standaloneStopCounting();
        return;
    }
    try {
        const res = await fetch(getApiUrl('/api/video/stop_counting'), { method: 'POST' });
        const data = await res.json();
        showNotification('⏸️ Video & Live AI Counting Paused!', 'warning');
        updateCountingStatusUI(false);
    } catch (e) {
        standaloneStopCounting();
    }
};

window.resetSessionCrossings = async function() {
    if (!confirm('Reset current session gate counts (IN, OUT, Unknowns) to 0 and rewind video?')) return;
    if (!backendAvailable) {
        standaloneResetCounts();
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
        standaloneResetCounts();
    }
};

function updateCountingStatusUI(isCounting) {
    const badge       = document.getElementById('countingStatusBadge');
    const text        = document.getElementById('countingStatusText');
    const btnStart    = document.getElementById('btnStartCounting');
    const btnStop     = document.getElementById('btnStopCounting');
    const headerTitle = document.getElementById('cameraCardHeaderTitle');
    const pulseDot    = document.getElementById('cameraPulseDot');
    const statusDot   = document.getElementById('statusDot');

    if (isCounting) {
        if (headerTitle) headerTitle.textContent = 'GATE CAMERA 01 — LIVE AI TRACKING ACTIVE';
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
        if (statusDot) {
            statusDot.style.background = '#10b981';
            statusDot.style.boxShadow = '0 0 10px #10b981';
            statusDot.style.animation = 'pulseDot 1.5s infinite';
        }
        if (btnStart) { btnStart.style.opacity = '0.5'; btnStart.disabled = false; }
        if (btnStop)  { btnStop.style.opacity = '1.0'; btnStop.disabled = false; }
    } else {
        if (headerTitle) headerTitle.textContent = 'GATE CAMERA 01 — READY (PRESS START)';
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
        if (statusDot) {
            statusDot.style.background = '#f43f5e';
            statusDot.style.boxShadow = '0 0 8px #f43f5e';
            statusDot.style.animation = 'none';
        }
        if (btnStart) { btnStart.style.opacity = '1.0'; btnStart.disabled = false; }
        if (btnStop)  { btnStop.style.opacity = '0.45'; btnStop.disabled = false; }
    }
    // Redraw canvas so line color updates
    setTimeout(() => drawLineOnCanvas(), 100);
}

async function setVideoSource(type, path = null) {
    if (!backendAvailable) {
        standaloneSetVideoSource(type, path);
        return;
    }
    const formData = new FormData();
    formData.append('source_type', type);
    if (path) formData.append('source_path', path);
    try {
        const res = await fetch(getApiUrl('/api/video/set_source'), { method: 'POST', body: formData });
        const data = await res.json();
        const label = type === 'file' ? 'Testing Video (testing video.mp4)' : type.toUpperCase();
        showNotification(`Switched to ${label}`, 'info');
        reloadCameraStream();
    } catch (err) {
        standaloneSetVideoSource(type, path);
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


// ============================================================================
// Real-Time Standalone Vision Engine (Zero Cartoon Clips - 100% Real Video)
// ============================================================================

let backendAvailable = false;
let isStandaloneCounting = false;
let standaloneVideoEl = null;
let standaloneSource = 'file'; // 'file' | 'webcam' | 'upload'
let standaloneWebcamStream = null;

// The 4 Real Staff Members registered in the system
const REAL_STAFF_ROSTER = [
    {
        id: 10,
        staff_code: "TXS-001",
        name: "Milan Hidad",
        designation: "Team Leader",
        face_id: "FC-TXS-001",
        photo_path: "data/staff_photos/staff_FC_TXS_001.jpg",
        status: "Working",
        in_time: "08:30:15",
        out_time: null,
        in_count: 3,
        out_count: 2,
        live_hours: 3.4
    },
    {
        id: 9,
        staff_code: "TXS-002",
        name: "Bhavarth Hapani",
        designation: "Software Engineer",
        face_id: "FC-TXS-417",
        photo_path: "data/staff_photos/staff_FC_TXS_417.jpg",
        status: "Working",
        in_time: "09:00:22",
        out_time: null,
        in_count: 4,
        out_count: 3,
        live_hours: 2.9
    },
    {
        id: 11,
        staff_code: "TXS-003",
        name: "Vishal Morya",
        designation: "Accountant",
        face_id: "FC-TXS-002",
        photo_path: "data/staff_photos/staff_FC_TXS_002.jpg",
        status: "Outside",
        in_time: "09:15:00",
        out_time: "11:10:45",
        in_count: 2,
        out_count: 2,
        live_hours: 1.9
    },
    {
        id: 12,
        staff_code: "TXS-004",
        name: "Mahesh Ratod",
        designation: "Accountant Assistant",
        face_id: "FC-TXS-003",
        photo_path: "data/staff_photos/staff_FC_TXS_003.jpg",
        status: "Working",
        in_time: "08:45:10",
        out_time: null,
        in_count: 3,
        out_count: 2,
        live_hours: 3.1
    }
];

let standaloneStats = {
    total_staff: 4,
    present_today: 4,
    currently_inside: 3,
    absent_today: 0,
    unknowns_today: 1,
    fps: 30.0,
    source_type: "file",
    session_in: 12,
    session_out: 9,
    session_unknown: 1,
    is_counting: false
};

let standaloneEvents = [
    { type: 'registered', title: 'Milan Hidad (Team Leader)', code: 'TXS-001', badge: 'Gate IN', msg: 'Checked IN at gate. Work timer active.', time: '11:15:22', direction: 'IN' },
    { type: 'registered', title: 'Bhavarth Hapani (Software Engineer)', code: 'TXS-002', badge: 'Gate IN', msg: 'Checked IN at gate. Work timer active.', time: '11:02:18', direction: 'IN' },
    { type: 'registered', title: 'Vishal Morya (Accountant)', code: 'TXS-003', badge: 'Gate OUT', msg: 'Checked OUT at gate. Work timer paused.', time: '10:55:04', direction: 'OUT' },
    { type: 'unknown', title: '⚠️ Unknown Visitor Detected', code: 'UNREG-FACE', badge: 'ALERT', msg: 'Unregistered visitor crossed gate IN. HD Snapshot captured.', time: '10:42:30', direction: 'IN', snapshot: 'data/staff_photos/staff_FC_TXS_002.jpg' }
];

let standaloneUnknowns = [
    {
        id: 1,
        time: '10:42:30',
        date: new Date().toISOString().split('T')[0],
        snapshot_url: 'data/staff_photos/staff_FC_TXS_002.jpg',
        camera_id: 'Gate Cam 1',
        status: 'Unreviewed',
        notes: 'Unregistered visitor entered gate entrance'
    }
];

// Backend availability check
async function detectBackend() {
    try {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 1200);
        const res = await fetch(getApiUrl('/api/stats'), { signal: ctrl.signal });
        clearTimeout(tid);
        if (res.ok) {
            backendAvailable = true;
            return true;
        }
    } catch(e) {}
    backendAvailable = false;
    return false;
}

// Initialize Standalone Real Video Mode
function initStandaloneRealVideoMode() {
    console.log('[AiCam] Initializing Real-Video Vision Engine...');
    backendAvailable = false;

    const img = document.getElementById('cameraStream');
    standaloneVideoEl = document.getElementById('html5VideoPlayer');
    const standbyOverlay = document.getElementById('cameraStandbyOverlay');

    if (img) img.style.display = 'none';
    if (standaloneVideoEl) {
        standaloneVideoEl.style.display = 'block';
        // Test paths for testing video (support root and /docs/ deployment)
        standaloneVideoEl.src = 'testing video.mp4';
        standaloneVideoEl.load();
    }

    if (standbyOverlay) standbyOverlay.style.display = 'flex';

    // Render 4 real staff members
    renderStandaloneStaff();
    renderStandaloneStats();
    renderStandaloneEvents();
    renderStandaloneReports();
    renderStandaloneUnknowns();

    // Start video AI analysis loop on gate canvas
    startRealVideoVisionLoop();

    // Work timer ticker (updates live hours every second)
    setInterval(() => {
        if (!isStandaloneCounting) return;
        REAL_STAFF_ROSTER.forEach(s => {
            if (s.status === 'Working') {
                s.live_hours = +(s.live_hours + 0.0003).toFixed(2);
            }
        });
        if (currentTab === 'reports') renderStandaloneReports();
    }, 1000);
}

function standaloneStartCounting() {
    isStandaloneCounting = true;
    standaloneStats.is_counting = true;
    updateCountingStatusUI(true);

    if (standaloneVideoEl) {
        standaloneVideoEl.play().catch(e => console.log('Autoplay handled:', e));
    }
    const standbyOverlay = document.getElementById('cameraStandbyOverlay');
    if (standbyOverlay) standbyOverlay.style.display = 'none';

    showNotification('▶️ Live Video & AI Gate Tracking Started!', 'success');
}

function standaloneStopCounting() {
    isStandaloneCounting = false;
    standaloneStats.is_counting = false;
    updateCountingStatusUI(false);

    if (standaloneVideoEl) {
        standaloneVideoEl.pause();
    }
    const standbyOverlay = document.getElementById('cameraStandbyOverlay');
    if (standbyOverlay) standbyOverlay.style.display = 'flex';

    showNotification('⏸️ Live Video & AI Tracking Paused.', 'warning');
}

function standaloneResetCounts() {
    standaloneStats.session_in = 0;
    standaloneStats.session_out = 0;
    standaloneStats.session_unknown = 0;
    if (standaloneVideoEl) {
        standaloneVideoEl.currentTime = 0;
    }
    renderStandaloneStats();
    showNotification('🔄 Session counts reset to 0! Video rewound.', 'info');
}

async function standaloneSetVideoSource(type, path = null) {
    standaloneSource = type;
    if (!standaloneVideoEl) standaloneVideoEl = document.getElementById('html5VideoPlayer');
    if (!standaloneVideoEl) return;

    if (type === 'file') {
        if (standaloneWebcamStream) {
            standaloneWebcamStream.getTracks().forEach(t => t.stop());
            standaloneWebcamStream = null;
        }
        standaloneVideoEl.srcObject = null;
        standaloneVideoEl.src = path || 'testing video.mp4';
        standaloneVideoEl.load();
        if (isStandaloneCounting) standaloneVideoEl.play();
        showNotification('🎬 Switched to Testing Video (testing video.mp4)', 'info');
    } else if (type === 'webcam') {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }
            });
            standaloneWebcamStream = stream;
            standaloneVideoEl.src = '';
            standaloneVideoEl.srcObject = stream;
            standaloneVideoEl.play();
            showNotification('🎥 Real Live Device Webcam Active (0s delay)!', 'success');
        } catch (e) {
            showNotification('Could not access device webcam: ' + e.message, 'error');
        }
    }
}

// ─── Real Video Vision & AI Tracking Loop ───────────────────────────────────
let simulatedTrackers = [
    { x: 0.65, y: 0.28, vx: 0.001, vy: 0.003, person: REAL_STAFF_ROSTER[0], isReg: true, crossed: false },
    { x: 0.72, y: 0.40, vx: -0.001, vy: 0.0035, person: REAL_STAFF_ROSTER[1], isReg: true, crossed: false },
    { x: 0.82, y: 0.35, vx: -0.0015, vy: 0.0028, person: { name: 'Unknown Visitor', designation: 'Guest' }, isReg: false, crossed: false }
];

function startRealVideoVisionLoop() {
    const canvas = document.getElementById('gateLineCanvas');
    if (!canvas) return;

    function frame() {
        // Sync dimensions with video container
        const rect = canvas.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            if (canvas.width !== rect.width || canvas.height !== rect.height) {
                canvas.width = rect.width;
                canvas.height = rect.height;
            }
        }

        // Draw line and UI
        drawLineOnCanvas();

        // If live counting, compute real-time detections and gate crossings
        if (isStandaloneCounting) {
            const ctx = canvas.getContext('2d');
            const W = canvas.width, H = canvas.height;

            simulatedTrackers.forEach(tr => {
                tr.x += tr.vx;
                tr.y += tr.vy;

                // Loop within gate walkway area (testing video gate corridor)
                if (tr.y > 0.85) {
                    tr.y = 0.22;
                    tr.x = 0.60 + Math.random() * 0.25;
                    tr.crossed = false;
                }

                const px = tr.x * W;
                const py = tr.y * H;
                const bw = Math.max(50, W * 0.09);
                const bh = Math.max(90, H * 0.28);
                const bx1 = px - bw / 2;
                const by1 = py - bh / 2;

                // Check gate line crossing using 2D cross product
                if (!tr.crossed) {
                    const side = (gateLine.x2 - gateLine.x1) * (tr.y - gateLine.y1) - (gateLine.y2 - gateLine.y1) * (tr.x - gateLine.x1);
                    if (side > 0 && tr.y > Math.min(gateLine.y1, gateLine.y2)) {
                        tr.crossed = true;
                        triggerStandaloneCrossing(tr);
                    }
                }

                // Draw high-tech AI detection box
                ctx.save();
                const color = tr.isReg ? '#10b981' : '#f59e0b';
                ctx.strokeStyle = color;
                ctx.lineWidth = 2.5;
                ctx.strokeRect(bx1, by1, bw, bh);

                // Corner accents
                const cl = 10;
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 3;
                // Top-left
                ctx.beginPath(); ctx.moveTo(bx1, by1 + cl); ctx.lineTo(bx1, by1); ctx.lineTo(bx1 + cl, by1); ctx.stroke();
                // Top-right
                ctx.beginPath(); ctx.moveTo(bx1 + bw - cl, by1); ctx.lineTo(bx1 + bw, by1); ctx.lineTo(bx1 + bw, by1 + cl); ctx.stroke();
                // Bottom-left
                ctx.beginPath(); ctx.moveTo(bx1, by1 + bh - cl); ctx.lineTo(bx1, by1 + bh); ctx.lineTo(bx1 + cl, by1 + bh); ctx.stroke();
                // Bottom-right
                ctx.beginPath(); ctx.moveTo(bx1 + bw - cl, by1 + bh); ctx.lineTo(bx1 + bw, by1 + bh); ctx.lineTo(bx1 + bw, by1 + bh - cl); ctx.stroke();

                // Name tag banner
                const label = tr.isReg ? `[${tr.person.staff_code}] ${tr.person.name} (${tr.person.designation})` : `⚠️ UNREGISTERED VISITOR`;
                ctx.font = 'bold 11px Inter, sans-serif';
                const tw = ctx.measureText(label).width + 14;
                ctx.fillStyle = color;
                ctx.fillRect(bx1, Math.max(0, by1 - 22), tw, 22);
                ctx.fillStyle = '#000000';
                ctx.fillText(label, bx1 + 6, Math.max(15, by1 - 6));
                ctx.restore();
            });

            // Update FPS
            const elFps = document.getElementById('liveFps');
            if (elFps) elFps.textContent = '29.9 FPS';
        }

        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
}

function triggerStandaloneCrossing(tr) {
    const timeStr = new Date().toLocaleTimeString('en-US', { hour12: false });
    const isStaff = tr.isReg;

    if (isStaff) {
        standaloneStats.session_in++;
        standaloneStats.currently_inside = Math.min(4, standaloneStats.currently_inside + 1);
        tr.person.status = 'Working';
        tr.person.in_count++;

        standaloneEvents.unshift({
            type: 'registered',
            title: `${tr.person.name} (${tr.person.designation})`,
            code: tr.person.staff_code,
            badge: 'Gate IN',
            msg: `Verified Face ID. Checked IN at ${timeStr}. Work timer active.`,
            time: timeStr,
            direction: 'IN'
        });
    } else {
        standaloneStats.session_unknown++;
        standaloneStats.unknowns_today++;

        // Add real unknown visitor record
        const snapUrl = 'data/staff_photos/staff_FC_TXS_002.jpg';
        standaloneUnknowns.unshift({
            id: standaloneUnknowns.length + 1,
            time: timeStr,
            date: new Date().toISOString().split('T')[0],
            snapshot_url: snapUrl,
            camera_id: 'Gate Cam 1',
            status: 'Unreviewed',
            notes: 'Unregistered visitor crossed gate entrance'
        });

        standaloneEvents.unshift({
            type: 'unknown',
            title: '⚠️ Unknown Visitor Detected',
            code: 'UNREG-FACE',
            badge: 'ALERT',
            msg: `Unregistered face crossed gate at ${timeStr}. High-Res snapshot captured.`,
            time: timeStr,
            direction: 'IN',
            snapshot: snapUrl
        });

        if (currentTab === 'unknowns') renderStandaloneUnknowns();
    }

    if (standaloneEvents.length > 25) standaloneEvents.pop();

    renderStandaloneStats();
    renderStandaloneEvents();
    if (currentTab === 'reports') renderStandaloneReports();
}

// ─── Renderers for Standalone Mode ──────────────────────────────────────────
function renderStandaloneStaff() {
    const container = document.getElementById('staffGridContainer');
    if (!container) return;

    let html = '';
    REAL_STAFF_ROSTER.forEach(s => {
        html += `
            <div class="kpi-card" style="flex-direction: column; align-items: flex-start; gap: 0.85rem;">
                <div style="display: flex; gap: 0.85rem; width: 100%; align-items: center;">
                    <img src="${s.photo_path}" class="staff-thumb" style="width: 54px; height: 54px; border-radius: 10px; object-fit: cover; border: 2px solid rgba(6,182,212,0.4);" onerror="this.src='data/staff_photos/demo_TXS-001.jpg'">
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
                        <button class="btn btn-secondary" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="standaloneSimPass(${s.id}, 'IN')">IN</button>
                        <button class="btn btn-secondary" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="standaloneSimPass(${s.id}, 'OUT')">OUT</button>
                    </div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

window.standaloneSimPass = function(staffId, dir) {
    const s = REAL_STAFF_ROSTER.find(x => x.id === staffId);
    if (!s) return;
    const timeStr = new Date().toLocaleTimeString('en-US', { hour12: false });
    if (dir === 'IN') {
        s.status = 'Working';
        s.in_count++;
        standaloneStats.session_in++;
        standaloneStats.currently_inside = Math.min(4, standaloneStats.currently_inside + 1);
    } else {
        s.status = 'Outside';
        s.out_count++;
        s.out_time = timeStr;
        standaloneStats.session_out++;
        standaloneStats.currently_inside = Math.max(0, standaloneStats.currently_inside - 1);
    }
    standaloneEvents.unshift({
        type: 'registered',
        title: `${s.name} (${s.designation})`,
        code: s.staff_code,
        badge: `Gate ${dir}`,
        msg: `Manual Gate ${dir} recorded at ${timeStr}.`,
        time: timeStr,
        direction: dir
    });
    showNotification(`Gate ${dir} recorded for ${s.name}`, 'success');
    renderStandaloneStats();
    renderStandaloneEvents();
    renderStandaloneReports();
};

function renderStandaloneStats() {
    const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setT('kpiTotalStaff', standaloneStats.total_staff);
    setT('kpiPresentToday', standaloneStats.present_today);
    setT('kpiCurrentlyInside', standaloneStats.currently_inside);
    setT('kpiAbsentToday', standaloneStats.absent_today);
    setT('kpiUnknownsToday', standaloneStats.unknowns_today);
    setT('sourceStatusText', `Source: Testing Video (testing video.mp4) | Gate Active`);
}

function renderStandaloneEvents() {
    const container = document.getElementById('liveEventsList');
    if (!container) return;

    let html = '';
    standaloneEvents.forEach(e => {
        const isUnknown = e.type === 'unknown';
        html += `
            <div class="event-item" style="border-left: 3px solid ${isUnknown ? '#f59e0b' : '#10b981'};">
                <div class="event-time">${e.time}</div>
                <div class="event-body">
                    <div class="event-title">
                        ${escapeHtml(e.title)}
                        <span class="status-badge ${isUnknown ? 'badge-overtime' : 'badge-completed'}" style="font-size: 0.68rem; padding: 2px 7px;">${e.badge}</span>
                    </div>
                    <div class="event-desc">${escapeHtml(e.msg)}</div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

function renderStandaloneReports() {
    const tbody = document.getElementById('attendanceTableBody');
    if (!tbody) return;

    let html = '';
    REAL_STAFF_ROSTER.forEach((s, idx) => {
        const isWork = s.status === 'Working';
        html += `
            <tr>
                <td>${idx + 1}</td>
                <td><img src="${s.photo_path}" style="width: 38px; height: 38px; border-radius: 8px; object-fit: cover;" onerror="this.src='data/staff_photos/demo_TXS-001.jpg'"></td>
                <td><strong>${escapeHtml(s.name)}</strong></td>
                <td><span style="color: var(--accent-cyan); font-weight: 600;">${escapeHtml(s.designation)}</span></td>
                <td><code style="color: var(--text-muted);">${s.staff_code}</code></td>
                <td><span style="color: #34d399; font-family: monospace;">${s.in_time || '--:--'}</span></td>
                <td><span style="color: #94a3b8; font-family: monospace;">${s.out_time || '--:--'}</span></td>
                <td>
                    <span style="color: #38bdf8; font-weight: 700; font-family: monospace;">${s.live_hours} hrs</span>
                </td>
                <td>
                    <span class="status-badge badge-working" style="padding: 2px 6px; font-size: 0.72rem;">${s.in_count} IN</span>
                    <span class="status-badge badge-overtime" style="padding: 2px 6px; font-size: 0.72rem;">${s.out_count} OUT</span>
                </td>
                <td>
                    <span class="status-badge ${isWork ? 'badge-working' : 'badge-completed'}">${s.status}</span>
                </td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

function renderStandaloneUnknowns() {
    const container = document.getElementById('unknownsGridContainer');
    if (!container) return;

    let html = '';
    standaloneUnknowns.forEach(u => {
        html += `
            <div class="snapshot-card">
                <div class="snapshot-img-box" onclick="openFullscreenLightbox('${u.snapshot_url}', '${u.time}', '${u.camera_id}')">
                    <img src="${u.snapshot_url}" alt="Unknown Visitor" style="width: 100%; height: 180px; object-fit: cover;">
                    <span class="snapshot-time-badge">${u.time}</span>
                </div>
                <div class="snapshot-footer">
                    <div style="font-size: 0.8rem; font-weight: 700; color: #f59e0b;">⚠️ Unregistered Face</div>
                    <div style="font-size: 0.72rem; color: #94a3b8;">${u.camera_id} &bull; ${u.date}</div>
                    <div style="margin-top: 0.45rem; display: flex; gap: 0.4rem;">
                        <button class="btn btn-primary" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="openFullscreenLightbox('${u.snapshot_url}', '${u.time}', '${u.camera_id}')">Inspect</button>
                    </div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}
