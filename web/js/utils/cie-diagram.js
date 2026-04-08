/**
 * CIE 1931 Chromaticity Diagram — HiDPI renderer.
 *
 * Renders the spectral locus filled with the sRGB-approximated chromaticity
 * gradient, the Planckian (black-body) curve with iso-CCT ticks, wavelength
 * labels around the locus and an optional target marker — all matching the
 * reference Planckian Locus diagram used by the OPPLE app.
 *
 * The gradient is computed once at fixed resolution into an offscreen canvas
 * (pure JS point-in-polygon, no isPointInPath quirks) then drawn scaled into
 * the visible canvas. This is what fixes the desktop "blank diagram" bug.
 */

// ── Spectral locus (CIE 1931 2° observer) ─────────────────────────────────
const CIE_LOCUS = [
    [0.1741, 0.0050], [0.1740, 0.0050], [0.1738, 0.0049], [0.1736, 0.0049],
    [0.1733, 0.0048], [0.1726, 0.0048], [0.1714, 0.0051], [0.1689, 0.0069],
    [0.1644, 0.0109], [0.1566, 0.0177], [0.1440, 0.0297], [0.1241, 0.0578],
    [0.0913, 0.1327], [0.0687, 0.2007], [0.0454, 0.2950], [0.0235, 0.4127],
    [0.0082, 0.5384], [0.0039, 0.6548], [0.0139, 0.7502], [0.0389, 0.8120],
    [0.0743, 0.8338], [0.1142, 0.8262], [0.1547, 0.8059], [0.1929, 0.7816],
    [0.2296, 0.7543], [0.2658, 0.7243], [0.3016, 0.6923], [0.3373, 0.6589],
    [0.3731, 0.6245], [0.4087, 0.5896], [0.4441, 0.5547], [0.4788, 0.5202],
    [0.5125, 0.4866], [0.5448, 0.4544], [0.5752, 0.4242], [0.6029, 0.3965],
    [0.6270, 0.3725], [0.6482, 0.3514], [0.6658, 0.3340], [0.6801, 0.3197],
    [0.6915, 0.3083], [0.7006, 0.2993], [0.7079, 0.2920], [0.7140, 0.2859],
    [0.7190, 0.2809], [0.7230, 0.2770], [0.7260, 0.2740], [0.7283, 0.2717],
    [0.7300, 0.2700], [0.7311, 0.2689], [0.7320, 0.2680], [0.7327, 0.2673],
    [0.7334, 0.2666], [0.7340, 0.2660], [0.7344, 0.2656], [0.7346, 0.2654],
    [0.7347, 0.2653],
];

// Subset of CIE 1931 spectral locus points labelled by wavelength (nm).
// Coordinates come from the standard 2° observer table.
const CIE_WAVELENGTH_LABELS = [
    { wl: 380, x: 0.1741, y: 0.0050 },
    { wl: 460, x: 0.1440, y: 0.0297 },
    { wl: 470, x: 0.1241, y: 0.0578 },
    { wl: 480, x: 0.0913, y: 0.1327 },
    { wl: 490, x: 0.0454, y: 0.2950 },
    { wl: 500, x: 0.0082, y: 0.5384 },
    { wl: 510, x: 0.0139, y: 0.7502 },
    { wl: 520, x: 0.0743, y: 0.8338 },
    { wl: 540, x: 0.2296, y: 0.7543 },
    { wl: 560, x: 0.3731, y: 0.6245 },
    { wl: 580, x: 0.5125, y: 0.4866 },
    { wl: 600, x: 0.6270, y: 0.3725 },
    { wl: 620, x: 0.6915, y: 0.3083 },
    { wl: 700, x: 0.7347, y: 0.2653 },
];

