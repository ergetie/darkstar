let chart;
let timelineItems = new vis.DataSet();
let currentDragAction = null;
let themeCatalog = [];
let currentTheme = null;
let currentAccentIndex = null;
let latestScheduleData = null;
let latestConfigData = null;
let timelineInstance = null;

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

function themeStyleForAction(action) {
    if (action === 'Charge') {
        return 'background-color: var(--ds-palette-8); color: var(--ds-background); border: 1px solid var(--ds-border);';
    }
    if (action === 'Water Heating') {
        return 'background-color: var(--ds-palette-9); color: var(--ds-background); border: 1px solid var(--ds-border);';
    }
    return '';
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
        .then(simulatedData => {
            // Handle the Response - update the main chart with new data
            // We need the current config to render the chart properly
            return fetch('/api/config').then(configResponse => {
                return configResponse.json().then(configData => {
                    renderChart(simulatedData, configData);
                });
            });
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
    if (addChargeBtn) addChargeBtn.addEventListener('click', () => addActionBlock('Charge'));
    if (addWaterBtn)  addWaterBtn.addEventListener('click',  () => addActionBlock('Water Heating'));


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
        .join(' • ');
    let sIndexSummary = fallbackSummary || '—';

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
            sIndexSummary = pieces.join(' • ');
        }
    }

    // Generate stats HTML
    const statsHTML = `
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">Total PV Today:</span>
            <span class="stat-value" id="stat-pv-today">${pvToday.toFixed(1)} kWh</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">PV Forecast:</span>
            <span class="stat-value" id="stat-pv-days">–</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">Weather Forecast:</span>
            <span class="stat-value" id="stat-weather-days">–</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">Current SoC:</span>
            <span class="stat-value" id="stat-current-soc">loading…</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">Battery Capacity:</span>
            <span class="stat-value" id="stat-battery-capacity">${batteryCapacity.toFixed(1)} kWh</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">Water Heater Today:</span>
            <span class="stat-value" id="stat-water-today">loading…</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">Avg Load (HA):</span>
            <span class="stat-value" id="stat-avg-load-ha">calculating…</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">HA data:</span>
            <span class="stat-value" id="stat-ha-daily-average">–</span>
        </div>
        <div class="stat-row">
            <span class="stat-key">├</span>
            <span class="stat-label">S-index:</span>
            <span class="stat-value" id="stat-s-index">${sIndexSummary || '—'}</span>
        </div>
    `;

    statsContent.innerHTML = statsHTML;

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
                waterElement.textContent = '—';
            }
        })
        .catch(() => {
            const waterElement = document.getElementById('stat-water-today');
            if (waterElement) waterElement.textContent = '—';
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

        // Get solar array kWp from config
        const kwp = config.system?.solar_array?.kwp || 5.0;

        // Calculate PV totals and build datasets for the dynamic 48-hour window
        const schedule = data.schedule || [];
        const { startOfToday, endOfTomorrow } = getTodayWindow();

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

        // Find first index within the window
        let startIndex = schedule.findIndex(s => new Date(s.start_time).getTime() >= startOfToday.getTime());
        if (startIndex === -1) startIndex = 0;
        const windowSlice = schedule.slice(startIndex, startIndex + 192);

        // Build 48-hour grid from startOfToday
        const labels = [];
        const importPrices = [];
        const pvForecasts = [];
        const loadForecasts = [];
        const batteryCharge = [];
        const batteryDischarge = [];
        const projectedSoC = [];
        const waterHeating = [];
        const exportPower = [];

        for (let i = 0; i < 192; i++) {
            const slotTime = new Date(startOfToday.getTime() + i * 15 * 60 * 1000);
            if (i % 4 === 0) {
                labels.push(slotTime.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' }));
            } else {
                labels.push('');
            }

            const slot = windowSlice[i];
            if (slot) {
                importPrices.push(slot.import_price_sek_kwh ?? null);
                pvForecasts.push(slot.pv_forecast_kwh ?? 0);
                loadForecasts.push(slot.load_forecast_kwh ?? 0);
                batteryCharge.push((slot.battery_charge_kw ?? slot.charge_kw ?? 0));
                batteryDischarge.push((slot.battery_discharge_kw ?? 0));
                projectedSoC.push(slot.projected_soc_percent ?? null);
                waterHeating.push(slot.water_heating_kw ?? 0);
                exportPower.push(slot.export_kwh != null ? slot.export_kwh * 4 : 0);
            } else {
                importPrices.push(null);
                pvForecasts.push(0);
                loadForecasts.push(0);
                batteryCharge.push(0);
                batteryDischarge.push(0);
                projectedSoC.push(null);
                waterHeating.push(0);
                exportPower.push(0);
            }
        }

        const canvas = document.getElementById('scheduleChart');
        if (!canvas) {
            console.error('Chart canvas not found!');
            return;
        }

        const ctx = canvas.getContext('2d');

        // Destroy previous chart if exists
        if (chart) {
            chart.destroy();
        }

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
            soc: theme.foreground
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
                labels: labels,
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
                        spanGaps: false  // Don't connect lines across null values
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
                        spanGaps: false  // Don't connect lines across null values
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
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: theme.foreground
                        }
                    },
                    y: {
                        display: false,
                        min: 0,
                        max: 10
                    },
                    y1: {
                        display: false
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
            if (classification === 'charge' || classification === 'battery_charge') {
                action = 'Charge';
            } else if (slot.water_heating_kw > 0) {
                action = 'Water Heating';
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
                            end: startSlot.end_time,
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
                        end: startSlot.end_time,
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
                end: startSlot.end_time,
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
