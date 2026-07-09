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
    const searchSection = document.getElementById('searchSection');
    const searchResults = document.getElementById('searchResults');
    const parallelInput = document.getElementById('parallelInput');
    const parallelMinus = document.getElementById('parallelMinus');
    const parallelPlus = document.getElementById('parallelPlus');
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');
    const downloadSelectedBtn = document.getElementById('downloadSelectedBtn');
    const downloadAllBtn = document.getElementById('downloadAllBtn');

    let selectedBitrate = '320';
    let selectedDir = '';
    let embedLyrics = true;
    let parallelCount = 1;
    let currentSource = null;
    let currentJobId = null;
    let retryJobId = null;
    let isAlbum = false;
    let searchTimeout = null;

    // Init lyrics label
    if (lyricsLabel) {
        lyricsLabel.textContent = 'ON';
        lyricsLabel.style.color = 'var(--accent)';
    }

    // Parallel input controls
    if (parallelInput) {
        parallelInput.addEventListener('input', () => {
            let v = parseInt(parallelInput.value) || 1;
            v = Math.max(1, Math.min(10, v));
            parallelCount = v;
        });
    }
    if (parallelMinus) {
        parallelMinus.addEventListener('click', () => {
            let v = (parseInt(parallelInput.value) || 1) - 1;
            v = Math.max(1, v);
            parallelInput.value = v;
            parallelCount = v;
        });
    }
    if (parallelPlus) {
        parallelPlus.addEventListener('click', () => {
            let v = (parseInt(parallelInput.value) || 1) + 1;
            v = Math.min(10, v);
            parallelInput.value = v;
            parallelCount = v;
        });
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
            const jobId = retryJobId || currentJobId;
            if (!jobId) return;
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

                const result = await API.retryFailed(jobId, failedTracks, isAlbum);
                retryJobId = result.job_id;
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
                        UI.toast(data.error || 'Track retry failed', 'error');
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
        if (!retryBtn) return;
        const jobId = retryJobId || currentJobId;
        if (!jobId) return;

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

                const result = await API.retryFailed(jobId, [track], isAlbum);
                retryJobId = result.job_id;
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
                        UI.toast(data.error || 'Track retry failed', 'error');
                    },
                });
            } catch (err) {
                UI.toast('Retry failed: ' + err.message, 'error');
                retryBtn.disabled = false;
                retryBtn.textContent = 'RETRY';
            }
        })();
    });

    // Search result download button delegation
    document.addEventListener('click', (e) => {
        const dlBtn = e.target.closest('.search-download-btn');
        if (!dlBtn) return;
        const url = dlBtn.dataset.url;
        if (url) downloadFromSearch(url);
    });

    // Select all checkbox
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', () => {
            const checked = selectAllCheckbox.checked;
            searchResults.querySelectorAll('.search-checkbox').forEach(cb => {
                cb.checked = checked;
            });
            updateMassDownloadBtns();
        });
    }

    // Individual checkbox delegation
    searchResults.addEventListener('change', (e) => {
        if (e.target.classList.contains('search-checkbox')) {
            updateMassDownloadBtns();
            const total = searchResults.querySelectorAll('.search-checkbox').length;
            const checked = searchResults.querySelectorAll('.search-checkbox:checked').length;
            selectAllCheckbox.checked = total > 0 && checked === total;
        }
    });

    // Download selected
    if (downloadSelectedBtn) {
        downloadSelectedBtn.addEventListener('click', () => {
            const urls = getSelectedSearchUrls();
            if (urls.length === 0) return;
            startMassDownload(urls);
        });
    }

    // Download all
    if (downloadAllBtn) {
        downloadAllBtn.addEventListener('click', () => {
            const urls = getAllSearchUrls();
            if (urls.length === 0) return;
            startMassDownload(urls);
        });
    }

    function updateMassDownloadBtns() {
        const checkedCount = searchResults.querySelectorAll('.search-checkbox:checked').length;
        if (downloadSelectedBtn) {
            downloadSelectedBtn.disabled = checkedCount === 0;
        }
    }

    function getSelectedSearchUrls() {
        const urls = [];
        searchResults.querySelectorAll('.search-checkbox:checked').forEach(cb => {
            const item = cb.closest('.search-item');
            if (item) {
                const btn = item.querySelector('.search-download-btn');
                if (btn && btn.dataset.url) urls.push(btn.dataset.url);
            }
        });
        return urls;
    }

    function getAllSearchUrls() {
        const urls = [];
        searchResults.querySelectorAll('.search-download-btn').forEach(btn => {
            if (btn.dataset.url) urls.push(btn.dataset.url);
        });
        return urls;
    }

    async function startMassDownload(urls) {
        UI.hideSection('searchSection');
        UI.showSection('progressSection');
        UI.hideSection('filesSection');
        UI.setProgress(0);
        UI.setPercent('0%');
        UI.setStatus(`Starting ${urls.length} downloads...`);
        UI.setDetail('');
        UI.setStatusDot('');
        UI.setProgressBarState('');
        UI.hideTrackInfo();
        stopBtn.classList.add('hidden');
        resumeBtn.classList.add('hidden');

        const outputDir = downloadDirInput.value.trim() || selectedDir;
        let completedJobs = 0;
        const totalJobs = urls.length;

        for (const url of urls) {
            try {
                const result = await API.download(url, selectedBitrate, outputDir, embedLyrics, parallelCount);
                UI.setStatus(`Job ${completedJobs + 1}/${totalJobs} queued...`);
            } catch (err) {
                UI.toast(`Failed to queue: ${err.message}`, 'error');
                completedJobs++;
            }
        }

        UI.setStatus(`${totalJobs} jobs queued. Watching progress...`);
    }

    goBtn.addEventListener('click', startDownload);
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') startDownload();
    });

    async function startDownload() {
        const input = urlInput.value.trim();
        if (!input) {
            UI.toast('Enter a Spotify URL or search for a song', 'error');
            urlInput.focus();
            return;
        }

        const isUrl = /open\.spotify\.com\/(track|playlist|album)\//.test(input);

        if (isUrl) {
            await startUrlDownload(input);
        } else {
            await startSearch(input);
        }
    }

    async function startSearch(query) {
        goBtn.disabled = true;
        goBtn.classList.add('loading');
        goBtn.querySelector('.go-text').textContent = 'SEARCHING';

        UI.hideSection('progressSection');
        UI.hideSection('filesSection');
        UI.showSection('searchSection');
        searchResults.innerHTML = '<div class="search-loading">Searching Spotify...</div>';

        try {
            const data = await API.search(query);
            renderSearchResults(data.results || []);
        } catch (err) {
            searchResults.innerHTML = `<div class="search-empty">${UI.escapeHtml(err.message)}</div>`;
        } finally {
            goBtn.disabled = false;
            goBtn.classList.remove('loading');
            goBtn.querySelector('.go-text').textContent = 'EXEC';
        }
    }

    function renderSearchResults(tracks) {
        if (!tracks.length) {
            searchResults.innerHTML = '<div class="search-empty">No results found</div>';
            return;
        }

        searchResults.innerHTML = '';
        tracks.forEach((track) => {
            const item = document.createElement('div');
            item.className = 'search-item';

            const coverHtml = track.cover
                ? `<img class="search-cover" src="${UI.escapeHtml(track.cover)}" alt="" loading="lazy">`
                : `<div class="search-cover-placeholder">&#9835;</div>`;

            const explicitTag = track.explicit ? '<span class="search-explicit">E</span>' : '';

            item.innerHTML = `
                <input type="checkbox" class="search-checkbox">
                ${coverHtml}
                <div class="search-info">
                    <div class="search-title">${explicitTag}${UI.escapeHtml(track.title)}</div>
                    <div class="search-meta">${UI.escapeHtml(track.artist)}${track.album ? ' &middot; ' + UI.escapeHtml(track.album) : ''}</div>
                </div>
                <span class="search-duration">${UI.escapeHtml(track.duration)}</span>
                <button class="search-download-btn" data-url="${UI.escapeHtml(track.url)}">DOWNLOAD</button>
            `;
            searchResults.appendChild(item);
        });

        // Reset select all
        if (selectAllCheckbox) selectAllCheckbox.checked = false;
        updateMassDownloadBtns();
    }

    async function downloadFromSearch(spotifyUrl) {
        UI.hideSection('searchSection');
        await startUrlDownload(spotifyUrl);
    }

    async function startUrlDownload(url) {
        goBtn.disabled = true;
        goBtn.classList.add('loading');
        goBtn.querySelector('.go-text').textContent = 'LOADING';

        UI.showSection('progressSection');
        UI.hideSection('filesSection');
        UI.hideSection('searchSection');
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
            const result = await API.download(url, selectedBitrate, outputDir, embedLyrics, parallelCount);
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
            if (parallelCount > 1) {
                UI.setStatus(`Downloading ${current}/${total} (${parallelCount} parallel)`);
            } else {
                UI.setStatus(`Downloading ${current}/${total}`);
            }
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
            retryJobId = currentJobId;
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
        const skippedCount = data.skipped_files?.length || 0;
        UI.setDetail(`${downloadedCount} downloaded, ${skippedCount} skipped, ${failedCount} failed`);

        const allFiles = (data.files || []).concat((data.skipped_files || []).map(f => '(exists) ' + f));
        UI.showResults(allFiles, data.failed_tracks || []);

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