// Planckian locus sample points (Kelvin, x, y).
const PLANCKIAN = [
    [1500, 0.5857, 0.3931], [2000, 0.5267, 0.4133], [2500, 0.4770, 0.4137],
    [3000, 0.4369, 0.4041], [3500, 0.4053, 0.3907], [4000, 0.3805, 0.3768],
    [4500, 0.3608, 0.3636], [5000, 0.3451, 0.3516], [5500, 0.3325, 0.3411],
    [6000, 0.3221, 0.3318], [6500, 0.3135, 0.3237], [7000, 0.3064, 0.3166],
    [8000, 0.2952, 0.3048], [9000, 0.2869, 0.2956], [10000, 0.2807, 0.2884],
    [15000, 0.2630, 0.2680], [20000, 0.2554, 0.2578],
];

const CCT_LABELS = [1500, 2000, 3000, 4000, 6000, 10000];

// Plot-space extents (the visible canvas region maps to these CIE ranges).
const PLOT_X_MAX = 0.8;
const PLOT_Y_MAX = 0.9;

// Gradient texture cached after first generation.
const GRADIENT_RESOLUTION = 360;
let _gradientCanvas = null;

function _pointInPolygon(x, y, poly) {
    let inside = false;
    const n = poly.length;
    for (let i = 0, j = n - 1; i < n; j = i++) {
        const xi = poly[i][0], yi = poly[i][1];
        const xj = poly[j][0], yj = poly[j][1];
        if (((yi > y) !== (yj > y)) &&
            (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
            inside = !inside;
        }
    }
    return inside;
}

function _generateGradientCanvas() {
    if (_gradientCanvas) return _gradientCanvas;

    const SIZE = GRADIENT_RESOLUTION;
    const off = document.createElement('canvas');
    off.width = SIZE;
    off.height = SIZE;
    const ctx = off.getContext('2d');

    // Locus polygon in gradient-canvas pixel space.
    const poly = CIE_LOCUS.map(([x, y]) => [
        x / PLOT_X_MAX * SIZE,
        SIZE - y / PLOT_Y_MAX * SIZE,
    ]);

    // Bounding box → only test pixels inside it.
    let minX = SIZE, minY = SIZE, maxX = 0, maxY = 0;
    for (const [px, py] of poly) {
        if (px < minX) minX = px;
        if (px > maxX) maxX = px;
        if (py < minY) minY = py;
        if (py > maxY) maxY = py;
    }
    minX = Math.max(0, Math.floor(minX) - 1);
    minY = Math.max(0, Math.floor(minY) - 1);
    maxX = Math.min(SIZE, Math.ceil(maxX) + 1);
    maxY = Math.min(SIZE, Math.ceil(maxY) + 1);

    const imgData = ctx.createImageData(SIZE, SIZE);
    const d = imgData.data;

    for (let py = minY; py < maxY; py++) {
        for (let px = minX; px < maxX; px++) {
            if (!_pointInPolygon(px + 0.5, py + 0.5, poly)) continue;
            const x = (px + 0.5) / SIZE * PLOT_X_MAX;
            const y = (SIZE - (py + 0.5)) / SIZE * PLOT_Y_MAX;
            const [r, g, b] = xyToRGB(x, y, 0.95);
            const idx = (py * SIZE + px) * 4;
            d[idx] = r;
            d[idx + 1] = g;
            d[idx + 2] = b;
            d[idx + 3] = 255;
        }
    }
    ctx.putImageData(imgData, 0, 0);
    _gradientCanvas = off;
    return off;
}

function _xyToCanvas(x, y, w, h, pad) {
    return [
        pad + x / PLOT_X_MAX * (w - pad * 2),
        h - pad - y / PLOT_Y_MAX * (h - pad * 2),
    ];
}

// CIE 1931 (x,y) ↔ CIE 1960 UCS (u,v). Iso-CCT lines are perpendicular to
// the Planckian locus in (u,v), NOT in (x,y) — computing the perpendicular
// directly in xy yields a mirrored slope (the bug we just fixed).
function _xyToUv1960(x, y) {
    const d = -2 * x + 12 * y + 3;
    return [4 * x / d, 6 * y / d];
}

function _uvToXy1960(u, v) {
    const d = 2 + u - 4 * v;
    return [3 * u / (2 * d), v / d];
}

function _buildLocusPath(w, h, pad) {
    const path = new Path2D();
    for (let i = 0; i < CIE_LOCUS.length; i++) {
        const [px, py] = _xyToCanvas(CIE_LOCUS[i][0], CIE_LOCUS[i][1], w, h, pad);
        if (i === 0) path.moveTo(px, py);
        else path.lineTo(px, py);
    }
    path.closePath();
    return path;
}

function _drawWavelengthLabels(ctx, w, h, pad) {
    const [cx, cy] = _xyToCanvas(0.33, 0.33, w, h, pad);

    const fontPx = Math.max(8, Math.min(10, Math.round(Math.min(w, h) * 0.024)));
    ctx.font = `600 ${fontPx}px JetBrains Mono, monospace`;
    ctx.textBaseline = 'middle';

    // Clamp labels inside the canvas with a small safety margin so digits
    // never collide with the outer frame or get cropped on small viewports.
    const margin = 3;
    const labelOffset = Math.max(10, Math.min(14, pad * 0.32));

    for (const wl of CIE_WAVELENGTH_LABELS) {
        const [lx, ly] = _xyToCanvas(wl.x, wl.y, w, h, pad);
        const dx = lx - cx;
        const dy = ly - cy;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const nx = dx / len;
        const ny = dy / len;

        // Outside-pointing tick mark.
        ctx.strokeStyle = 'rgba(255,255,255,0.55)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(lx + nx * 1, ly + ny * 1);
        ctx.lineTo(lx + nx * 5, ly + ny * 5);
        ctx.stroke();

        const align = nx > 0.25 ? 'left' : nx < -0.25 ? 'right' : 'center';
        ctx.textAlign = align;
        ctx.fillStyle = '#5fa8d8';

        // Estimate label width (mono: ~0.6em per char) so we can clamp.
        const label = String(wl.wl);
        const halfW = label.length * fontPx * 0.32;
        let tx = lx + nx * labelOffset;
        let ty = ly + ny * labelOffset;

        const leftEdge  = align === 'left'   ? tx           : align === 'right' ? tx - halfW * 2 : tx - halfW;
        const rightEdge = align === 'left'   ? tx + halfW*2 : align === 'right' ? tx             : tx + halfW;
        if (leftEdge  < margin)       tx += (margin - leftEdge);
        if (rightEdge > w - margin)   tx -= (rightEdge - (w - margin));
        ty = Math.max(margin + fontPx * 0.5, Math.min(h - margin - fontPx * 0.5, ty));

        ctx.fillText(label, tx, ty);
    }
}

function _drawPlanckian(ctx, w, h, pad) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Build the curve once, stroke twice: bright halo then dark core.
    const curve = new Path2D();
    for (let i = 0; i < PLANCKIAN.length; i++) {
        const [px, py] = _xyToCanvas(PLANCKIAN[i][1], PLANCKIAN[i][2], w, h, pad);
        if (i === 0) curve.moveTo(px, py);
        else curve.lineTo(px, py);
    }

    ctx.strokeStyle = 'rgba(255,255,255,0.55)';
    ctx.lineWidth = 2.8;
    ctx.stroke(curve);

    ctx.strokeStyle = '#0a0a0a';
    ctx.lineWidth = 1.4;
    ctx.stroke(curve);

    // Iso-CCT ticks: halo + dark core. Computed in CIE 1960 UCS so the
    // ticks come out perpendicular to the locus in the way the OPPLE
    // app (and every Robertson-style chart) draws them.
    const tickSegments = [];
    const ISO_HALF_UV = 0.013;
    for (const cct of CCT_LABELS) {
        const idx = PLANCKIAN.findIndex(p => p[0] === cct);
        if (idx < 0) continue;
        const prev = PLANCKIAN[Math.max(0, idx - 1)];
        const next = PLANCKIAN[Math.min(PLANCKIAN.length - 1, idx + 1)];
        const pt = PLANCKIAN[idx];

        const [uPrev, vPrev] = _xyToUv1960(prev[1], prev[2]);
        const [uNext, vNext] = _xyToUv1960(next[1], next[2]);
        const [u, v] = _xyToUv1960(pt[1], pt[2]);
        const tu = uNext - uPrev;
        const tv = vNext - vPrev;
        const tlen = Math.sqrt(tu * tu + tv * tv);
        if (tlen === 0) continue;

        const puU = (-tv / tlen) * ISO_HALF_UV;
        const puV = ( tu / tlen) * ISO_HALF_UV;
        const [x1, y1] = _uvToXy1960(u + puU, v + puV);
        const [x2, y2] = _uvToXy1960(u - puU, v - puV);
        tickSegments.push([
            _xyToCanvas(x1, y1, w, h, pad),
            _xyToCanvas(x2, y2, w, h, pad),
        ]);
    }

    ctx.strokeStyle = 'rgba(255,255,255,0.55)';
    ctx.lineWidth = 2.4;
    for (const [[x1, y1], [x2, y2]] of tickSegments) {
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
    }
    ctx.strokeStyle = '#0a0a0a';
    ctx.lineWidth = 1;
    for (const [[x1, y1], [x2, y2]] of tickSegments) {
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
    }

    // CCT labels: dark fill with white stroke outline for contrast against the gradient.
    ctx.font = '8px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    for (const cct of CCT_LABELS) {
        const pt = PLANCKIAN.find(p => p[0] === cct);
        if (!pt) continue;
        const [px, py] = _xyToCanvas(pt[1], pt[2], w, h, pad);
        const label = cct >= 10000 ? '10K' : cct >= 1000 ? (cct / 1000) + 'K' : cct + 'K';
        ctx.strokeText(label, px + 5, py + 9);
    }
    ctx.fillStyle = '#0a0a0a';
    for (const cct of CCT_LABELS) {
        const pt = PLANCKIAN.find(p => p[0] === cct);
        if (!pt) continue;
        const [px, py] = _xyToCanvas(pt[1], pt[2], w, h, pad);
        const label = cct >= 10000 ? '10K' : cct >= 1000 ? (cct / 1000) + 'K' : cct + 'K';
        ctx.fillText(label, px + 5, py + 9);
    }

    // Tc(K) header.
    const headerPt = PLANCKIAN.find(p => p[0] === 6000);
    if (headerPt) {
        const [hx, hy] = _xyToCanvas(headerPt[1], headerPt[2], w, h, pad);
        ctx.font = 'italic 600 10px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(255,255,255,0.85)';
        ctx.strokeText('T\u2099(K)', hx - 6, hy - 14);
        ctx.fillStyle = '#0a0a0a';
        ctx.fillText('T\u2099(K)', hx - 6, hy - 14);
    }
}

