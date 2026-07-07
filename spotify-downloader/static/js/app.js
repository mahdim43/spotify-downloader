document.addEventListener('DOMContentLoaded', () => {
    UI.initParticles();

    const urlInput = document.getElementById('urlInput');
    const goBtn = document.getElementById('goBtn');
    const bitrateBtns = document.querySelectorAll('.bitrate-btn');
    const browseBtn = document.getElementById('browseBtn');
    const resetDirBtn = document.getElementById('resetDirBtn');
    const downloadDirInput = document.getElementById('downloadDir');

    let selectedBitrate = '320';
    let selectedDir = '';
    let currentSource = null;

    bitrateBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
            bitrateBtns.forEach((b) => b.classList.remove('active'));
            btn.classList.add('active');
            selectedBitrate = btn.dataset.bitrate;
        });
    });

    browseBtn.addEventListener('click', async () => {
        if (window.showDirectoryPicker) {
            try {
                const dirHandle = await window.showDirectoryPicker();
                selectedDir = dirHandle.name;
                downloadDirInput.value = dirHandle.name;
                UI.toast(`Output: ${dirHandle.name}`, 'info');
            } catch (e) {
                if (e.name !== 'AbortError') {
                    UI.toast('Directory picker failed', 'error');
                }
            }
        } else {
            UI.toast('Directory picker not supported in this browser. Type the path manually.', 'error');
        }
    });

    resetDirBtn.addEventListener('click', () => {
        selectedDir = '';
        downloadDirInput.value = '';
        UI.toast('Output reset to default', 'info');
    });

    goBtn.addEventListener('click', startDownload);
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') startDownload();
    });

    async function startDownload() {
        const url = urlInput.value.trim();
        if (!url) {
            UI.toast('Paste a Spotify URL first', 'error');
            urlInput.focus();
            return;
        }

        if (!url.includes('open.spotify.com')) {
            UI.toast('Invalid Spotify URL', 'error');
            return;
        }

        goBtn.disabled = true;
        goBtn.classList.add('loading');
        goBtn.querySelector('.go-text').textContent = 'LOADING';

        UI.showSection('progressSection');
        UI.hideSection('filesSection');
        UI.setProgress(0);
        UI.setPercent('0%');
        UI.setStatus('Connecting...');
        UI.setDetail('');
        UI.setStatusDot('');
        UI.setProgressBarState('');
        UI.hideTrackInfo();

        try {
            const result = await API.download(url, selectedBitrate, selectedDir);
            UI.setStatus('Job queued, downloading...');

            currentSource = API.connectProgress(result.job_id, {
                onStatus(data) {
                    UI.setStatus(data.status || 'Processing...');
                },
                onProgress(data) {
                    handleProgress(data);
                },
                onComplete(data) {
                    handleComplete(data);
                },
                onError(data) {
                    handleError(data.error || 'Unknown error');
                },
            });
        } catch (err) {
            handleError(err.message);
            resetButton();
        }
    }

    function handleProgress(data) {
        if (data.total > 0) {
            const pct = Math.round((data.completed / data.total) * 100);
            UI.setProgress(pct);
            UI.setPercent(`${pct}%`);
            UI.setStatus(`Downloading ${data.completed}/${data.total}...`);

            if (data.track) {
                UI.setTrackInfo(data.track);
            }
        }

        if (data.status === 'transcoding') {
            UI.setStatus(`Transcoding ${data.current}/${data.total}...`);
        }
    }

    function handleComplete(data) {
        UI.setProgress(100);
        UI.setPercent('100%');
        UI.setStatus('Download complete!');
        UI.setStatusDot('done');
        UI.setProgressBarState('done');
        UI.hideTrackInfo();

        const count = data.files?.length || 0;
        UI.setDetail(`${count} file${count !== 1 ? 's' : ''} ready`);

        if (data.files && data.files.length > 0) {
            UI.showSection('filesSection');
            UI.showFiles(data.files);
        }

        const failed = data.failed || 0;
        if (failed > 0) {
            UI.toast(`${failed} track(s) failed to download`, 'error');
        }

        resetButton();
    }

    function handleError(message) {
        UI.setStatus(`Error: ${message}`);
        UI.setStatusDot('error');
        UI.setProgressBarState('error');
        UI.setDetail('');
        UI.toast(message, 'error');
        resetButton();
    }

    function resetButton() {
        goBtn.disabled = false;
        goBtn.classList.remove('loading');
        goBtn.querySelector('.go-text').textContent = 'EXEC';
        if (currentSource) {
            currentSource.close();
            currentSource = null;
        }
    }
});
