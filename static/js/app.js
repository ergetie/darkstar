let chart;
let timelineItems = new vis.DataSet();
let currentDragAction = null;
let themeCatalog = [];
let currentTheme = null;
let currentAccentIndex = null;
let latestScheduleData = null;
let latestConfigData = null;
let timelineInstance = null;
let nowShowingSource = 'local';
let isRenderingChart = false;

function getCssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function hexToRgba(hex, alpha = 1) {
    const sanitized = hex.replace('#', '');
    const value = sanitized.length === 3
        ? sanitized.split('').map(ch => ch + ch).join('')
        : sanitized;
    const num = parseInt(value, 16);
    const r = (num >> 16) & 255;
    const g = (num >> 8) & 255;
    const b = num & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function getThemeColours() {
    const palette = Array.from({ length: 16 }, (_, idx) => {
        const value = getCssVar(`--ds-palette-${idx}`);
        return value || '#000000';
    });
    return {
        palette,
        foreground: getCssVar('--ds-foreground') || '#ffffff',
        background: getCssVar('--ds-background') || '#000000',
        accent: getCssVar('--ds-accent') || palette[9] || '#ffffff',
        border: getCssVar('--ds-border') || palette[7] || '#ffffff'
    };
}

function setNowShowing(source) {
    nowShowingSource = source === 'server' ? 'server' : 'local';
    const el = document.getElementById('now-showing');
    if (el) {
        el.textContent = `now showing: ${nowShowingSource} plan`;
    }
}

function themeStyleForAction(action) {
    const base = 'color: var(--ds-background); border: none;';
    switch (action) {
        case 'Charge':
            return `${base} background-color: var(--ds-palette-0);`;
        case 'Water Heating':
            return `${base} background-color: var(--ds-palette-1);`;
        case 'Export':
            return `${base} background-color: var(--ds-palette-2);`;
        case 'Hold':
            return `${base} background-color: var(--ds-palette-3);`;
        default:
            return '';
    }
}

function applyThemeVariables(theme, accentIndex) {
    if (!theme) return;
    const root = document.documentElement;
    root.style.setProperty('--ds-background', theme.background);
    root.style.setProperty('--ds-foreground', theme.foreground);
    theme.palette.forEach((colour, index) => {
        root.style.setProperty(`--ds-palette-${index}`, colour);
    });
    const accent = theme.palette[accentIndex] || theme.palette[9] || theme.palette[1] || theme.foreground;
    const muted = theme.palette[7] || theme.foreground;
    root.style.setProperty('--ds-accent', accent);
    root.style.setProperty('--ds-muted', muted);
    root.style.setProperty('--ds-border', muted);
}

async function persistThemeSelection(themeName, accentIndex) {
    if (!themeName) return;
    try {
        const response = await fetch('/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: themeName, accent_index: accentIndex })
        });
        if (!response.ok) {
            const details = await response.json().catch(() => ({}));
            throw new Error(details.error || `HTTP ${response.status}`);
        }
    } catch (error) {
        console.error('Error persisting theme:', error);
        alert('Failed to save theme selection.');
    }
}

function applyTheme(theme, { persist = false, accentIndex = null } = {}) {
    if (!theme) return;
    currentTheme = theme;
    if (typeof accentIndex === 'number' && accentIndex >= 0 && accentIndex <= 15) {
        currentAccentIndex = accentIndex;
    } else if (currentAccentIndex == null) {
        currentAccentIndex = 9;
    }
    applyThemeVariables(theme, currentAccentIndex);
    const accentSelect = document.getElementById('themeAccentSelect');
    if (accentSelect) {
        accentSelect.value = String(currentAccentIndex);
    }
    const accentInput = document.getElementById('themeAccentInput');
    if (accentInput) {
        accentInput.value = String(currentAccentIndex);
    }
    if (persist) {
        persistThemeSelection(theme.name, currentAccentIndex);
    }
    if (latestScheduleData && latestConfigData) {
        renderChart(latestScheduleData, latestConfigData);
    }
}

async function loadThemes() {
    const select = document.getElementById('themeSelect');
    const accentSelect = document.getElementById('themeAccentSelect');
    const accentInput = document.getElementById('themeAccentInput');
    if (!select) return;
    try {
        const response = await fetch('/api/themes');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        themeCatalog = data.themes || [];
        select.innerHTML = '';
        if (accentSelect && !accentSelect.dataset.initialised) {
            accentSelect.innerHTML = '';
            for (let i = 0; i < 16; i += 1) {
                const option = document.createElement('option');
                option.value = String(i);
                option.textContent = `Palette ${i}`;
                accentSelect.appendChild(option);
            }
            accentSelect.dataset.initialised = 'true';
        }
        themeCatalog.forEach(theme => {
            const option = document.createElement('option');
            option.value = theme.name;
            option.textContent = theme.name;
            select.appendChild(option);
        });
        const current = themeCatalog.find(t => t.name === data.current) || themeCatalog[0];
        currentAccentIndex = typeof data.accent_index === 'number' ? data.accent_index : 9;
        if (accentSelect) {
            accentSelect.value = String(currentAccentIndex);
        }
        if (accentInput) {
            accentInput.value = String(currentAccentIndex);
        }
        if (current) {
            select.value = current.name;
            applyTheme(current, { persist: false, accentIndex: currentAccentIndex });
        }
        if (!select.dataset.bound) {
            select.addEventListener('change', () => {
                const chosen = themeCatalog.find(t => t.name === select.value);
                if (chosen) {
                    const selectedAccent = accentSelect ? Number(accentSelect.value) : currentAccentIndex;
                    if (accentInput) accentInput.value = String(selectedAccent);
                    applyTheme(chosen, { persist: false, accentIndex: selectedAccent });
                }
            });
            select.dataset.bound = 'true';
        }
        if (accentSelect && !accentSelect.dataset.bound) {
            accentSelect.addEventListener('change', () => {
                const newIndex = Number(accentSelect.value);
                if (accentInput) accentInput.value = String(newIndex);
                applyTheme(currentTheme, { persist: false, accentIndex: newIndex });
            });
            accentSelect.dataset.bound = 'true';
        }
    } catch (error) {
        console.error('Error loading themes:', error);
    }
}