function _drawAxes(ctx, w, h, pad) {
    // Frame.
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad, pad);
    ctx.lineTo(pad, h - pad);
    ctx.lineTo(w - pad, h - pad);
    ctx.stroke();

    // Ticks.
    ctx.strokeStyle = 'rgba(255,255,255,0.32)';
    ctx.fillStyle = 'rgba(225,225,225,0.7)';
    ctx.font = '8px JetBrains Mono, monospace';

    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let v = 0; v <= PLOT_X_MAX + 1e-6; v += 0.1) {
        const [px, py] = _xyToCanvas(v, 0, w, h, pad);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px, py + 4);
        ctx.stroke();
        ctx.fillText(v.toFixed(1), px, py + 6);
    }

    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let v = 0; v <= PLOT_Y_MAX + 1e-6; v += 0.1) {
        const [px, py] = _xyToCanvas(0, v, w, h, pad);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px - 4, py);
        ctx.stroke();
        ctx.fillText(v.toFixed(1), px - 6, py);
    }

    // Axis titles.
    ctx.fillStyle = 'rgba(225,225,225,0.85)';
    ctx.font = 'italic 600 11px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText('x', w / 2, h - 4);

    ctx.save();
    ctx.translate(11, h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('y', 0, 0);
    ctx.restore();
}

