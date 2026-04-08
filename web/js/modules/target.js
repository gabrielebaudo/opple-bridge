/**
 * Save Target — snapshot current measurement and show deltas
 */
window.TargetModule = {
    target: null,
    targetName: '',
    showDeltas: true,

    saveTarget() {
        const name = prompt('Target name (e.g. "ETC S4 Lustr3 FOH1"):', '');
        if (name === null) return;
        this.targetName = name || 'Target';
        this.target = JSON.parse(JSON.stringify(this.data));
        localStorage.setItem('opple_target', JSON.stringify({
            name: this.targetName,
            timestamp: new Date().toISOString(),
            data: this.target,
        }));
        this.showToast('Target saved: ' + this.targetName, 'success', 3000);
    },

    clearTarget() {
        this.target = null;
        this.targetName = '';
        localStorage.removeItem('opple_target');
        this.updateCIE();
    },

    loadTarget() {
        try {
            const saved = localStorage.getItem('opple_target');
            if (saved) {
                const parsed = JSON.parse(saved);
                this.target = parsed.data;
                this.targetName = parsed.name || 'Target';
            }
        } catch { /* ignore corrupt data */ }
    },

    delta(field) {
        if (!this.target || this.data[field] == null || this.target[field] == null) return null;
        return this.data[field] - this.target[field];
    },

    deltaFmt(field, decimals = 1, unit = '') {
        const d = this.delta(field);
        if (d == null) return '';
        const sign = d >= 0 ? '+' : '';
        return '\u0394 ' + sign + d.toFixed(decimals) + (unit ? ' ' + unit : '');
    },

    deltaPctFmt(field) {
        if (!this.target || !this.target[field] || this.data[field] == null) return '';
        const pct = ((this.data[field] - this.target[field]) / this.target[field]) * 100;
        const sign = pct >= 0 ? '+' : '';
        return '\u0394 ' + sign + pct.toFixed(1) + '%';
    },

    deltaColor(field, greenThresh, yellowThresh) {
        const d = this.delta(field);
        if (d == null) return 'text-gray-600';
        const abs = Math.abs(d);
        if (abs <= greenThresh) return 'text-green-400';
        if (abs <= yellowThresh) return 'text-yellow-400';
        return 'text-red-400';
    },

    deltaPctColor(field, greenPct, yellowPct) {
        if (!this.target || !this.target[field] || this.data[field] == null) return 'text-gray-600';
        const pct = Math.abs((this.data[field] - this.target[field]) / this.target[field]) * 100;
        if (pct <= greenPct) return 'text-green-400';
        if (pct <= yellowPct) return 'text-yellow-400';
        return 'text-red-400';
    },
};
