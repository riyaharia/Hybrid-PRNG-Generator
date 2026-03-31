/* ── Hybrid RNG Dashboard — Frontend Logic ────────────────────────────── */

(function () {
    "use strict";

    // ── State ────────────────────────────────────────────────────────
    let currentMode = "PRNG";
    let totalSamples = 0;
    const MAX_FEED = 120;             // pills in live feed
    const ENTROPY_WINDOW = 60;        // data points in entropy line chart
    const HISTOGRAM_BINS = 32;        // number of bins for histogram

    // Per-mode data (kept client-side for charts)
    const modeData = { TRNG: [], PRNG: [], HYBRID: [] };
    const entropyHistory = [];        // { time, score }

    // ── Elements ─────────────────────────────────────────────────────
    const $stream      = document.getElementById("numberStream");
    const $totalSamples = document.getElementById("totalSamples");
    const $modeLabel   = document.getElementById("currentModeLabel");
    const $statsMode   = document.getElementById("statsMode");
    const $statsBody   = document.getElementById("statsBody");
    const $connStatus  = document.getElementById("connectionStatus");

    // ── Chart.js setup ───────────────────────────────────────────────

    const COLORS = {
        TRNG:   { main: "rgb(6,182,212)",   bg: "rgba(6,182,212,0.25)"  },
        PRNG:   { main: "rgb(168,85,247)",  bg: "rgba(168,85,247,0.25)" },
        HYBRID: { main: "rgb(249,115,22)",  bg: "rgba(249,115,22,0.25)" },
    };

    const chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: {
            legend: { display: false },
        },
        scales: {
            x: { grid: { color: "rgba(148,163,184,0.06)" }, ticks: { color: "#64748b", font: { size: 10 } } },
            y: { grid: { color: "rgba(148,163,184,0.06)" }, ticks: { color: "#64748b", font: { size: 10 } } },
        },
    };

    // -- Histogram
    const histCtx = document.getElementById("histogramChart").getContext("2d");
    const histogramChart = new Chart(histCtx, {
        type: "bar",
        data: {
            labels: Array.from({ length: HISTOGRAM_BINS }, (_, i) => `Bin ${i}`),
            datasets: [{
                data: new Array(HISTOGRAM_BINS).fill(0),
                backgroundColor: COLORS.TRNG.bg,
                borderColor: COLORS.TRNG.main,
                borderWidth: 1,
                borderRadius: 3,
            }],
        },
        options: {
            ...chartDefaults,
            plugins: { ...chartDefaults.plugins, tooltip: { enabled: true } },
            scales: {
                ...chartDefaults.scales,
                x: { ...chartDefaults.scales.x, ticks: { ...chartDefaults.scales.x.ticks, maxRotation: 45, autoSkip: true, maxTicksLimit: 12 } },
                y: { ...chartDefaults.scales.y, beginAtZero: true },
            },
        },
    });

    // -- Bit Distribution (doughnut)
    const bitCtx = document.getElementById("bitDistChart").getContext("2d");
    const bitDistChart = new Chart(bitCtx, {
        type: "doughnut",
        data: {
            labels: ["0 bits", "1 bits"],
            datasets: [{
                data: [50, 50],
                backgroundColor: ["rgba(100,116,139,0.4)", COLORS.TRNG.bg],
                borderColor: ["rgba(100,116,139,0.6)", COLORS.TRNG.main],
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            cutout: "65%",
            plugins: {
                legend: { position: "bottom", labels: { color: "#94a3b8", font: { size: 11 }, padding: 16 } },
            },
        },
    });

    // -- Entropy / Randomness score (line)
    const entCtx = document.getElementById("entropyChart").getContext("2d");
    const entropyChart = new Chart(entCtx, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                data: [],
                borderColor: COLORS.TRNG.main,
                backgroundColor: COLORS.TRNG.bg,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                borderWidth: 2,
            }],
        },
        options: {
            ...chartDefaults,
            scales: {
                ...chartDefaults.scales,
                y: { ...chartDefaults.scales.y, min: 0, max: 1, ticks: { ...chartDefaults.scales.y.ticks, stepSize: 0.2 } },
            },
        },
    });

    // ── Helpers ───────────────────────────────────────────────────────

    function modeColor(mode) { return COLORS[mode] || COLORS.TRNG; }

    function pillClass(mode) {
        if (mode === "PRNG") return "num-pill prng";
        if (mode === "HYBRID") return "num-pill hybrid";
        return "num-pill";
    }

    function detectBitWidth(values) {
        if (values.length === 0) return 16;
        const mx = Math.max(...values);
        if (mx > 65535) return 32;
        if (mx > 255)   return 16;
        return 8;
    }

    function computeEntropy(values) {
        // Shannon entropy normalised to [0,1] using detected bit width
        if (values.length < 10) return 0;
        const bw = detectBitWidth(values);
        const freq = new Map();
        for (const v of values) freq.set(v, (freq.get(v) || 0) + 1);
        let h = 0;
        const n = values.length;
        for (const count of freq.values()) {
            const p = count / n;
            h -= p * Math.log2(p);
        }
        return Math.min(h / bw, 1); // normalise by max possible entropy
    }

    function updateHistogramData(values) {
        if (values.length === 0) return { bins: new Array(HISTOGRAM_BINS).fill(0), labels: [] };
        const lo = Math.min(...values);
        const hi = Math.max(...values);
        const range = (hi - lo) || 1;
        const bins = new Array(HISTOGRAM_BINS).fill(0);
        const labels = [];
        for (let i = 0; i < HISTOGRAM_BINS; i++) {
            const bLo = Math.floor(lo + i * range / HISTOGRAM_BINS);
            const bHi = Math.floor(lo + (i + 1) * range / HISTOGRAM_BINS);
            labels.push(bLo >= 1000 ? `${(bLo/1000).toFixed(0)}k` : `${bLo}`);
        }
        for (const v of values) {
            const idx = Math.min(Math.floor((v - lo) * HISTOGRAM_BINS / (range + 1)), HISTOGRAM_BINS - 1);
            bins[idx]++;
        }
        return { bins, labels };
    }

    function countBits(values) {
        let zeros = 0, ones = 0;
        const bw = detectBitWidth(values);
        for (const v of values) {
            for (let i = 0; i < bw; i++) {
                if ((v >>> i) & 1) ones++; else zeros++;
            }
        }
        return [zeros, ones];
    }

    // ── UI Updates ───────────────────────────────────────────────────

    function addToFeed(mode, value) {
        // Remove placeholder
        const ph = $stream.querySelector(".placeholder-text");
        if (ph) ph.remove();

        const pill = document.createElement("span");
        pill.className = pillClass(mode);
        pill.textContent = value;
        $stream.appendChild(pill);

        // Trim
        while ($stream.children.length > MAX_FEED) {
            $stream.removeChild($stream.firstChild);
        }
        $stream.scrollTop = $stream.scrollHeight;
    }

    function refreshCharts() {
        const vals = modeData[currentMode] || [];
        const c = modeColor(currentMode);

        // Histogram
        const { bins, labels } = updateHistogramData(vals);
        histogramChart.data.labels = labels;
        histogramChart.data.datasets[0].data = bins;
        histogramChart.data.datasets[0].backgroundColor = c.bg;
        histogramChart.data.datasets[0].borderColor = c.main;
        histogramChart.update("none");

        // Bit distribution
        const [z, o] = countBits(vals);
        bitDistChart.data.datasets[0].data = [z, o];
        bitDistChart.data.datasets[0].backgroundColor = ["rgba(100,116,139,0.4)", c.bg];
        bitDistChart.data.datasets[0].borderColor = ["rgba(100,116,139,0.6)", c.main];
        bitDistChart.update("none");
    }

    function addEntropyPoint() {
        const vals = modeData[currentMode] || [];
        const score = computeEntropy(vals.slice(-200));
        entropyHistory.push(score);
        if (entropyHistory.length > ENTROPY_WINDOW) entropyHistory.shift();

        const c = modeColor(currentMode);
        entropyChart.data.labels = entropyHistory.map((_, i) => i);
        entropyChart.data.datasets[0].data = [...entropyHistory];
        entropyChart.data.datasets[0].borderColor = c.main;
        entropyChart.data.datasets[0].backgroundColor = c.bg;
        entropyChart.update("none");
    }

    function renderStatsTable(tests) {
        if (!tests || tests.length === 0) {
            $statsBody.innerHTML = '<tr><td colspan="4" class="muted">No results yet</td></tr>';
            return;
        }
        $statsBody.innerHTML = tests.map(t => `
            <tr>
                <td>${t.name}</td>
                <td>${t.statistic.toFixed(4)}</td>
                <td>${t.p_value.toFixed(4)}</td>
                <td class="${t.passed ? "result-pass" : "result-fail"}">${t.passed ? "✓ PASS" : "✗ FAIL"}</td>
            </tr>
        `).join("");
    }

    function updateComparison(data) {
        for (const mode of ["TRNG", "PRNG", "HYBRID"]) {
            const info = data[mode] || { count: 0, tests: [] };
            document.getElementById(`comp-${mode}-count`).textContent = info.count;
            const testsEl = document.getElementById(`comp-${mode}-tests`);
            if (info.tests && info.tests.length > 0) {
                testsEl.innerHTML = info.tests.map(t => `
                    <div class="comp-test-row">
                        <span>${t.name}</span>
                        <span class="${t.passed ? "result-pass" : "result-fail"}">${t.passed ? "✓" : "✗"} p=${t.p_value.toFixed(3)}</span>
                    </div>
                `).join("");
            } else {
                testsEl.innerHTML = '<p class="muted">Waiting...</p>';
            }
        }
    }

    function setActiveMode(mode) {
        currentMode = mode;
        $modeLabel.textContent = mode;
        $statsMode.textContent = mode;

        document.querySelectorAll(".mode-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.mode === mode);
        });

        // Update badge colours
        const c = modeColor(mode);
        $modeLabel.style.background = c.bg;
        $modeLabel.style.color = c.main;
        $statsMode.style.background = c.bg;
        $statsMode.style.color = c.main;

        // Reset entropy history for cleaner view on mode switch
        entropyHistory.length = 0;

        refreshCharts();
    }

    // ── Mode Buttons ─────────────────────────────────────────────────
    document.querySelectorAll(".mode-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const mode = btn.dataset.mode;
            setActiveMode(mode);

            // Tell the server
            fetch("/api/mode", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mode }),
            }).catch(() => {});
        });
    });

    // ── WebSocket ────────────────────────────────────────────────────
    let ws;
    let reconnectTimer;
    let chartRefreshCounter = 0;

    function setConnected(ok) {
        $connStatus.classList.toggle("disconnected", !ok);
        $connStatus.querySelector(".status-text").textContent = ok ? "Connected" : "Disconnected";
    }

    function connect() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${proto}//${location.host}/ws`);

        ws.onopen = () => {
            setConnected(true);
            if (reconnectTimer) { clearInterval(reconnectTimer); reconnectTimer = null; }
        };

        ws.onclose = () => {
            setConnected(false);
            if (!reconnectTimer) reconnectTimer = setInterval(connect, 3000);
        };

        ws.onerror = () => ws.close();

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);

            if (msg.type === "data") {
                for (const item of msg.values) {
                    totalSamples++;
                    const m = item.mode;
                    if (!modeData[m]) modeData[m] = [];
                    modeData[m].push(item.value);
                    if (modeData[m].length > 500) modeData[m] = modeData[m].slice(-500);

                    // Only add to feed if it matches the active mode
                    if (m === currentMode) {
                        addToFeed(m, item.value);
                    }
                }

                $totalSamples.textContent = totalSamples.toLocaleString();

                // Throttle chart updates
                chartRefreshCounter++;
                if (chartRefreshCounter % 3 === 0) {
                    refreshCharts();
                    addEntropyPoint();
                }
            }

            if (msg.type === "stats") {
                if (msg.mode === currentMode) {
                    renderStatsTable(msg.tests);
                }
            }

            if (msg.type === "mode_change") {
                setActiveMode(msg.mode);
            }
        };
    }

    connect();

    // ── Periodically fetch comparison ────────────────────────────────
    setInterval(async () => {
        try {
            const res = await fetch("/api/comparison");
            const data = await res.json();
            updateComparison(data);
        } catch (e) { /* ignore */ }
    }, 3000);

    // ── Initial mode badge colour ────────────────────────────────────
    setActiveMode("PRNG");

})();