async function main() {
    try {
        const [scheduleResponse, configResponse] = await Promise.all([
            fetch('/api/schedule'),
            fetch('/api/config')
        ]);

        if (!scheduleResponse.ok) {
            throw new Error(`Schedule API error: ${scheduleResponse.status}`);
        }
        if (!configResponse.ok) {
            throw new Error(`Config API error: ${configResponse.status}`);
        }

        const scheduleData = await scheduleResponse.json();
        const configData = await configResponse.json();
        latestScheduleData = scheduleData;
        latestConfigData = configData;
        
        console.log('main() loaded data:', {
            scheduleSlots: scheduleData.schedule?.length || 0,
            hasConfig: !!configData.timezone
        });

        updateStats(scheduleData, configData);
        renderChart(scheduleData, configData);
        renderTimeline(scheduleData);
        setNowShowing('local');
    } catch (error) {
        console.error('Error loading data:', error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Tab switching
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tab = button.dataset.tab;
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));
            button.classList.add('active');
            document.getElementById(tab).classList.add('active');

            if (tab === 'learning') {
                // Populate learning dashboard on first view and refresh
                loadLearningStatus();
                loadLearningMetrics();
                loadLearningLoops();
                loadLearningChanges();

                const runBtn = document.getElementById('run-learning-btn');
                const refreshBtn = document.getElementById('refresh-learning-btn');
                if (runBtn && !runBtn.dataset.bound) {
                    runBtn.addEventListener('click', runLearningNow);
                    runBtn.dataset.bound = 'true';
                }
                if (refreshBtn && !refreshBtn.dataset.bound) {
                    refreshBtn.addEventListener('click', async () => {
                        await Promise.all([
                            loadLearningStatus(),
                            loadLearningMetrics(),
                            loadLearningLoops(),
                            loadLearningChanges()
                        ]);
                    });
                    refreshBtn.dataset.bound = 'true';
                }
            }
            
            if (tab === 'debug') {
                // Populate debug dashboard on first view and refresh
                loadDebugData();

                const refreshBtn = document.getElementById('refresh-debug-btn');
                if (refreshBtn && !refreshBtn.dataset.bound) {
                    refreshBtn.addEventListener('click', async () => {
                        await loadDebugData();
                    });
                    refreshBtn.dataset.bound = 'true';
                }
            }
        });
    });

    // Load initial data
    main();

    // Load config and populate forms
    loadConfig();
    loadThemes();

    // Save changes
    document.querySelectorAll('#save-changes').forEach(button => {
        button.addEventListener('click', saveConfig);
    });

    // Reset to defaults
    document.querySelectorAll('#reset-defaults').forEach(button => {
        button.addEventListener('click', resetConfig);
    });

    // Run planner
    const runPlannerBtn = document.getElementById('runPlannerBtn');
    const reloadServerBtn = document.getElementById('reloadServerBtn');
    const pushDbBtn = document.getElementById('pushDbBtn');
    const plannerStatus = document.getElementById('plannerStatus');

    runPlannerBtn.addEventListener('click', () => {
        runPlannerBtn.disabled = true;
        plannerStatus.textContent = 'Running planner...';

        fetch('/api/run_planner', {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                plannerStatus.textContent = 'Success! Reloading...';
                main();  // Refresh all UI with new data
                setTimeout(() => {
                    plannerStatus.textContent = '';
                    runPlannerBtn.disabled = false;
                }, 2000);
            } else {
                throw new Error(data.message);
            }
        })
        .catch(error => {
            plannerStatus.textContent = 'Error! Check console.';
            console.error('Error running planner:', error);
            runPlannerBtn.disabled = false;
        });
    });

    // Load current plan from MariaDB and render
    if (reloadServerBtn) {
        reloadServerBtn.addEventListener('click', async () => {
            try {
                reloadServerBtn.disabled = true;
                plannerStatus.textContent = 'Loading server plan...';
                const [dbResp, cfgResp] = await Promise.all([
                    fetch('/api/db/current_schedule'),
                    fetch('/api/config')
                ]);
                if (!dbResp.ok) throw new Error(`DB API ${dbResp.status}`);
                if (!cfgResp.ok) throw new Error(`Config API ${cfgResp.status}`);
                const dbData = await dbResp.json();
                const cfgData = await cfgResp.json();
                latestScheduleData = dbData;
                latestConfigData = cfgData;
                updateStats(dbData, cfgData);
                renderChart(dbData, cfgData);
                renderTimeline(dbData);
                setNowShowing('server');
                plannerStatus.textContent = 'Loaded server plan';
                setTimeout(() => { plannerStatus.textContent = ''; }, 2000);
            } catch (e) {
                console.error('Failed to load server plan:', e);
                plannerStatus.textContent = 'Failed to load server plan';
            } finally {
                reloadServerBtn.disabled = false;
            }
        });
    }

    // Manually push current local schedule.json to MariaDB
    if (pushDbBtn) {
        pushDbBtn.addEventListener('click', async () => {
            try {
                pushDbBtn.disabled = true;
                plannerStatus.textContent = 'Pushing to DB...';
                const resp = await fetch('/api/db/push_current', { method: 'POST' });
                const payload = await resp.json();
                if (!resp.ok || payload.status !== 'success') {
                    throw new Error(payload.error || `HTTP ${resp.status}`);
                }
                plannerStatus.textContent = `Pushed ${payload.rows} rows`;
                // Auto-load server plan for visual confirmation
                const [dbResp, cfgResp] = await Promise.all([
                    fetch('/api/db/current_schedule'),
                    fetch('/api/config')
                ]);
                if (dbResp.ok && cfgResp.ok) {
                    const dbData = await dbResp.json();
                    const cfgData = await cfgResp.json();
                    latestScheduleData = dbData;
                    latestConfigData = cfgData;
                    renderTimeline(dbData);
                    renderChart(dbData, cfgData);
                    updateStats(dbData, cfgData);
                    setNowShowing('server');
                }
                setTimeout(() => { plannerStatus.textContent = ''; }, 1500);
            } catch (e) {
                console.error('Failed to push to DB:', e);
                plannerStatus.textContent = 'Failed to push to DB';
            } finally {
                pushDbBtn.disabled = false;
            }
        });
    }

    // Schedule midnight auto-refresh to keep views aligned with today/tomorrow
    (function scheduleMidnightRefresh() {
        const now = new Date();
        const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 1, 0);
        setTimeout(() => { main(); scheduleMidnightRefresh(); }, midnight.getTime() - now.getTime());
    })();

    // Add this inside the DOMContentLoaded listener
    const applyChangesBtn = document.getElementById('applyChangesBtn');
    const resetChangesBtn = document.getElementById('resetChangesBtn');

    applyChangesBtn.addEventListener('click', () => {
        // Get Manual Plan
        const manualItems = timelineItems.get();
        
        // Construct the "Simplified Schedule"
        const simplifiedSchedule = manualItems.map(item => ({
            start: item.start,
            end: item.end,
            content: item.content
        }));
        
        // Send to Backend API
        fetch('/api/simulate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(simplifiedSchedule)
        })
        .then(response => response.json())
        .then(async (simulatedData) => {
            // Persist simulated schedule to schedule.json so a later push uses it
            try {
                const saveResp = await fetch('/api/schedule/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ schedule: simulatedData.schedule })
                });
                if (!saveResp.ok) {
                    const details = await saveResp.json().catch(() => ({}));
                    console.warn('Failed to save simulated schedule:', details.error || saveResp.status);
                }
            } catch (e) { console.warn('Save schedule failed:', e); }

            latestScheduleData = simulatedData;
            // Handle the Response - update the main chart with new data
            const configResponse = await fetch('/api/config');
            const configData = await configResponse.json();
            latestConfigData = configData;
            // Keep current manual blocks visible; do not rebuild timeline from computed plan here
            renderChart(simulatedData, configData);
            updateStats(simulatedData, configData);
            setNowShowing('local');
        })
        .catch(error => {
            console.error('Error applying manual changes:', error);
        });
    });

    resetChangesBtn.addEventListener('click', () => {
        // Reload the optimal schedule from the server
        fetch('/api/schedule')
            .then(response => response.json())
            .then(scheduleData => {
                // Fetch config for rendering
                return fetch('/api/config').then(configResponse => {
                    return configResponse.json().then(configData => {
                        // Re-render both the timeline and the chart with the optimal schedule
                        renderTimeline(scheduleData);
                        renderChart(scheduleData, configData);
                        setNowShowing('local');
                    });
                });
            })
            .catch(error => {
                console.error('Error resetting to optimal schedule:', error);
            });
    });

    // Add-click buttons to create blocks
    const addChargeBtn = document.getElementById('addChargeBtn');
    const addWaterBtn  = document.getElementById('addWaterBtn');
    const addHoldBtn   = document.getElementById('addHoldBtn');
    const addExportBtn = document.getElementById('addExportBtn');
