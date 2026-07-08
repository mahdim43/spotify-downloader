const API = {
    async download(url, bitrate, outputDir, embedLyrics) {
        const resp = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, bitrate, output_dir: outputDir || '', embed_lyrics: embedLyrics || false }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Download request failed');
        return data;
    },

    async stopJob(jobId) {
        const resp = await fetch(`/api/stop/${jobId}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Stop request failed');
        return data;
    },

    async resumeJob(jobId) {
        const resp = await fetch(`/api/resume/${jobId}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Resume request failed');
        return data;
    },

    async retryFailed(jobId, tracks, isAlbum) {
        const resp = await fetch(`/api/retry/${jobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tracks, is_album: isAlbum || false }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Retry request failed');
        return data;
    },

    async search(query) {
        const resp = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Search failed');
        return data;
    },

    connectProgress(jobId, callbacks) {
        const source = new EventSource(`/api/progress/${jobId}`);

        source.addEventListener('status', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onStatus?.(data);
            } catch {}
        });

        source.addEventListener('progress', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onProgress?.(data);
            } catch {}
        });

        source.addEventListener('file', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onFile?.(data);
            } catch {}
        });

        source.addEventListener('complete', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onComplete?.(data);
            } catch {}
            source.close();
        });

        source.addEventListener('retry_complete', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onRetryComplete?.(data) || callbacks.onComplete?.(data);
            } catch {}
            source.close();
        });

        source.addEventListener('stopped', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onStopped?.(data);
            } catch {}
            source.close();
        });

        source.addEventListener('error', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onError?.(data);
            } catch {
                callbacks.onError?.({ error: 'Connection lost' });
            }
            source.close();
        });

        source.onerror = () => {
            callbacks.onError?.({ error: 'SSE connection error' });
            source.close();
        };

        return source;
    },

    getFileUrl(filename) {
        return `/files/${encodeURIComponent(filename)}`;
    },

    async health() {
        const resp = await fetch('/api/health');
        return resp.json();
    },
};
