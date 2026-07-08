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
    const stopBtn = document.getElementById('stopBtn');
    const resumeBtn = document.getElementById('resumeBtn');
    const retryAllBtn = document.getElementById('retryAllBtn');

    let selectedBitrate = '320';
    let selectedDir = '';
    let embedLyrics = true;
    let currentSource = null;
    let currentJobId = null;
    let isAlbum = false;

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

    browseBtn.addEventListener('click', async () => {
        try {
            const resp = await fetch('/api/browse-folder');
            const data = await resp.json();
            if (data.path) {
                downloadDirInput.value = data.path;
                selectedDir = data.path;
                UI.toast('Folder selected: ' + data.path, 'success');
            } else if (data.error) {
                UI.toast(data.error, 'error');
            }
        } catch (err) {
            UI.toast('Failed to open folder picker', 'error');
        }
    });

    resetDirBtn.addEventListener('click', () => {
        selectedDir = '';
        downloadDirInput.value = '';
        UI.toast('Output reset to default', 'info');
    });

    stopBtn.addEventListener('click', async () => {
        if (currentJobId) {
            try {
                await API.stopJob(currentJobId);
                UI.toast('Stopping download...', 'info');
            } catch (err) {
                UI.toast('Failed to stop: ' + err.message, 'error');
            }
        }
    });

    resumeBtn.addEventListener('click', async () => {
        if (currentJobId) {
            try {
                await API.resumeJob(currentJobId);
                UI.toast('Resuming download...', 'info');
                resumeBtn.classList.add('hidden');
                stopBtn.classList.remove('hidden');
            } catch (err) {
                UI.toast('Failed to resume: ' + err.message, 'error');
            }
        }
    });

    // Retry all failed tracks
    if (retryAllBtn) {
        retryAllBtn.addEventListener('click', async () => {
            if (!currentJobId) return;
            const failedTracks = UI.getFailedTracks();
            if (failedTracks.length === 0) return;

            retryAllBtn.disabled = true;
            retryAllBtn.textContent = 'RETRYING...';

            try {
                UI.showSection('progressSection');
                UI.setStatus('Retrying failed tracks...');
                UI.setDetail('');
                UI.setProgress(0);
                UI.setPercent('0%');
                UI.setStatusDot('');
                UI.setProgressBarState('');

                const result = await API.retryFailed(currentJobId, failedTracks, isAlbum);
                currentJobId = result.job_id;

                currentSource = API.connectProgress(result.job_id, {
                    onStatus(data) {
                        UI.setStatus(data.status || 'Retrying...');
                    },
                    onProgress(data) {
                        handleProgress(data);
                    },
                    onFile(data) {
                        handleFile(data);
                    },
                    onRetryComplete(data) {
                        handleRetryComplete(data);
                    },
                    onStopped(data) {
                        handleRetryComplete(data);
                    },
                    onError(data) {
                        handleRetryComplete(data);
                    },
                });
            } catch (err) {
                UI.toast('Retry failed: ' + err.message, 'error');
                retryAllBtn.disabled = false;
                retryAllBtn.textContent = 'RETRY ALL FAILED';
            }
        });
    }

    // Individual retry button delegation
    document.addEventListener('click', (e) => {
        const retryBtn = e.target.closest('.retry-btn');
        if (!retryBtn || !currentJobId) return;

        const item = retryBtn.closest('.result-failed');
        if (!item) return;

        let track;
        try {
            track = JSON.parse(item.dataset.track);
        } catch { return; }

        retryBtn.disabled = true;
        retryBtn.textContent = '...';

        (async () => {
            try {
                UI.showSection('progressSection');
                UI.setStatus(`Retrying: ${track.artist || ''} - ${track.title}`);
                UI.setDetail('');
                UI.setProgress(0);
                UI.setPercent('0%');
                UI.setStatusDot('');
                UI.setProgressBarState('');

                const result = await API.retryFailed(currentJobId, [track], isAlbum);
                currentJobId = result.job_id;

                currentSource = API.connectProgress(result.job_id, {
                    onStatus(data) {
                        UI.setStatus(data.status || 'Retrying...');
                    },
                    onProgress(data) {
                        handleProgress(data);
                    },
                    onFile(data) {
                        handleFile(data);
                    },
                    onRetryComplete(data) {
                        handleRetryComplete(data);
                    },
                    onStopped(data) {
                        handleRetryComplete(data);
                    },
                    onError(data) {
                        handleRetryComplete(data);
                    },
                });
            } catch (err) {
                UI.toast('Retry failed: ' + err.message, 'error');
                retryBtn.disabled = false;
                retryBtn.textContent = 'RETRY';
            }
        })();
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

        // Show stop button, hide resume button
        stopBtn.classList.remove('hidden');
        resumeBtn.classList.add('hidden');

        isAlbum = url.includes('/album/');

        try {
            const outputDir = downloadDirInput.value.trim() || selectedDir;
            const result = await API.download(url, selectedBitrate, outputDir, embedLyrics);
            currentJobId = result.job_id;
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
                onStopped(data) {
                    handleStopped(data);
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

    function handleStopped(data) {
        UI.setStatus('Download stopped');
        UI.setStatusDot('error');
        UI.setProgressBarState('error');
        UI.setDetail(`Stopped at ${data.current || 0}/${data.total || 0}`);
        UI.toast('Download stopped. Click Resume to continue.', 'info');

        stopBtn.classList.add('hidden');
        resumeBtn.classList.remove('hidden');
        if (currentSource) {
            currentSource.close();
            currentSource = null;
        }
    }

    function handleRetryComplete(data) {
        UI.setProgress(100);
        UI.setPercent('100%');
        UI.setStatus('Retry complete!');
        UI.setStatusDot('done');
        UI.setProgressBarState('done');
        UI.hideTrackInfo();

        const failedCount = data.failed_tracks?.length || 0;
        const downloadedCount = data.files?.length || 0;
        UI.setDetail(`${downloadedCount} total files, ${failedCount} still failed`);

        UI.showResults(data.files || [], data.failed_tracks || []);

        if (failedCount > 0) {
            UI.toast(`${failedCount} track(s) still failed`, 'error');
        } else {
            UI.toast('All retries succeeded!', 'success');
        }

        stopBtn.classList.add('hidden');
        resumeBtn.classList.add('hidden');
        if (retryAllBtn) {
            retryAllBtn.disabled = false;
            retryAllBtn.textContent = 'RETRY ALL FAILED';
        }
        if (currentSource) {
            currentSource.close();
            currentSource = null;
        }
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
        // Hide stop/resume buttons on completion or error
        stopBtn.classList.add('hidden');
        resumeBtn.classList.add('hidden');
        currentJobId = null;
    }
});
