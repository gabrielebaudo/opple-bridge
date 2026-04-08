/**
 * IEEE 1789 flicker risk zone chart (Canvas renderer)
 *
 * Boundaries follow the OPPLE app convention:
 *   no_risk threshold  : Mod% = 0.033 * max(10, f)   -> green/yellow line
 *   low_risk threshold : Mod% = 0.080 * max(10, f)   -> yellow/red line
 * The max(10, f) clamp produces a horizontal floor below 10 Hz and a
 * straight diagonal above, matching the IEEE PAR1789-2015 chart shape.
 */
window.FlickerChartModule = {
    drawFlicker() {
        const canvas = this.$refs.flickerCanvas;
        if (!canvas || !this.flicker) return;

        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        const w = Math.round(rect.width);
        const h = Math.round(rect.height);
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        const pad = { l: 48, r: 16, t: 16, b: 32 };
        const pw = w - pad.l - pad.r;
        const ph = h - pad.t - pad.b;

        ctx.clearRect(0, 0, w, h);

        const F_MIN = 3, F_MAX = 10000;
        const M_MIN = 0.1, M_MAX = 100;
        const fMinL = Math.log10(F_MIN), fMaxL = Math.log10(F_MAX);
        const mMinL = Math.log10(M_MIN), mMaxL = Math.log10(M_MAX);

        const toX = f => pad.l + (Math.log10(Math.max(F_MIN, Math.min(F_MAX, f))) - fMinL) / (fMaxL - fMinL) * pw;
        const toY = m => pad.t + ph - (Math.log10(Math.max(M_MIN, Math.min(M_MAX, m))) - mMinL) / (mMaxL - mMinL) * ph;

        // Risk thresholds with horizontal floor below 10 Hz.
        const noRiskLine  = f => 0.033 * Math.max(10, f);
        const lowRiskLine = f => 0.080 * Math.max(10, f);

        // Build curves once as point arrays for both fills and strokes.
        const N = 220;
        const freqs = new Array(N + 1);
        for (let i = 0; i <= N; i++) {
            freqs[i] = F_MIN * Math.pow(F_MAX / F_MIN, i / N);
        }
        const noRiskPts  = freqs.map(f => [toX(f), toY(noRiskLine(f))]);
        const lowRiskPts = freqs.map(f => [toX(f), toY(lowRiskLine(f))]);

        const xL = pad.l, xR = pad.l + pw;
        const yT = pad.t, yB = pad.t + ph;

        // ─── Zone fills (non-overlapping) ─────────────────
        // Green: from chart bottom up to no-risk line.
        ctx.beginPath();
        ctx.moveTo(xL, yB);
        for (const [x, y] of noRiskPts) ctx.lineTo(x, y);
        ctx.lineTo(xR, yB);
        ctx.closePath();
        ctx.fillStyle = 'rgba(46,204,113,0.16)';
        ctx.fill();

        // Yellow: between no-risk and low-risk lines.
        ctx.beginPath();
        for (const [x, y] of noRiskPts) ctx.lineTo(x, y);
        for (let i = lowRiskPts.length - 1; i >= 0; i--) ctx.lineTo(lowRiskPts[i][0], lowRiskPts[i][1]);
        ctx.closePath();
        ctx.fillStyle = 'rgba(243,156,18,0.18)';
        ctx.fill();

        // Red: from low-risk line up to chart top.
        ctx.beginPath();
        ctx.moveTo(xL, yT);
        for (const [x, y] of lowRiskPts) ctx.lineTo(x, y);
        ctx.lineTo(xR, yT);
        ctx.closePath();
        ctx.fillStyle = 'rgba(231,76,60,0.18)';
        ctx.fill();

        // ─── Grid (drawn over fills, under boundary lines) ─
        ctx.strokeStyle = 'rgba(255,255,255,0.05)';
        ctx.lineWidth = 1;
        for (const f of [10, 100, 1000]) {
            const x = toX(f);
            ctx.beginPath(); ctx.moveTo(x, yT); ctx.lineTo(x, yB); ctx.stroke();
        }
        for (const m of [1, 10]) {
            const y = toY(m);
            ctx.beginPath(); ctx.moveTo(xL, y); ctx.lineTo(xR, y); ctx.stroke();
        }

        // ─── Boundary lines ───────────────────────────────
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = 1.5;

        const strokePath = (pts, color) => {
            ctx.strokeStyle = color;
            ctx.beginPath();
            for (let i = 0; i < pts.length; i++) {
                const [x, y] = pts[i];
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
        };
        strokePath(noRiskPts,  'rgba(46,204,113,0.95)');
        strokePath(lowRiskPts, 'rgba(243,156,18,0.95)');

        // ─── Axes ────────────────────────────────────────
        ctx.strokeStyle = 'rgba(255,255,255,0.18)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xL, yT); ctx.lineTo(xL, yB); ctx.lineTo(xR, yB);
        ctx.stroke();

        // ─── Tick labels ─────────────────────────────────
        ctx.fillStyle = 'rgba(180,180,180,0.7)';
        ctx.font = '9px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (const f of [3, 10, 100, 1000, 10000]) {
            ctx.fillText(f, toX(f), yB + 6);
        }
        ctx.fillText('Freq (Hz)', xL + pw / 2, h - 12);

        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (const m of [0.1, 1, 10, 100]) {
            ctx.fillText(m + '%', xL - 6, toY(m));
        }

        // ─── Legend ──────────────────────────────────────
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.font = '9px "JetBrains Mono", monospace';
        const legend = [
            ['#2ecc71', 'No Risk'],
            ['#f39c12', 'Low Risk'],
            ['#e74c3c', 'High Risk'],
        ];
        const lx = xR - 78;
        legend.forEach(([color, label], i) => {
            const ly = yT + 8 + i * 13;
            ctx.fillStyle = color;
            ctx.fillRect(lx, ly + 3, 8, 2);
            ctx.fillStyle = 'rgba(220,220,220,0.85)';
            ctx.fillText(label, lx + 14, ly);
        });

        // ─── Measured point ──────────────────────────────
        const mf = this.flicker.frequency_hz;
        const mm = this.flicker.modulation_pct;
        if (mf > 0 && mm > 0) {
            const px = toX(mf), py = toY(mm);
            const c = this.flicker.risk_level === 'no_risk'  ? '#2ecc71' :
                      this.flicker.risk_level === 'low_risk' ? '#f39c12' : '#e74c3c';
            ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(0,0,0,0.55)';
            ctx.fill();
            ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2);
            ctx.fillStyle = c; ctx.fill();
            ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6; ctx.stroke();
        }
    },
};
