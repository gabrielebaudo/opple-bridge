/**
 * WebSocket connection + BLE device scan/connect
 */
window.ConnectionModule = {
    devices: [],
    scanning: false,
    showDeviceList: false,

    connectWS() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}/ws`;
        try { this.ws = new WebSocket(url); } catch { setTimeout(() => this.connectWS(), this.wsRetryDelay); return; }

        this.ws.onopen = () => { this.wsRetryDelay = 1000; };
        this.ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'measurement') {
                    this.data = msg;
                    this.scheduleCIE();
                } else if (msg.type === 'flicker') {
                    this.flicker = msg;
                    this.flickerLoading = false;
                    this.$nextTick(() => this.drawFlicker());
                } else if (msg.type === 'connection') {
                    this.data.connection = msg;
                }
            } catch (err) { console.warn('WS parse error:', err); }
        };
        this.ws.onclose = () => {
            this.wsRetryDelay = Math.min(this.wsRetryDelay * 1.5, 10000);
            setTimeout(() => this.connectWS(), this.wsRetryDelay);
        };
        this.ws.onerror = () => {};
    },

    async scanAndConnect() {
        this.scanning = true;
        this.showDeviceList = true;
        try {
            const res = await fetch('/api/scan');
            const body = await res.json();
            this.devices = body.devices || [];
        } catch (err) {
            console.error('Scan failed:', err);
            this.devices = [];
            this.showToast('Scan failed. Check your connection.', 'error', 4000);
        } finally {
            this.scanning = false;
        }
    },

    async rescanDevices() {
        this.devices = [];
        await this.scanAndConnect();
    },

    cancelDeviceList() {
        this.showDeviceList = false;
        this.devices = [];
        this.scanning = false;
    },

    async connectToDevice(address) {
        this.showDeviceList = false;
        this.scanning = false;
        this.data.connection.status = 'connecting';
        try {
            await fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ address }),
            });
        } catch (err) {
            console.error('Connect failed:', err);
            this.showToast('Connection failed. Try again.', 'error', 4000);
        }
    },

    async disconnectDevice() {
        try {
            await fetch('/api/disconnect', { method: 'POST' });
            this.data.connection.status = 'disconnected';
            this.data.connection.device_name = null;
        } catch (err) {
            console.error('Disconnect failed:', err);
        }
    },
};