if (addChargeBtn) addChargeBtn.addEventListener('click', () => addActionBlock('Charge'));
    if (addWaterBtn)  addWaterBtn.addEventListener('click',  () => addActionBlock('Water Heating'));
    if (addHoldBtn)   addHoldBtn.addEventListener('click',   () => addActionBlock('Hold'));
    if (addExportBtn) addExportBtn.addEventListener('click', () => addActionBlock('Export'));

    // Learning tab event listeners
    const runLearningBtn = document.getElementById('run-learning-btn');
    const refreshLearningBtn = document.getElementById('refresh-learning-btn');
    
    if (runLearningBtn) {
        runLearningBtn.addEventListener('click', runLearningNow);
    }
    
    if (refreshLearningBtn) {
        refreshLearningBtn.addEventListener('click', refreshLearningData);
    }
    
    // Load learning data when learning tab is activated
    const learningTabButton = document.querySelector('[data-tab="learning"]');
    if (learningTabButton) {
        learningTabButton.addEventListener('click', () => {
            // Load learning data when tab is opened
            setTimeout(() => {
                refreshLearningData();
            }, 100);
        });
    }

});

function updateStats(data, config) {
    const statsContent = document.getElementById('stats-content');
    if (!statsContent) return;

    // Calculate PV total for today
    const schedule = data.schedule || [];
    const today = new Date();
    const todayKey = today.toDateString();
    const pvToday = schedule.reduce((total, slot) => {
        const slotDate = new Date(slot.start_time);
        return slotDate.toDateString() === todayKey
            ? total + (slot.pv_forecast_kwh || 0)
            : total;
    }, 0);

    // Get battery capacity from config (system override > legacy battery block)
    const batteryCapacity =
        config.system?.battery?.capacity_kwh ??
        config.battery?.capacity_kwh ??
        0;

    const sIndexCfg = config.s_index || {};
    const fallbackSummary = [
        sIndexCfg.mode || 'static',
        sIndexCfg.static_factor != null ? Number(sIndexCfg.static_factor).toFixed(2) : null,
        sIndexCfg.max_factor != null ? `max ${Number(sIndexCfg.max_factor).toFixed(2)}` : null
    ]
        .filter(Boolean)
        .join(' - ');
    let sIndexSummary = fallbackSummary || '-';

    const debugSIndex = data.debug?.s_index;
    if (debugSIndex && typeof debugSIndex === 'object') {
        const pieces = [];
        if (debugSIndex.mode) {
            pieces.push(String(debugSIndex.mode));
        }
        if (typeof debugSIndex.factor === 'number') {
            pieces.push(Number(debugSIndex.factor).toFixed(2));
        } else if (typeof debugSIndex.base_factor === 'number') {
            pieces.push(Number(debugSIndex.base_factor).toFixed(2));
        }
        if (typeof debugSIndex.max_factor === 'number') {
            pieces.push(`max ${Number(debugSIndex.max_factor).toFixed(2)}`);
        }
        if (debugSIndex.fallback) {
            pieces.push(`fallback: ${debugSIndex.fallback}`);
        }
        if (pieces.length) {
            sIndexSummary = pieces.join(' - ');
        }
    }

    // Generate stats HTML
    const statsHTML = `
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Total PV Today:</span>
            <span class="stat-value" id="stat-pv-today">${pvToday.toFixed(1)} kWh</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Local Plan:</span>
            <span class="stat-value" id="stat-local-plan">-</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Server Plan:</span>
            <span class="stat-value" id="stat-db-plan">-</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">PV Forecast:</span>
            <span class="stat-value" id="stat-pv-days">-</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Weather Forecast:</span>
            <span class="stat-value" id="stat-weather-days">-</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Current SoC:</span>
            <span class="stat-value" id="stat-current-soc">loading...</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Battery Capacity:</span>
            <span class="stat-value" id="stat-battery-capacity">${batteryCapacity.toFixed(1)} kWh</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Water Heater Today:</span>
            <span class="stat-value" id="stat-water-today">loading...</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">Avg Load (HA):</span>
            <span class="stat-value" id="stat-avg-load-ha">calculating...</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">HA data:</span>
            <span class="stat-value" id="stat-ha-daily-average">-</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">+</span>
            <span class="stat-label">S-index:</span>
            <span class="stat-value" id="stat-s-index">${sIndexSummary || '-'}</span>
        </div>
    `;

    statsContent.innerHTML = statsHTML;

    // Planned at/version info
    try {
        const localMeta = data.meta || {};
        const localEl = document.getElementById('stat-local-plan');
        if (localEl && (localMeta.planned_at || localMeta.planner_version)) {
            const when = localMeta.planned_at ? new Date(localMeta.planned_at).toLocaleString() : '-';
            const ver = localMeta.planner_version || '-';
            localEl.textContent = `${when} (v ${ver})`;
        }
    } catch {}
    fetch('/api/status')
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(status => {
            const db = status.db;
            const dbEl = document.getElementById('stat-db-plan');
            if (dbEl && db && !db.error) {
                const when = db.planned_at ? new Date(db.planned_at).toLocaleString() : '-';
                const ver = db.planner_version || '-';
                dbEl.textContent = `${when} (v ${ver})`;
            } else if (dbEl && db && db.error) {
                dbEl.textContent = `error: ${db.error}`;
            }
        })
        .catch(() => { /* ignore */ });

    // Fallback Avg Load from schedule (today, kW)
    try {
        const todayStr = new Date().toDateString();
        let sumKw = 0, count = 0;
        schedule.forEach(slot => {
            const d = new Date(slot.start_time);
            if (d.toDateString() === todayStr) {
                const kwh = slot.load_forecast_kwh || 0;
                sumKw += kwh * 4; // 15-min slots to kW
                count++;
            }
        });
        const fallbackAvg = count ? (sumKw / count) : 0;
        const avgEl = document.getElementById('stat-avg-load-ha');
        if (avgEl) avgEl.textContent = `${fallbackAvg.toFixed(1)} kW`;
    } catch {}

    // Try HA-provided averages and override if present
    fetch('/api/ha/average')
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(data => {
            const avgKw = Number(data.average_load_kw);
            if (!Number.isNaN(avgKw)) {
                const avgEl = document.getElementById('stat-avg-load-ha');
                if (avgEl) avgEl.textContent = `${avgKw.toFixed(1)} kW`;
            }
            const daily = Number(data.daily_kwh);
            if (!Number.isNaN(daily)) {
                const dailyEl = document.getElementById('stat-ha-daily-average');
                if (dailyEl) dailyEl.textContent = `${daily.toFixed(2)} kWh/day average`;
            }
        })
        .catch(() => { /* keep fallback */ });

    // Fetch current SoC asynchronously
    fetch('/api/initial_state')
        .then(response => response.json())
        .then(initialState => {
            const socValue = Number(initialState.battery_soc_percent);
            const socElement = document.getElementById('stat-current-soc');
            if (socElement && !Number.isNaN(socValue)) {
                socElement.textContent = `${socValue.toFixed(0)}%`;
            }
        })
        .catch(e => {
            console.warn('Could not load initial state:', e);
        });

    // Fetch water usage today
    fetch('/api/ha/water_today')
        .then(response => response.json())
        .then(payload => {
            const waterElement = document.getElementById('stat-water-today');
            if (!waterElement) return;

            if (payload && typeof payload.water_kwh_today === 'number') {
                waterElement.textContent = `${payload.water_kwh_today.toFixed(2)} kWh`;
            } else {
                waterElement.textContent = '-';
            }
        })
        .catch(() => {
            const waterElement = document.getElementById('stat-water-today');
            if (waterElement) waterElement.textContent = '-';
        });

    // Fetch forecast horizon info (days available)
    fetch('/api/forecast/horizon')
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(h => {
            const pvDaysEl = document.getElementById('stat-pv-days');
            const pvDays = h?.pv_forecast_days ?? h?.pv_days_schedule ?? h?.pv_days;
            if (pvDaysEl && typeof pvDays === 'number') {
                pvDaysEl.textContent = `${pvDays} days`;
            }

            const weatherEl = document.getElementById('stat-weather-days');
            let weatherDays = h?.weather_forecast_days;
            if (typeof weatherDays !== 'number') {
                const debugSIndex = data.debug?.s_index;
                if (debugSIndex && debugSIndex.temperatures) {
                    weatherDays = Object.keys(debugSIndex.temperatures).length;
                }
            }
            if (weatherEl && typeof weatherDays === 'number') {
                weatherEl.textContent = `${weatherDays} days`;
            }
        })
        .catch(() => {/* ignore */});
}