function _drawTarget(ctx, measX, measY, targetX, targetY, w, h, pad) {
    if (!targetX || !targetY || targetX <= 0 || targetY <= 0) return;
    const [tx, ty] = _xyToCanvas(targetX, targetY, w, h, pad);

    if (measX > 0 && measY > 0) {
        const [mx, my] = _xyToCanvas(measX, measY, w, h, pad);
        ctx.strokeStyle = 'rgba(245,166,35,0.6)';
        ctx.lineWidth = 1.2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(mx, my);
        ctx.stroke();
        ctx.setLineDash([]);

        const dist = Math.sqrt((measX - targetX) ** 2 + (measY - targetY) ** 2);
        if (dist > 0.001) {
            const midX = (tx + mx) / 2;
            const midY = (ty + my) / 2;
            ctx.fillStyle = 'rgba(245,166,35,0.95)';
            ctx.font = '600 8px JetBrains Mono, monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'alphabetic';
            ctx.fillText('\u0394 ' + dist.toFixed(4), midX, midY - 5);
        }
    }

    const s = 7;
    ctx.beginPath();
    ctx.moveTo(tx, ty - s);
    ctx.lineTo(tx + s, ty);
    ctx.lineTo(tx, ty + s);
    ctx.lineTo(tx - s, ty);
    ctx.closePath();
    ctx.fillStyle = '#f5a623';
    ctx.fill();
    ctx.strokeStyle = '#0a0a0a';
    ctx.lineWidth = 1.4;
    ctx.stroke();

    ctx.fillStyle = '#f5a623';
    ctx.font = 'bold 9px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('T', tx + 9, ty);
}

