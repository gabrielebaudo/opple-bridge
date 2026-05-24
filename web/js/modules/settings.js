/**
 * Opple Bridge — Settings module
 * WiFi network management + system controls (reboot / shutdown).
 * Spread into the root Alpine component via app.js.
 */
window.SettingsModule = {

    // ── State ────────────────────────────────────────────────────
    settingsPanelOpen: false,
    wifiNetworks: [],          // [{ssid, priority, has_password, autoconnect}]
    wifiStatus: { connected: false, ssid: null, ip_address: null, is_hotspot: false },
    systemInfo: { version: '', git_sha: '', uptime_s: 0 },
    hotspotConfig: { ssid: 'OPPLE BRIDGE', has_password: false },
    hotspotForm: { ssid: '', password: '', showPassword: false },
    addForm: { ssid: '', password: '', showPassword: false },
    editingNetwork: null,      // { original_ssid, ssid, password, priority, showPassword } while editing
    _dragSsid: null,           // ssid being dragged (HTML5 DnD state)
    _settingsLoading: false,

    // ── Open / close ─────────────────────────────────────────────

    async openSettings() {
        this.settingsPanelOpen = true;
        this._settingsLoading = true;
        try {
            const [networksRes, statusRes, infoRes, hotspotRes] = await Promise.all([
                fetch('/api/wifi/networks'),
                fetch('/api/wifi/status'),
                fetch('/api/system/info'),
                fetch('/api/wifi/hotspot'),
            ]);
            if (networksRes.ok) this.wifiNetworks  = await networksRes.json();
            if (statusRes.ok)   this.wifiStatus    = await statusRes.json();
            if (infoRes.ok)     this.systemInfo     = await infoRes.json();
            if (hotspotRes.ok) {
                this.hotspotConfig = await hotspotRes.json();
                this.hotspotForm = { ssid: this.hotspotConfig.ssid, password: '', showPassword: false };
            }
        } catch {
            this.showToast('Failed to load settings', 'error');
        } finally {
            this._settingsLoading = false;
        }
    },

    closeSettings() {
        this.settingsPanelOpen = false;
        this.editingNetwork = null;
        this.addForm = { ssid: '', password: '', showPassword: false };
        this.hotspotForm = { ssid: this.hotspotConfig.ssid, password: '', showPassword: false };
    },

    // ── Add network ──────────────────────────────────────────────

    async submitAddNetwork() {
        const { ssid, password } = this.addForm;
        if (!ssid.trim()) { this.showToast('SSID required', 'warn'); return; }
        try {
            const res = await fetch('/api/wifi/networks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ssid: ssid.trim(),
                    // Trim before falsy check — whitespace-only strings must not be sent as passwords
                    password: password.trim() || null,
                    // New networks get the lowest priority so they are tried last.
                    // Server convention: higher number = higher preference (nmcli).
                    // Index 0 in the list = priority 100 (assigned by server on reorder).
                    // Sending a number below all existing ensures the server places this last.
                    priority: this.wifiNetworks.length
                        ? Math.min(...this.wifiNetworks.map(n => n.priority)) - 10
                        : 50,
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this.showToast(err.detail || 'Failed to add network', 'error');
                return;
            }
            this.addForm = { ssid: '', password: '', showPassword: false };
            const r = await fetch('/api/wifi/networks');
            if (r.ok) this.wifiNetworks = await r.json();
            const msg = this.wifiStatus.is_hotspot
                ? 'Network saved. Reboot to connect.'
                : 'Network added.';
            this.showToast(msg, 'success');
        } catch {
            this.showToast('Failed to add network', 'error');
        }
    },

    // ── Edit network ─────────────────────────────────────────────

    startEditNetwork(ssid) {
        const net = this.wifiNetworks.find(n => n.ssid === ssid);
        if (!net) return;
        this.editingNetwork = {
            original_ssid: net.ssid,
            ssid: net.ssid,
            password: net.password || '',
            priority: net.priority,
            showPassword: false,
        };
    },

    async saveEditNetwork() {
        if (!this.editingNetwork) return;
        const { original_ssid, ssid, password, priority } = this.editingNetwork;
        const cleanSsid = ssid.trim();
        if (!cleanSsid) { this.showToast('SSID required', 'warn'); return; }
        const cleanPassword = password.trim() || null;
        try {
            const res = await fetch(`/api/wifi/networks?ssid=${encodeURIComponent(original_ssid)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_ssid: cleanSsid, password: cleanPassword, priority }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this.showToast(err.detail || 'Update failed', 'error');
                return;
            }
            this.editingNetwork = null;
            const r = await fetch('/api/wifi/networks');
            if (r.ok) this.wifiNetworks = await r.json();
            const s = await fetch('/api/wifi/status');
            if (s.ok) this.wifiStatus = await s.json();
            this.showToast('Network updated', 'success');
        } catch {
            this.showToast('Update failed', 'error');
        }
    },

    // ── Delete network ───────────────────────────────────────────

    async deleteWifiNetwork(ssid) {
        if (!window.confirm(`Remove "${ssid}"?`)) return;
        try {
            const res = await fetch(
                `/api/wifi/networks?ssid=${encodeURIComponent(ssid)}`,
                { method: 'DELETE' }
            );
            if (!res.ok && res.status !== 204) {
                this.showToast('Delete failed', 'error');
                return;
            }
            this.wifiNetworks = this.wifiNetworks.filter(n => n.ssid !== ssid);
            this.showToast('Network removed', 'success');
        } catch {
            this.showToast('Delete failed', 'error');
        }
    },

    // ── Drag & Drop (HTML5 native, desktop) ─────────────────────

    onDragStart(event, ssid) {
        this._dragSsid = ssid;
        event.dataTransfer.effectAllowed = 'move';
    },

    onDragEnd() {
        this._dragSsid = null;
    },

    onDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
    },

    onDrop(event, targetSsid) {
        event.preventDefault();
        if (!this._dragSsid || this._dragSsid === targetSsid) return;
        const from = this.wifiNetworks.findIndex(n => n.ssid === this._dragSsid);
        const to   = this.wifiNetworks.findIndex(n => n.ssid === targetSsid);
        if (from < 0 || to < 0) return;
        const arr = [...this.wifiNetworks];
        const [moved] = arr.splice(from, 1);
        arr.splice(to, 0, moved);
        this.wifiNetworks = arr;
        this._dragSsid = null;
        this._commitReorder();
    },

    async _commitReorder() {
        try {
            const res = await fetch('/api/wifi/networks/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order: this.wifiNetworks.map(n => n.ssid) }),
            });
            if (!res.ok) { this.showToast('Reorder failed', 'error'); return; }
            this.showToast('Order updated', 'success');
        } catch {
            this.showToast('Reorder failed', 'error');
        }
    },

    // ── Arrow buttons (mobile fallback) ─────────────────────────

    moveNetworkUp(ssid) {
        const i = this.wifiNetworks.findIndex(n => n.ssid === ssid);
        if (i <= 0) return;
        const arr = [...this.wifiNetworks];
        [arr[i - 1], arr[i]] = [arr[i], arr[i - 1]];
        this.wifiNetworks = arr;
        this._commitReorder();
    },

    moveNetworkDown(ssid) {
        const i = this.wifiNetworks.findIndex(n => n.ssid === ssid);
        if (i < 0 || i >= this.wifiNetworks.length - 1) return;
        const arr = [...this.wifiNetworks];
        [arr[i], arr[i + 1]] = [arr[i + 1], arr[i]];
        this.wifiNetworks = arr;
        this._commitReorder();
    },

    // ── System controls ──────────────────────────────────────────

    pisugarUrl() {
        return `http://${window.location.hostname}:8421`;
    },

    async rebootPi() {
        if (!window.confirm('Reboot the Pi? You will lose connection for ~45 seconds.')) return;
        try {
            const res = await fetch('/api/system/reboot', { method: 'POST' });
            if (!res.ok) { this.showToast('Reboot failed', 'error'); return; }
            this.showToast('Pi is rebooting\u2026', 'warn', 10000);
            this.closeSettings();
        } catch {
            this.showToast('Reboot failed', 'error');
        }
    },

    async shutdownPi() {
        if (!window.confirm('Shut down the Pi? Power must be cycled to restart.')) return;
        try {
            const res = await fetch('/api/system/shutdown', { method: 'POST' });
            if (!res.ok) { this.showToast('Shutdown failed', 'error'); return; }
            this.showToast('Pi is shutting down\u2026', 'warn', 10000);
            this.closeSettings();
        } catch {
            this.showToast('Shutdown failed', 'error');
        }
    },

    // ── Hotspot config ───────────────────────────────────────────

    async saveHotspotConfig() {
        const ssid = this.hotspotForm.ssid.trim();
        if (!ssid) { this.showToast('Hotspot name required', 'warn'); return; }
        try {
            const res = await fetch('/api/wifi/hotspot', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ssid,
                    password: this.hotspotForm.password || null,
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this.showToast(err.detail || 'Failed to save hotspot config', 'error');
                return;
            }
            this.hotspotConfig.ssid = ssid;
            this.hotspotConfig.has_password = !!this.hotspotForm.password;
            this.hotspotForm.password = '';
            this.showToast('Hotspot config saved', 'success');
        } catch {
            this.showToast('Failed to save hotspot config', 'error');
        }
    },

    // ── Helpers ──────────────────────────────────────────────────

    formatUptime(s) {
        if (s == null) return '\u2014';
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = Math.floor(s % 60);
        if (h) return `${h}h ${m}m`;
        if (m) return `${m}m`;
        return `${sec}s`;
    },
};
