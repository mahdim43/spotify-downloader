const UI = {
    initParticles() {
        const container = document.getElementById('particles');
        if (!container) return;

        const count = 30;
        for (let i = 0; i < count; i++) {
            const p = document.createElement('div');
            p.className = 'particle';
            p.style.left = `${Math.random() * 100}%`;
            p.style.animationDuration = `${8 + Math.random() * 12}s`;
            p.style.animationDelay = `${Math.random() * 10}s`;
            p.style.width = `${1 + Math.random() * 2}px`;
            p.style.height = p.style.width;
            container.appendChild(p);
        }
    },

    showSection(id) {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove('hidden');
            el.style.animation = 'none';
            el.offsetHeight;
            el.style.animation = 'slideIn 0.4s ease-out';
        }
    },

    hideSection(id) {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    },

    setProgress(percent) {
        const bar = document.getElementById('progressBar');
        if (bar) {
            bar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
        }
    },

    setStatus(text) {
        const el = document.getElementById('statusText');
        if (el) el.textContent = text;
    },

    setPercent(text) {
        const el = document.getElementById('progressPercent');
        if (el) el.textContent = text;
    },

    setDetail(html) {
        const el = document.getElementById('progressDetail');
        if (el) el.innerHTML = html;
    },

    setTrackInfo(name) {
        const info = document.getElementById('trackInfo');
        const nameEl = document.getElementById('trackName');
        if (name && info && nameEl) {
            nameEl.textContent = name;
            info.classList.remove('hidden');
        }
    },

    hideTrackInfo() {
        const info = document.getElementById('trackInfo');
        if (info) info.classList.add('hidden');
    },

    setStatusDot(state) {
        const dot = document.getElementById('statusDot');
        if (!dot) return;
        dot.classList.remove('error', 'done');
        if (state === 'error') dot.classList.add('error');
        else if (state === 'done') dot.classList.add('done');
    },

    setProgressBarState(state) {
        const bar = document.getElementById('progressBar');
        if (!bar) return;
        bar.classList.remove('error', 'done');
        if (state === 'error') bar.classList.add('error');
        else if (state === 'done') bar.classList.add('done');
    },

    showFiles(files) {
        const list = document.getElementById('filesList');
        if (!list) return;
        list.innerHTML = '';

        if (files.length === 0) {
            list.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:0.5rem;">No files downloaded</div>';
            return;
        }

        files.forEach((file) => {
            const item = document.createElement('div');
            item.className = 'file-item';

            const name = file.split(/[/\\]/).pop();
            const url = `/files/${encodeURIComponent(name)}`;

            item.innerHTML = `
                <span class="file-name">${UI.escapeHtml(name)}</span>
                <a href="${url}" download class="file-download-btn">GET</a>
            `;
            list.appendChild(item);
        });
    },

    showResults(successFiles, failedTracks) {
        const successList = document.getElementById('successList');
        const failedList = document.getElementById('failedList');
        if (!successList || !failedList) return;
        successList.innerHTML = '';
        failedList.innerHTML = '';

        successFiles.forEach((file) => {
            UI._addSuccessItem(file);
        });
        UI._updateSuccessCount(successFiles.length);

        failedTracks.forEach((track) => {
            UI._addFailedItem(track);
        });
        UI._updateFailedCount(failedTracks.length);
    },

    addSuccess(file) {
        UI._addSuccessItem(file);
        const list = document.getElementById('successList');
        if (list) {
            const count = list.children.length;
            UI._updateSuccessCount(count);
            UI.showSection('filesSection');
        }
    },

    addFailed(track) {
        UI._addFailedItem(track);
        const list = document.getElementById('failedList');
        if (list) {
            const count = list.children.length;
            UI._updateFailedCount(count);
            UI.showSection('filesSection');
        }
    },

    _addSuccessItem(file) {
        const list = document.getElementById('successList');
        if (!list) return;
        const name = file.replace(/^\(exists\)\s*/i, '');
        const url = `/files/${encodeURIComponent(name)}`;
        const displayName = name.replace(/\.mp3$/i, '');
        const isSkipped = /^\(exists\)/i.test(file);

        const item = document.createElement('div');
        item.className = 'file-item result-success';
        item.innerHTML = `
            <span class="result-icon">${isSkipped ? '&#8635;' : '&#10003;'}</span>
            <span class="file-name">${UI.escapeHtml(displayName)}</span>
            ${isSkipped ? '<span class="skip-label">EXISTS</span>' : `<a href="${url}" download class="file-download-btn">GET</a>`}
        `;
        list.appendChild(item);
    },

    _addFailedItem(track) {
        const list = document.getElementById('failedList');
        if (!list) return;
        const displayName = track.artist
            ? `${track.artist} - ${track.title}`
            : track.title;

        const item = document.createElement('div');
        item.className = 'file-item result-failed';
        item.dataset.track = JSON.stringify(track);
        item.innerHTML = `
            <span class="result-icon fail">&#10007;</span>
            <span class="file-name">${UI.escapeHtml(displayName)}</span>
            <span class="fail-reason">${UI.escapeHtml(track.error || 'Failed')}</span>
            <button class="retry-btn" title="Retry this track">RETRY</button>
        `;
        list.appendChild(item);
        document.getElementById('failedSection')?.classList.remove('hidden');
        UI._updateRetryButton();
    },

    _updateSuccessCount(count) {
        const el = document.getElementById('successCount');
        if (el) el.textContent = count;
    },

    _updateFailedCount(count) {
        const el = document.getElementById('failedCount');
        if (el) el.textContent = count;
    },

    _updateRetryButton() {
        const failedList = document.getElementById('failedList');
        const retryAllContainer = document.getElementById('retryAllContainer');
        if (!failedList || !retryAllContainer) return;
        const count = failedList.children.length;
        if (count > 0) {
            retryAllContainer.classList.remove('hidden');
        } else {
            retryAllContainer.classList.add('hidden');
        }
    },

    getFailedTracks() {
        const failedList = document.getElementById('failedList');
        if (!failedList) return [];
        const tracks = [];
        for (const item of failedList.children) {
            try {
                tracks.push(JSON.parse(item.dataset.track));
            } catch {}
        }
        return tracks;
    },

    toast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.transition = 'opacity 0.3s';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
};