function getTodayWindow() {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
    const endOfTomorrow = new Date(startOfToday.getTime() + 48 * 60 * 60 * 1000);
    return { startOfToday, endOfTomorrow };
}

function snapToNextQuarterHour(date) {
    const d = new Date(date);
    d.setSeconds(0, 0);
    const m = d.getMinutes();
    const next = Math.ceil((m + 0.001) / 15) * 15;
    if (next >= 60) {
        d.setHours(d.getHours() + 1, 0, 0, 0);
    } else {
        d.setMinutes(next);
    }
    return d;
}

function addActionBlock(action) {
    const { startOfToday, endOfTomorrow } = getTodayWindow();
    const now = new Date();
    const oneHourMs = 60 * 60 * 1000;
    let start = snapToNextQuarterHour(now < startOfToday ? startOfToday : now);
    if (start.getTime() > endOfTomorrow.getTime() - oneHourMs) {
        start = new Date(endOfTomorrow.getTime() - oneHourMs);
    }
    const end = new Date(start.getTime() + oneHourMs);

    timelineItems.add({
        id: 'manual-' + Date.now() + '-' + Math.floor(Math.random() * 1000),
        content: action,
        start,
        end,
        style: themeStyleForAction(action)
    });
}

async function renderChart(data, config) {
    try {
        console.log('Rendering chart...');
        
        // Prevent concurrent chart rendering
        if (isRenderingChart) {
            console.log('Chart already rendering, skipping...');
            return;
        }
        isRenderingChart = true;

        // Get solar array kWp from config
        const kwp = config.system?.solar_array?.kwp || 5.0;

        // Calculate PV totals and build datasets for the dynamic 48-hour window
        const schedule = data.schedule || [];
        const { startOfToday, endOfTomorrow } = getTodayWindow();

        // Find first index within the window
        let startIndex = schedule.findIndex(s => new Date(s.start_time).getTime() >= startOfToday.getTime());
        if (startIndex === -1) startIndex = 0;
        const windowSlice = schedule.slice(startIndex, startIndex + 192);

        // Fetch additional SoC data for Rev 14 features
        let currentSoCPoint = null;
        let historicSoCLine = [];
        
        try {
            const [statusResponse, historicResponse] = await Promise.allSettled([
                fetch('/api/status'),
                fetch('/api/history/soc?date=today')
            ]);
            
            // Extract current SoC point from status API
            if (statusResponse.status === 'fulfilled' && statusResponse.value.ok) {
                try {
                    const statusData = await statusResponse.value.json();
                    if (statusData.current_soc && statusData.current_soc.value !== undefined) {
                        currentSoCPoint = {
                            x: statusData.current_soc.timestamp || new Date().toISOString(),
                            y: statusData.current_soc.value
                        };
                        
                        console.log(`[chart] Current SoC point: x=${currentSoCPoint.x}, y=${statusData.current_soc.value}`);
                    }
                } catch (e) {
                    console.warn('Could not parse current SoC from status:', e);
                }
            }
            
            // Extract historic SoC line from history API
            if (historicResponse.status === 'fulfilled' && historicResponse.value.ok) {
                try {
                    const historicData = await historicResponse.value.json();
                    if (historicData.slots && Array.isArray(historicData.slots)) {
                        historicSoCLine = historicData.slots.map(slot => ({
                            x: slot.timestamp,
                            y: slot.soc_percent
                        }));
                        console.log(`[chart] Historic SoC line: ${historicSoCLine.length} points`);
                    }
                } catch (e) {
                    console.warn('Could not parse historic SoC data:', e);
                }
            }
        } catch (e) {
            console.warn('Failed to fetch additional SoC data:', e);
        }
        
        // Small delay to ensure SoC data is processed before chart rendering
        await new Promise(resolve => setTimeout(resolve, 100));

        let pvToday = 0;
        let pvTomorrow = 0;
        const todayStr = startOfToday.toDateString();
        const tomorrowStr = new Date(startOfToday.getTime() + 24 * 60 * 60 * 1000).toDateString();

        // Compute PV totals across full schedule
        schedule.forEach(slot => {
            const slotDate = new Date(slot.start_time);
            const pvKwh = slot.pv_forecast_kwh || 0;
            if (slotDate.toDateString() === todayStr) pvToday += pvKwh;
            if (slotDate.toDateString() === tomorrowStr) pvTomorrow += pvKwh;
        });

        // Build 48-hour time-based datasets
        const importPrices = [];
        const pvForecasts = [];
        const loadForecasts = [];
        const batteryCharge = [];
        const batteryChargeHistorical = [];  // Track historical charge separately
        const batteryDischarge = [];
        const batteryDischargeHistorical = [];  // Track historical discharge separately
        const projectedSoC = [];
        const waterHeating = [];
        const exportPower = [];
        const socTarget = [];

        for (let i = 0; i < 192; i++) {
            const slot = windowSlice[i];
            if (slot) {
                const slotTime = new Date(slot.start_time);
                
                importPrices.push({
                    x: slotTime.toISOString(),
                    y: slot.import_price_sek_kwh ?? null
                });
                pvForecasts.push({
                    x: slotTime.toISOString(),
                    y: slot.pv_forecast_kwh ?? 0
                });
                loadForecasts.push({
                    x: slotTime.toISOString(),
                    y: slot.load_forecast_kwh ?? 0
                });
                
                // Separate historical vs current battery actions
                const chargeKw = (slot.battery_charge_kw ?? slot.charge_kw ?? 0);
                const dischargeKw = (slot.battery_discharge_kw ?? 0);
                
                if (slot.is_historical) {
                    // Historical slots - show in separate dataset with different styling
                    batteryCharge.push({
                        x: slotTime.toISOString(),
                        y: 0
                    });
                    batteryChargeHistorical.push({
                        x: slotTime.toISOString(),
                        y: chargeKw
                    });
                    batteryDischarge.push({
                        x: slotTime.toISOString(),
                        y: 0
                    });
                    batteryDischargeHistorical.push({
                        x: slotTime.toISOString(),
                        y: dischargeKw
                    });
                } else {
                    // Current/future slots - normal display
                    batteryCharge.push({
                        x: slotTime.toISOString(),
                        y: chargeKw
                    });
                    batteryChargeHistorical.push({
                        x: slotTime.toISOString(),
                        y: 0
                    });
                    batteryDischarge.push({
                        x: slotTime.toISOString(),
                        y: dischargeKw
                    });
                    batteryDischargeHistorical.push({
                        x: slotTime.toISOString(),
                        y: 0
                    });
                }
                
                projectedSoC.push({
                    x: slotTime.toISOString(),
                    y: slot.projected_soc_percent ?? null
                });
                waterHeating.push({
                    x: slotTime.toISOString(),
                    y: slot.water_heating_kw ?? 0
                });
                exportPower.push({
                    x: slotTime.toISOString(),
                    y: slot.export_kwh != null ? slot.export_kwh * 4 : 0
                });
                socTarget.push({
                    x: slotTime.toISOString(),
                    y: slot.soc_target_percent ?? null
                });
            }
        }

        // Get canvas element
        const canvas = document.getElementById('scheduleChart');
        if (!canvas) {
            console.error('Chart canvas not found!');
            return;
        }

        // Destroy previous chart if exists
        if (chart) {
            try {
                chart.destroy();
                chart = null;
            } catch (e) {
                console.warn('Error destroying previous chart:', e);
            }
        }

        // Clear canvas completely
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Fixed axes: price 0-8 SEK/kWh; energy scaled to series
        const fixedPriceMax = 8; // SEK/kWh

        const energySeries = [
            ...pvForecasts,
            ...loadForecasts,
            ...batteryCharge,
            ...batteryDischarge,
            ...waterHeating,
            ...exportPower,
        ].map(v => (typeof v === 'number' && !Number.isNaN(v) ? v : 0));
        const maxEnergy = energySeries.length ? Math.max(...energySeries) : 0;
        const fixedEnergyMax = Number.isFinite(maxEnergy) && maxEnergy > 0 ? Math.ceil(maxEnergy * 1.2) : 10;

        console.log('Chart data summary:', {
            hasPriceData: importPrices.some(v => v.y !== null),
            hasSoCData: projectedSoC.some(v => v.y !== null),
            hasCurrentSoC: currentSoCPoint !== null,
            historicSoCCount: historicSoCLine.length,
            samplePrices: importPrices.slice(0, 10),
            sampleSoC: projectedSoC.slice(0, 10),
            scheduleLength: schedule.length,
            windowSliceLength: windowSlice.length,
            maxEnergy: fixedEnergyMax,
            maxPrice: fixedPriceMax
        });





        const theme = getThemeColours();
        const palette = theme.palette;
        const colours = {
            price: palette[6] || theme.accent,
            pv: palette[4] || theme.accent,
            load: palette[5] || theme.accent,
            charge: palette[0] || theme.accent,
            water: palette[1] || theme.accent,
            export: palette[2] || theme.accent,
            discharge: palette[3] || theme.accent,
            soc: theme.foreground,
            socTarget: palette[7] || theme.accent,
            // Rev 14: Additional colors for current and historic SoC
            currentSoc: '#FF1493',  // Deep pink for current real SoC
            historicSoc: '#FF69B4'  // Hot pink for historic SoC line
        };

        const gradientFactory = (colour, startAlpha = 0.55, endAlpha = 0.05) => (context) => {
            const { chart } = context;
            const { ctx: chartCtx, chartArea } = chart;
            if (!chartArea) {
                return hexToRgba(colour, startAlpha);
            }
            const gradient = chartCtx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            gradient.addColorStop(0, hexToRgba(colour, startAlpha));
            gradient.addColorStop(1, hexToRgba(colour, endAlpha));
            return gradient;
        };

        const chargeFill = hexToRgba(colours.charge, 0.65);
        const waterFill = hexToRgba(colours.water, 0.65);
        const exportFill = hexToRgba(colours.export, 0.6);

        chart = new Chart(ctx, {
            type: 'bar',
            data: {
                datasets: [
                    {
                        type: 'line',
                        label: 'Import Price (SEK/kWh)',
                        data: importPrices,
                        borderColor: colours.price,
                        backgroundColor: gradientFactory(colours.price, 0.6, 0.05),
                        tension: 0,
                        pointRadius: 0,
                        stepped: true,
                        fill: true,
                        yAxisID: 'y',
                        spanGaps: false
                    },
                    {
                        type: 'line',
                        label: 'PV Forecast (kWh)',
                        data: pvForecasts,
                        borderColor: colours.pv,
                        backgroundColor: gradientFactory(colours.pv, 0.4, 0.05),
                        tension: 0.4,
                        pointRadius: 0,
                        fill: true,
                        yAxisID: 'y1'
                    },
                    {
                        type: 'line',
                        label: 'Load Forecast (kWh)',
                        data: loadForecasts,
                        borderColor: colours.load,
                        backgroundColor: gradientFactory(colours.load, 0.4, 0.05),
                        tension: 0.4,
                        pointRadius: 0,
                        fill: true,
                        yAxisID: 'y1'
                    },
                    {
                        type: 'bar',
                        label: 'Battery Charge (kW)',
                        data: batteryCharge,
                        backgroundColor: chargeFill,
                        yAxisID: 'y1',
                        barPercentage: 1.0,
                        categoryPercentage: 1.0
                    },
                    {
                        type: 'bar',
                        label: 'Water Heating (kW)',
                        data: waterHeating,
                        backgroundColor: waterFill,
                        yAxisID: 'y1',
                        barPercentage: 1.0,
                        categoryPercentage: 1.0
                    },
                    {
                        type: 'bar',
                        label: 'Export (kW)',
                        data: exportPower,
                        backgroundColor: exportFill,
                        yAxisID: 'y1',
                        barPercentage: 1.0,
                        categoryPercentage: 1.0
                    },
                    {
                        type: 'line',
                        label: 'Battery Discharge (kW)',
                        data: batteryDischarge,
                        borderColor: colours.discharge,
                        backgroundColor: 'transparent',
                        tension: 0.4,
                        pointRadius: 0,
                        fill: false,
                        yAxisID: 'y1'
                    },
                    {
                        type: 'line',
                        label: 'Projected SoC (%)',
                        data: projectedSoC,
                        borderColor: colours.soc,
                        backgroundColor: 'transparent',
                        yAxisID: 'y2',
                        fill: false,
                        pointRadius: 0,
                        borderDash: [3, 3],
                        spanGaps: false
                    },
                    {
                        type: 'line',
                        label: 'SoC Target (%)',
                        data: socTarget,
                        borderColor: colours.socTarget,
                        backgroundColor: 'transparent',
                        yAxisID: 'y2',
                        fill: false,
                        pointRadius: 0,
                        stepped: true,
                        borderDash: [6, 4],
                        spanGaps: false
                    },
                    // Rev 14: Current real SoC point and historic SoC line
                    {
                        type: 'scatter',
                        label: 'Current SoC (Real)',
                        data: currentSoCPoint ? [currentSoCPoint] : [],
                        backgroundColor: colours.currentSoc,  // Deep pink for current
                        borderColor: colours.currentSoc,
                        pointRadius: 8,
                        pointHoverRadius: 10,
                        yAxisID: 'y2',
                        showLine: false,
                        order: 0  // Ensure it renders on top
                    },
                    {
                        type: 'line', 
                        label: 'Historic SoC (Today)',
                        data: historicSoCLine.length > 0 ? historicSoCLine : [],
                        borderColor: colours.historicSoc,  // Hot pink for historic
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        tension: 0.1,
                        pointRadius: 0,
                        fill: false,
                        yAxisID: 'y2'
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                layout: {
                    padding: {
                        top: 40,
                        bottom: 40
                    }
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'hour',
                            stepSize: 2,
                            displayFormats: {
                                hour: 'HH:mm'
                            },
                            tooltipFormat: 'HH:mm'
                        },
                        min: startOfToday.toISOString(),
                        max: new Date(startOfToday.getTime() + 48 * 60 * 60 * 1000).toISOString(),
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: theme.foreground,
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 12
                        }
                    },
                    y: {
                        display: false,
                        beginAtZero: true,
                        min: 0,
                        max: fixedPriceMax
                    },
                    y1: {
                        display: false,
                        beginAtZero: true,
                        min: 0,
                        max: fixedEnergyMax
                    },
                    y2: {
                        display: false,
                        min: 0,
                        max: 100
                    }
                },
                plugins: {
                    legend: {
                        labels: {
                            color: theme.foreground
                        }
                    },
                    tooltip: {
                        backgroundColor: hexToRgba(theme.background || '#000000', 0.95),
                        titleColor: theme.foreground,
                        bodyColor: theme.foreground,
                        borderColor: theme.border,
                        borderWidth: 1
                    }
                }
            }
        });

        console.log('Chart created successfully');
    } catch (error) {
        console.error('Error rendering chart:', error);
        console.error('Error details:', error.stack);
    } finally {
        isRenderingChart = false;
    }
}

