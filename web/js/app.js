/**
 * Opple Bridge — Alpine.js application
 */
function oppleBridge() {
    return {
        // Core state
        ws: null,
        wsRetryDelay: 1000,

        data: {
            type: 'measurement',
            connection: { status: 'disconnected', device_name: null, device_address: null, mock_mode: false, battery_pct: null },
            lux: 0, cct_k: 0, duv: 0,
            cie_x: 0, cie_y: 0, cie_u: 0, cie_v: 0,
            cri_ra: null, r9: null, r_values: null,
            cs: null, eml: null,
            spectrum: [0, 0, 0, 0, 0, 0],
        },

        flicker: null,
        flickerLoading: false,

        activeInfo: null,

        toast: null,
        toastType: 'info',
        _toastTimeout: null,

        spectrumColors: ['#8B5CF6', '#3B82F6', '#10B981', '#EAB308', '#F97316', '#EF4444'],
        spectrumNames:  ['Violet',  'Blue',    'Green',   'Yellow',  'Orange',  'Red'],

        _cieTimer: null,

        paramInfo: window.PARAM_INFO,

        // Spread modules
        ...window.ConnectionModule,
        ...window.TargetModule,
        ...window.FlickerChartModule,

        // --- Core methods ---

        init() {
            this.loadTarget();
            this.connectWS();

            // Debounced resize: re-rasterises the CIE diagram + flicker chart
            // once per gesture so nothing smears when rotating a phone.
            window.addEventListener('resize', () => {
                clearTimeout(this._cieTimer);
                this._cieTimer = setTimeout(() => {
                    this.updateCIE();
                    if (this.flicker) this.drawFlicker();
                }, 150);
            });

            // Dismiss info popovers on outside click.
            document.addEventListener('click', (e) => {
                if (this.activeInfo && !e.target.closest('.info-trigger') && !e.target.closest('.info-popover')) {
                    this.activeInfo = null;
                }
            });

            // First paint: wait for layout + for the webfont so label metrics are stable.
            requestAnimationFrame(() => this.updateCIE());
            if (document.fonts && document.fonts.ready) {
                document.fonts.ready.then(() => this.updateCIE()).catch(() => {});
            }
        },

        /**
         * Throttled CIE redraw: multiple WS measurements inside the same frame
         * collapse into a single rAF tick. Keeps the Pi-served dashboard calm
         * on fast networks.
         */
        _cieRaf: null,
        scheduleCIE() {
            if (this._cieRaf) return;
            this._cieRaf = requestAnimationFrame(() => {
                this._cieRaf = null;
                this.updateCIE();
            });
        },

        requestFlicker() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.flickerLoading = true;
            this.ws.send(JSON.stringify({ type: 'command', action: 'request_flicker' }));
        },

        toggleInfo(param, event) {
            if (event) event.stopPropagation();
            this.activeInfo = this.activeInfo === param ? null : param;
        },

        showToast(msg, type = 'info', duration = 4000) {
            this.toast = msg;
            this.toastType = type;
            clearTimeout(this._toastTimeout);
            this._toastTimeout = setTimeout(() => { this.toast = null; }, duration);
        },

        updateCIE() {
            const c = this.$refs.cieCanvas;
            if (!c) return;
            const tx = this.target ? this.target.cie_x : null;
            const ty = this.target ? this.target.cie_y : null;
            drawCIE1931(c, this.data.cie_x, this.data.cie_y, tx, ty);
        },

        barHeight(ch) {
            const s = this.data.spectrum || [];
            const mx = s.length ? Math.max(...s, 1) : 1;
            return Math.max(2, (ch || 0) / mx * 100);
        },

        formatLux(lux) {
            if (lux == null) return '\u2014';
            if (lux >= 1000) return lux.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
            if (lux >= 100) return lux.toFixed(0);
            if (lux >= 10) return lux.toFixed(1);
            return lux.toFixed(2);
        },

        formatDuv(duv) {
            if (duv == null) return '\u2014';
            return (duv >= 0 ? '+' : '') + duv.toFixed(4);
        },

        batteryClass(pct) {
            if (pct == null) return '';
            if (pct >= 50) return 'battery-good';
            if (pct >= 20) return 'battery-mid';
            return 'battery-low';
        },

        /**
         * Shorten a BLE address / UUID for narrow header pills.
         * macOS gives UUIDs like "F8E80615-2413-0F88-9D91-1F0DDFB60F6C",
         * Linux gives "XX:XX:XX:XX:XX:XX". Both are truncated to head…tail.
         */
        formatMac(addr) {
            if (!addr) return '';
            if (addr.length <= 17) return addr;
            return addr.slice(0, 8) + '\u2026' + addr.slice(-6);
        },
    };
}
