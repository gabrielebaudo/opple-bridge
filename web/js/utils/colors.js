/**
 * Color utility functions for the Opple Bridge dashboard.
 */

/**
 * Approximate CCT (Kelvin) to sRGB color for the temperature swatch.
 * Based on Tanner Helland's algorithm.
 */
function cctToRGB(kelvin) {
    const temp = kelvin / 100;
    let r, g, b;

    if (temp <= 66) {
        r = 255;
        g = Math.max(0, Math.min(255, 99.4708025861 * Math.log(temp) - 161.1195681661));
        if (temp <= 19) {
            b = 0;
        } else {
            b = Math.max(0, Math.min(255, 138.5177312231 * Math.log(temp - 10) - 305.0447927307));
        }
    } else {
        r = Math.max(0, Math.min(255, 329.698727446 * Math.pow(temp - 60, -0.1332047592)));
        g = Math.max(0, Math.min(255, 288.1221695283 * Math.pow(temp - 60, -0.0755148492)));
        b = 255;
    }

    return [Math.round(r), Math.round(g), Math.round(b)];
}

function cctToColor(kelvin) {
    if (!kelvin || kelvin < 1000) return '#888';
    const [r, g, b] = cctToRGB(kelvin);
    return `rgb(${r},${g},${b})`;
}

/**
 * CIE 1931 xy to approximate sRGB (for rendering the chromaticity diagram).
 * Uses the sRGB matrix and gamma correction.
 */
function xyToRGB(x, y, brightness) {
    if (y === 0) return [0, 0, 0];
    brightness = brightness || 1.0;

    const Y = brightness;
    const X = (Y / y) * x;
    const Z = (Y / y) * (1 - x - y);

    // sRGB matrix (D65)
    let r =  3.2406 * X - 1.5372 * Y - 0.4986 * Z;
    let g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z;
    let b =  0.0557 * X - 0.2040 * Y + 1.0570 * Z;

    // Clamp negatives
    const m = Math.min(r, g, b);
    if (m < 0) { r -= m; g -= m; b -= m; }

    // Normalize
    const mx = Math.max(r, g, b);
    if (mx > 0) { r /= mx; g /= mx; b /= mx; }

    // Gamma
    r = Math.pow(Math.max(0, r), 1 / 2.2) * 255;
    g = Math.pow(Math.max(0, g), 1 / 2.2) * 255;
    b = Math.pow(Math.max(0, b), 1 / 2.2) * 255;

    return [Math.round(r), Math.round(g), Math.round(b)];
}