function _drawMeasurement(ctx, measX, measY, w, h, pad) {
    if (!(measX > 0 && measY > 0)) return;
    const [px, py] = _xyToCanvas(measX, measY, w, h, pad);

    // Soft halo.
    const halo = ctx.createRadialGradient(px, py, 0, px, py, 18);
    halo.addColorStop(0, 'rgba(255,255,255,0.55)');
    halo.addColorStop(0.45, 'rgba(255,255,255,0.18)');
    halo.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(px, py, 18, 0, Math.PI * 2);
    ctx.fill();

    // White outer ring + black inner dot — high contrast on any chromaticity.
    ctx.beginPath();
    ctx.arc(px, py, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.85)';
    ctx.lineWidth = 1.4;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(px, py, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#0a0a0a';
    ctx.fill();
}

function drawCIE1931(canvas, measX, measY, targetX, targetY) {
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.round(rect.width);
    const h = Math.round(rect.height);
    if (w < 10 || h < 10) return;

    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, w, h);

    const pad = Math.round(Math.max(34, Math.min(46, Math.min(w, h) * 0.085)));
    const plotW = w - pad * 2;
    const plotH = h - pad * 2;

    // Locus path used both for clipping and for the outline.
    const locusPath = _buildLocusPath(w, h, pad);

    // Gradient fill, clipped to the locus.
    const gradient = _generateGradientCanvas();
    ctx.save();
    ctx.clip(locusPath);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(gradient, pad, pad, plotW, plotH);
    ctx.restore();

    // Locus outline.
    ctx.strokeStyle = 'rgba(255,255,255,0.8)';
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.stroke(locusPath);

    _drawWavelengthLabels(ctx, w, h, pad);
    _drawPlanckian(ctx, w, h, pad);
    _drawAxes(ctx, w, h, pad);
    _drawTarget(ctx, measX, measY, targetX, targetY, w, h, pad);
    _drawMeasurement(ctx, measX, measY, w, h, pad);
}