function renderTimeline(data) {
    try {
        const schedule = data.schedule || [];

        // Clear existing items before repainting
        timelineItems.clear();

        const { startOfToday, endOfTomorrow } = getTodayWindow();
        const filtered = schedule.filter(s => {
            const t = new Date(s.start_time).getTime();
            return t >= startOfToday.getTime() && t < endOfTomorrow.getTime();
        });

        let currentAction = null;
        let startSlot = null;
        let endSlot = null;
        filtered.forEach(slot => {
            let action = null;

            const classification = (slot.classification || '').toString().toLowerCase();
            if (slot.water_heating_kw > 0) {
                action = 'Water Heating';
            } else if (classification === 'charge' || classification === 'battery_charge' || classification === 'pv charge') {
                action = 'Charge';
            } else if (classification === 'export') {
                action = 'Export';
            } else if (classification === 'hold') {
                action = 'Hold';
            }

            if (action !== null) {
                const s = new Date(slot.start_time);
                const e = new Date(slot.end_time);

                if (currentAction === action) {
                    // Extend the current group
                    endSlot = { ...slot, start_time: s, end_time: e };
                } else {
                    // Finish the previous group if it exists
                    if (currentAction !== null) {
                        timelineItems.add({
                            id: startSlot.slot_number,
                            content: currentAction,
                            start: startSlot.start_time,
                            end: endSlot.end_time,
                            style: themeStyleForAction(currentAction)
                        });
                    }
                    // Start a new group
                    currentAction = action;
                    startSlot = { ...slot, start_time: s, end_time: e };
                    endSlot = { ...slot, start_time: s, end_time: e };
                }
            } else {
                // Finish the previous group if it exists
                if (currentAction !== null) {
                    timelineItems.add({
                        id: startSlot.slot_number,
                        content: currentAction,
                        start: startSlot.start_time,
                        end: endSlot.end_time,
                        style: themeStyleForAction(currentAction)
                    });
                    currentAction = null;
                }
            }
        });

        // Finish any remaining group
        if (currentAction !== null) {
            timelineItems.add({
                id: startSlot.slot_number,
                content: currentAction,
                start: startSlot.start_time,
                end: endSlot.end_time,
                style: themeStyleForAction(currentAction)
            });
        }

        const container = document.getElementById('timeline-container');
        if (!container) {
            console.error('Timeline container not found!');
            return;
        }

        // Use dynamic time window like the chart - always show today and tomorrow
        // using existing startOfToday/endOfTomorrow

        const options = {
            editable: { updateTime: true, updateGroup: false, add: false, remove: true },
            stack: true,
            start: startOfToday,
            end: endOfTomorrow,
            min: startOfToday,
            max: endOfTomorrow,
            height: '200px'
        };

        if (timelineInstance) {
            timelineInstance.destroy();
        }

        timelineInstance = new vis.Timeline(container, timelineItems, options);

        // Allow external drag targets to be dropped
        timelineInstance.on('dragover', (props) => {
            if (props && props.event && props.event.preventDefault) {
                props.event.preventDefault();
                if (props.event.dataTransfer) {
                    props.event.dataTransfer.dropEffect = 'copy';
                }
            }
        });

        // Handle drop: create a 1-hour block at the drop time
        timelineInstance.on('drop', (props) => {
            try {
                const evt = props && props.event;
                const dt = evt && evt.dataTransfer;
                const action = (dt && (dt.getData('text/plain') || dt.getData('text'))) || currentDragAction || 'Charge';

                const start = props && (props.snappedTime || props.time);
                const startDate = new Date(start);
                const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);

                timelineItems.add({
                    id: 'manual-' + Date.now() + '-' + Math.floor(Math.random() * 1000),
                    content: action,
                    start: startDate,
                    end: endDate,
                    style: themeStyleForAction(action)
                });
            } catch (e) {
                console.error('Drop error:', e);
            } finally {
                if (props && props.event && props.event.preventDefault) {
                    props.event.preventDefault();
                }
            }
        });

        console.log('Timeline created successfully with', timelineItems.length, 'items');
    } catch (error) {
        console.error('Error rendering timeline:', error);
    }
}


