document.addEventListener('DOMContentLoaded', () => {
    UI.initParticles();

    const urlInput = document.getElementById('urlInput');
    const goBtn = document.getElementById('goBtn');
    const bitrateBtns = document.querySelectorAll('.bitrate-btn');
    const browseBtn = document.getElementById('browseBtn');
    const resetDirBtn = document.getElementById('resetDirBtn');
    const downloadDirInput = document.getElementById('downloadDir');
    const lyricsToggle = document.getElementById('lyricsToggle');
    const lyricsLabel = document.getElementById('lyricsLabel');

    let selectedBitrate = '320';
    let selectedDir = '';
    let embedLyrics = true;
    let currentSource = null;

    // Init lyrics label
    if (lyricsLabel) {
        lyricsLabel.textContent = 'ON';
        lyricsLabel.style.color = 'var(--accent)';
    }

    bitrateBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
            bitrateBtns.forEach((b) => b.classList.remove('active'));
            btn.classList.add('active');
            selectedBitrate = btn.dataset.bitrate;
        });
    });

    if (lyricsToggle) {
        lyricsToggle.addEventListener('change', () => {
            embedLyrics = lyricsToggle.checked;
            lyricsLabel.textContent = embedLyrics ? 'ON' : 'OFF';
            lyricsLabel.style.color = embedLyrics ? 'var(--accent)' : 'var(--text-muted)';
        });
    }

    downloadDirInput.addEventListener('input', () => {
        selectedDir = downloadDirInput.value.trim();
    });

    browseBtn.addEventListener('click', () => {
        UI.toast('Type the full path manually — browsers cannot access real paths for security.', 'info');
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
            const outputDir = downloadDirInput.value.trim() || selectedDir;
            const result = await API.download(url, selectedBitrate, outputDir, embedLyrics);
            UI.setStatus('Job queued, downloading...');

            currentSource = API.connectProgress(result.job_id, {
                onStatus(data) {
                    UI.setStatus(data.status || 'Processing...');
                },
                onProgress(data) {
                    handleProgress(data);
                },
                onFile(data) {
                    handleFile(data);
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
            const current = (data.current || 0) + 1;
            const total = data.total;
            const pct = Math.round(((current) / total) * 100);
            UI.setProgress(pct);
            UI.setPercent(`${pct}%`);

            const trackName = data.track || 'Unknown Track';
            UI.setStatus(`Downloading ${current}/${total}`);
            UI.setTrackInfo(`${current}. ${trackName}`);
        }

        if (data.status === 'transcoding') {
            UI.setStatus(`Transcoding ${data.current}/${data.total}...`);
        }
    }

    function handleFile(data) {
        const trackName = data.track || '';
        if (trackName) {
            UI.addSuccess(trackName);
        }
    }

    function handleComplete(data) {
        UI.setProgress(100);
        UI.setPercent('100%');
        UI.setStatus('Download complete!');
        UI.setStatusDot('done');
        UI.setProgressBarState('done');
        UI.hideTrackInfo();

        const downloadedCount = data.downloaded || data.files?.length || 0;
        const skippedCount = data.skipped || data.skipped_files?.length || 0;
        const failedCount = data.failed_tracks?.length || 0;
        UI.setDetail(`${downloadedCount} downloaded, ${skippedCount} skipped, ${failedCount} failed`);

        const allFiles = (data.files || []).concat((data.skipped_files || []).map(f => '(exists) ' + f));
        UI.showResults(allFiles, data.failed_tracks || []);

        if (failedCount > 0) {
            UI.toast(`${failedCount} track(s) failed to download`, 'error');
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
