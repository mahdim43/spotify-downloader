const API = {
    async download(url, bitrate, outputDir) {
        const resp = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, bitrate, output_dir: outputDir || '' }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Download request failed');
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

        source.addEventListener('complete', (e) => {
            try {
                const data = JSON.parse(e.data);
                callbacks.onComplete?.(data);
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