async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        populateForms(config);
    } catch (error) {
        console.error('Error loading config:', error);
    }
}

function populateForms(config) {
    const controls = document.querySelectorAll('[name]');
    controls.forEach(control => {
        const keys = control.name.split('.');
        let value = config;
        for (const key of keys) {
            value = value != null ? value[key] : undefined;
        }
        if (value === undefined) {
            return;
        }

        if (control.type === 'checkbox') {
            control.checked = Boolean(value);
        } else if (Array.isArray(value)) {
            // Display arrays (e.g., days_ahead_for_sindex) as comma-separated
            control.value = value.join(', ');
        } else {
            control.value = value;
        }
    });
}

async function saveConfig() {
    const config = {};
    const minSocField = document.querySelector('input[name="system.battery.min_soc_percent"]');
    const maxSocField = document.querySelector('input[name="system.battery.max_soc_percent"]');
    const minSocValue = minSocField && minSocField.value !== '' ? Number(minSocField.value) : null;
    const maxSocValue = maxSocField && maxSocField.value !== '' ? Number(maxSocField.value) : null;
    if (
        minSocValue !== null
        && maxSocValue !== null
        && (
            Number.isNaN(minSocValue)
            || Number.isNaN(maxSocValue)
            || minSocValue < 0
            || maxSocValue > 100
            || minSocValue > maxSocValue
        )
    ) {
        alert('Max SoC (%) must be between Min SoC (%) and 100. Please adjust the values.');
        return;
    }
    const controls = document.querySelectorAll('[name]');
    controls.forEach(control => {
        const keys = control.name.split('.');
        let obj = config;
        for (let i = 0; i < keys.length - 1; i++) {
            if (!obj[keys[i]]) obj[keys[i]] = {};
            obj = obj[keys[i]];
        }

        let value;
        if (control.type === 'checkbox') {
            value = control.checked;
        } else if (control.type === 'number') {
            if (control.value === '') {
                return;
            }
            const parsed = Number(control.value);
            if (!Number.isNaN(parsed)) {
                value = parsed;
            } else {
                return;
            }
        } else if (control.name.endsWith('days_ahead_for_sindex')) {
            // Convert comma-separated list to array of integers
            const parts = control.value.split(',').map(s => s.trim()).filter(Boolean);
            const arr = parts.map(p => Number(p)).filter(n => !Number.isNaN(n));
            value = arr;
        } else {
            if (control.value === '') {
                return;
            }
            value = control.value;
        }

        obj[keys[keys.length - 1]] = value;
    });

    if (config.ui && Object.prototype.hasOwnProperty.call(config.ui, 'theme_accent_index')) {
        const parsed = Number(config.ui.theme_accent_index);
        if (!Number.isNaN(parsed)) {
            config.ui.theme_accent_index = parsed;
        } else {
            delete config.ui.theme_accent_index;
        }
    }

    try {
        const response = await fetch('/api/config/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        await response.json();
        const themeSelect = document.getElementById('themeSelect');
        const accentSelect = document.getElementById('themeAccentSelect');
        if (themeSelect) {
            const selected = themeCatalog.find(t => t.name === themeSelect.value);
            const accentIndex = accentSelect ? Number(accentSelect.value) : currentAccentIndex;
            if (selected) {
                applyTheme(selected, { persist: true, accentIndex });
            } else if (themeSelect.value) {
                persistThemeSelection(themeSelect.value, accentIndex);
            }
        }
        alert('Configuration saved successfully!');
    } catch (error) {
        console.error('Error saving config:', error);
        alert('Error saving configuration.');
    }
}

async function resetConfig() {
    if (confirm('Are you sure you want to reset to defaults? This will overwrite your current settings.')) {
        try {
            const response = await fetch('/api/config/reset', {
                method: 'POST'
            });
            const result = await response.json();
            alert('Configuration reset to defaults!');
            loadConfig(); // Re-load the config to update the forms
            loadThemes();
        } catch (error) {
            console.error('Error resetting config:', error);
            alert('Error resetting configuration.');
        }
    }
}

// Learning Dashboard Functions
async function loadLearningStatus() {
    try {
        const response = await fetch('/api/learning/status');
        const status = await response.json();
        updateLearningStatus(status);
    } catch (error) {
        console.error('Error loading learning status:', error);
        document.getElementById('learning-status-content').innerHTML = 
            '<div class="error">Error loading learning status</div>';
    }
}

async function loadLearningMetrics() {
    try {
        const response = await fetch('/api/learning/status');
        const status = await response.json();
        updateLearningMetrics(status.metrics || {});
    } catch (error) {
        console.error('Error loading learning metrics:', error);
        document.getElementById('learning-metrics-content').innerHTML = 
            '<div class="error">Error loading learning metrics</div>';
    }
}

async function loadLearningLoops() {
    try {
        const response = await fetch('/api/learning/loops');
        const loops = await response.json();
        updateLearningLoops(loops);
    } catch (error) {
        console.error('Error loading learning loops:', error);
        document.getElementById('learning-loops-content').innerHTML = 
            '<div class="error">Error loading learning loops status</div>';
    }
}

async function loadLearningChanges() {
    try {
        const response = await fetch('/api/learning/changes');
        const data = await response.json();
        updateLearningChanges(data.changes || []);
    } catch (error) {
        console.error('Error loading learning changes:', error);
        document.getElementById('learning-changes-content').innerHTML = 
            '<div class="error">Error loading learning changes</div>';
    }
}

function updateLearningStatus(status) {
    const metrics = status.metrics || {};
    const dbSizeBytes = metrics.db_size_bytes;
    const dbSizeDisplay = typeof dbSizeBytes === 'number'
        ? `${(dbSizeBytes / 1024).toFixed(1)} KiB`
        : 'N/A';
    const lastObservation = metrics.last_observation
        ? new Date(metrics.last_observation).toLocaleString()
        : 'N/A';

    const statusHtml = `
        <div class="learning-metric">
            <span>Enabled:</span>
            <span>${status.enabled ? 'Yes' : 'No'}</span>
        </div>
        <div class="learning-metric">
            <span>SQLite Path:</span>
            <span>${status.sqlite_path || 'N/A'}</span>
        </div>
        <div class="learning-metric">
            <span>Sync Interval:</span>
            <span>${status.sync_interval_minutes || 'N/A'} minutes</span>
        </div>
        <div class="learning-metric">
            <span>Last Updated:</span>
            <span>${status.last_updated ? new Date(status.last_updated).toLocaleString() : 'N/A'}</span>
        </div>
        <div class="learning-metric">
            <span>Days with Data:</span>
            <span>${metrics.days_with_data || 0}</span>
        </div>
        <div class="learning-metric">
            <span>Last Slot:</span>
            <span>${lastObservation}</span>
        </div>
        <div class="learning-metric">
            <span>DB Size:</span>
            <span>${dbSizeDisplay}</span>
        </div>
    `;
    document.getElementById('learning-status-content').innerHTML = statusHtml;
}

function updateLearningMetrics(metrics) {
    const metricsHtml = `
        <div class="learning-metric">
            <span>Total Slots:</span>
            <span>${metrics.total_slots || 0}</span>
        </div>
        <div class="learning-metric">
            <span>Total Import (kWh):</span>
            <span>${(metrics.total_import_kwh || 0).toFixed(2)}</span>
        </div>
        <div class="learning-metric">
            <span>Total Export (kWh):</span>
            <span>${(metrics.total_export_kwh || 0).toFixed(2)}</span>
        </div>
        <div class="learning-metric">
            <span>Total PV (kWh):</span>
            <span>${(metrics.total_pv_kwh || 0).toFixed(2)}</span>
        </div>
        <div class="learning-metric">
            <span>Total Load (kWh):</span>
            <span>${(metrics.total_load_kwh || 0).toFixed(2)}</span>
        </div>
        <div class="learning-metric">
            <span>Learning Runs:</span>
            <span>${metrics.total_learning_runs || 0}</span>
        </div>
        <div class="learning-metric">
            <span>Completed Runs:</span>
            <span>${metrics.completed_learning_runs || 0}</span>
        </div>
        <div class="learning-metric">
            <span>Failed Runs:</span>
            <span>${metrics.failed_learning_runs || 0}</span>
        </div>
        <div class="learning-metric">
            <span>Price Coverage:</span>
            <span>${metrics.price_coverage_ratio != null ? (metrics.price_coverage_ratio * 100).toFixed(1) + '%' : 'N/A'}</span>
        </div>
        <div class="learning-metric">
            <span>Reset Events:</span>
            <span>${metrics.quality_reset_events || 0}</span>
        </div>
        <div class="learning-metric">
            <span>Gap Events:</span>
            <span>${metrics.quality_gap_events || 0}</span>
        </div>
    `;
    document.getElementById('learning-metrics-content').innerHTML = metricsHtml;
}

function updateLearningLoops(loops) {
    const loopsHtml = Object.entries(loops).map(([loopName, loopData]) => `
        <div class="learning-loop-status">
            <span>${formatLoopName(loopName)}</span>
            <span class="loop-status-indicator loop-status-${loopData.status}">
                ${loopData.status === 'has_changes' ? 'Has Changes' : 'No Changes'}
            </span>
        </div>
    `).join('');
    document.getElementById('learning-loops-content').innerHTML = loopsHtml;
}

function updateLearningChanges(changes) {
    if (changes.length === 0) {
        document.getElementById('learning-changes-content').innerHTML = 
            '<div class="learning-metric"><span>No recent changes</span></div>';
        return;
    }
    
    const changesHtml = changes.map(change => `
        <div class="learning-change-item">
            <div class="change-date">${new Date(change.created_at).toLocaleString()}</div>
            <div class="change-reason">${change.reason || 'No reason provided'}</div>
            <div class="change-metrics">
                Applied: ${change.applied ? 'Yes' : 'No'}
                ${change.metrics ? ` | Metrics: ${JSON.stringify(change.metrics)}` : ''}
            </div>
        </div>
    `).join('');
    document.getElementById('learning-changes-content').innerHTML = changesHtml;
}

function formatLoopName(loopName) {
    return loopName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

async function runLearningNow() {
    const btn = document.getElementById('run-learning-btn');
    const status = document.getElementById('learning-run-status');
    
    btn.disabled = true;
    status.textContent = 'Running learning...';
    
    try {
        const response = await fetch('/api/learning/run', {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.status === 'completed') {
            status.textContent = `Completed: ${result.changes_applied} changes applied`;
            // Refresh all learning data
            await Promise.all([
                loadLearningStatus(),
                loadLearningMetrics(),
                loadLearningLoops(),
                loadLearningChanges()
            ]);
        } else if (result.status === 'failed') {
            status.textContent = `Failed: ${result.error || 'Unknown error'}`;
        } else {
            status.textContent = `Skipped: ${result.reason || 'Unknown reason'}`;
        }
    } catch (error) {
        console.error('Error running learning:', error);
        status.textContent = 'Error running learning';
    } finally {
        btn.disabled = false;
        setTimeout(() => {
            status.textContent = '';
        }, 5000);
    }
}

// Debug Dashboard Functions
async function loadDebugData() {
    try {
        const response = await fetch('/api/debug');
        const debugData = await response.json();
        updateDebugMetrics(debugData.metrics || {});
        updateDebugCharging(debugData.charging_plan || {});
        updateDebugSIndex(debugData.s_index || {});
        updateDebugWindows(debugData.windows || {});
        updateDebugExport(debugData.export_guard || {});
        updateDebugETL(debugData.etl || {});
        updateDebugSamples(debugData.sample_schedule || []);
    } catch (error) {
        console.error('Error loading debug data:', error);
        document.getElementById('debug-metrics-content').innerHTML = 
            '<div class="error">Error loading debug data</div>';
        document.getElementById('debug-refresh-status').textContent = 'Error loading debug data';
        setTimeout(() => {
            document.getElementById('debug-refresh-status').textContent = '';
        }, 3000);
    }
}

function updateDebugMetrics(metrics) {
    const metricsHtml = `
        <div class="debug-metric">
            <span>Average Battery Cost:</span>
            <span>${metrics.average_battery_cost?.toFixed(2) || 'N/A'} SEK/kWh</span>
        </div>
        <div class="debug-metric">
            <span>Final SoC:</span>
            <span>${metrics.final_soc_percent?.toFixed(1) || 'N/A'}%</span>
        </div>
        <div class="debug-metric">
            <span>Net Energy Balance:</span>
            <span>${metrics.net_energy_balance_kwh?.toFixed(2) || 'N/A'} kWh</span>
        </div>
        <div class="debug-metric">
            <span>Total Load:</span>
            <span>${metrics.total_load_kwh?.toFixed(2) || 'N/A'} kWh</span>
        </div>
        <div class="debug-metric">
            <span>Total PV Generation:</span>
            <span>${metrics.total_pv_generation_kwh?.toFixed(2) || 'N/A'} kWh</span>
        </div>
    `;
    document.getElementById('debug-metrics-content').innerHTML = metricsHtml;
}

function updateDebugCharging(chargingPlan) {
    const chargingHtml = `
        <div class="debug-metric">
            <span>Total Charge:</span>
            <span>${chargingPlan.total_charge_kwh?.toFixed(2) || 'N/A'} kWh</span>
        </div>
        <div class="debug-metric">
            <span>Total Export:</span>
            <span>${chargingPlan.total_export_kwh?.toFixed(2) || 'N/A'} kWh</span>
        </div>
        <div class="debug-metric">
            <span>Export Revenue:</span>
            <span>${chargingPlan.total_export_revenue?.toFixed(2) || 'N/A'} SEK</span>
        </div>
    `;
    document.getElementById('debug-charging-content').innerHTML = chargingHtml;
}

function updateDebugSIndex(sIndex) {
    const sIndexHtml = `
        <div class="debug-metric">
            <span>Mode:</span>
            <span>${sIndex.mode || 'N/A'}</span>
        </div>
        <div class="debug-metric">
            <span>Factor:</span>
            <span>${sIndex.factor?.toFixed(4) || 'N/A'}</span>
        </div>
        <div class="debug-metric">
            <span>Base Factor:</span>
            <span>${sIndex.base_factor?.toFixed(2) || 'N/A'}</span>
        </div>
        <div class="debug-metric">
            <span>Avg Deficit:</span>
            <span>${sIndex.avg_deficit?.toFixed(4) || 'N/A'} kWh</span>
        </div>
        <div class="debug-metric">
            <span>Considered Days:</span>
            <span>${sIndex.considered_days ? sIndex.considered_days.join(', ') : 'N/A'}</span>
        </div>
    `;
    document.getElementById('debug-sindex-content').innerHTML = sIndexHtml;
}

function updateDebugSamples(samples) {
    if (!samples || samples.length === 0) {
        document.getElementById('debug-samples-content').innerHTML = 
            '<div class="debug-metric"><span>No debug samples available</span></div>';
        return;
    }
    
    const samplesHtml = samples.slice(0, 10).map((sample, index) => `
        <div class="debug-sample-item">
            <div class="sample-index">Sample ${index + 1}</div>
            <div class="sample-details">
                <span>Price: ${sample.price_sek_kwh?.toFixed(2) || 'N/A'} SEK/kWh</span>
                <span>Load: ${sample.load_forecast_kwh?.toFixed(2) || 'N/A'} kWh</span>
                <span>PV: ${sample.pv_forecast_kwh?.toFixed(2) || 'N/A'} kWh</span>
                <span>SoC: ${sample.soc_percent?.toFixed(1) || 'N/A'}%</span>
            </div>
        </div>
    `).join('');
    
    document.getElementById('debug-samples-content').innerHTML = samplesHtml;
}

function updateDebugWindows(windows) {
    const windowsHtml = `
        <div class="debug-metric">
            <span>Cheap Threshold:</span>
            <span>${windows.cheap_threshold_sek_kwh?.toFixed(2) || 'N/A'} SEK/kWh</span>
        </div>
        <div class="debug-metric">
            <span>Smoothing Tolerance:</span>
            <span>${windows.smoothing_tolerance_sek_kwh?.toFixed(2) || 'N/A'} SEK/kWh</span>
        </div>
        <div class="debug-metric">
            <span>Cheap Slots:</span>
            <span>${windows.cheap_slot_count || 0}</span>
        </div>
        <div class="debug-metric">
            <span>Non-Cheap Slots:</span>
            <span>${windows.non_cheap_slot_count || 0}</span>
        </div>
    `;
    document.getElementById('debug-windows-content').innerHTML = windowsHtml;
}

function updateDebugExport(exportGuard) {
    const exportHtml = `
        <div class="debug-metric">
            <span>Export Guard Buffer:</span>
            <span>${exportGuard.buffer_sek?.toFixed(2) || 'N/A'} SEK</span>
        </div>
        <div class="debug-metric">
            <span>Recent Export Events:</span>
            <span>${exportGuard.recent_export_events || 0}</span>
        </div>
        <div class="debug-metric">
            <span>Premature Export Detections:</span>
            <span>${exportGuard.premature_export_detections || 0}</span>
        </div>
        <div class="debug-metric">
            <span>Export Guard Active:</span>
            <span>${exportGuard.active ? 'Yes' : 'No'}</span>
        </div>
    `;
    document.getElementById('debug-export-content').innerHTML = exportHtml;
}

function updateDebugETL(etl) {
    const etlHtml = `
        <div class="debug-metric">
            <span>Price Coverage:</span>
            <span>${etl.price_coverage_ratio != null ? (etl.price_coverage_ratio * 100).toFixed(1) + '%' : 'N/A'}</span>
        </div>
        <div class="debug-metric">
            <span>Reset Events:</span>
            <span>${etl.reset_events || 0}</span>
        </div>
        <div class="debug-metric">
            <span>Gap Events:</span>
            <span>${etl.gap_events || 0}</span>
        </div>
        <div class="debug-metric">
            <span>Last Slot Timestamp:</span>
            <span>${etl.last_slot_timestamp ? new Date(etl.last_slot_timestamp).toLocaleString() : 'N/A'}</span>
        </div>
    `;
    document.getElementById('debug-etl-content').innerHTML = etlHtml;
}

async function refreshLearningData() {
    await Promise.all([
        loadLearningStatus(),
        loadLearningMetrics(),
        loadLearningLoops(),
        loadLearningChanges()
    ]);
}
