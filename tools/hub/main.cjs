const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const { existsSync } = require('node:fs');
const { readdir, stat } = require('node:fs/promises');
const path = require('node:path');
const { createInterface } = require('node:readline');
const speechSdk = require('microsoft-cognitiveservices-speech-sdk');
const { loadSpeech, updateSpeech, saveSpeech, speechSsml } = require('./speech-settings.cjs');

const { SPEECH_KEY, SPEECH_REGION, LIAC_TTS_VOICE, ...workerEnv } = process.env;
const root = path.resolve(__dirname, '../..');
const speechFile = path.join(root, '.data/hub/.env');
let speech = loadSpeech(speechFile, { SPEECH_KEY, SPEECH_REGION, LIAC_TTS_VOICE });
let synthesizer, connection, synthesis;

function cancelSynthesis() {
    synthesis?.(null);
    const previous = synthesizer;
    synthesizer = undefined;
    connection = undefined;
    previous?.close(undefined, () => {});
}

const runRoot = path.join(root, '.data/hub/runs');
const venv = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.LIAC_PYTHON || (existsSync(venv) ? venv : 'python');
const localBun = path.join(root, '.data/hub/bin', process.platform === 'win32' ? 'bun.exe' : 'bun');
const bun = process.env.LIAC_BUN || (existsSync(localBun) ? localBun : 'bun');
const runId = /^run-[a-f0-9]{32}$/;
let window, live, replay;
let currentRun;
let resumeFrom;
let ready = false;
let quitting = false;
let switching = false;

function deliver(stream, frame) {
    if (window && !window.isDestroyed()) window.webContents.send('hub:frame', stream, frame);
}

function status(state, message, fields = {}) {
    deliver('live', { type: 'status', state, message, ...fields });
}

function worker(args, onFrame, onStop) {
    const child = spawn(python, ['-u', '-m', 'vtuber.hub', ...args], {
        cwd: root, windowsHide: true,
        env: { ...workerEnv, PYTHONPATH: path.join(root, 'src'), PYTHONUTF8: '1' },
        stdio: ['pipe', 'pipe', 'ignore'],
    });
    const lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
    lines.on('line', line => {
        let frame;
        try { frame = JSON.parse(line); } catch { return; }
        if (frame?.v === 1) onFrame(frame);
    });
    child.stdin.on('error', () => {});
    child.on('error', () => {});
    child.once('close', code => { lines.close(); onStop(code); });
    return child;
}

function start(resume) {
    if (live || quitting) return;
    resumeFrom = resume;
    ready = false;
    currentRun = undefined;
    let reportedError = false;
    status('starting', 'Checking the Luna bridge and sign-in.', { resuming: Boolean(resume) });
    const args = ['--bun', bun];
    if (resume) args.push('--resume', resume);
    live = worker(args, frame => {
        if (frame.type === 'status') {
            ready = frame.state === 'ready';
            reportedError = frame.state === 'error';
            if (ready) {
                currentRun = frame.run;
                resumeFrom = undefined;
            }
        }
        if (!quitting) deliver('live', frame.type === 'status' && frame.state === 'ready'
            ? { ...frame, voice_enabled: Boolean(speech.key) } : frame);
    }, code => {
        cancelSynthesis();
        live = undefined;
        ready = false;
        if (!quitting && !switching && !reportedError) {
            status('error', code === -4058 || code === -2
                ? 'Install Python 3.12 or newer, or set LIAC_PYTHON.'
                : 'Liac stopped. Check Python 3.12+, Bun, and the bridge setup, then retry.');
        }
        if (!quitting && !switching) deliver('live', { type: 'retry_available' });
    });
}

function stopLive(child) {
    return new Promise(resolve => {
        const timeout = setTimeout(() => {
            if (process.platform === 'win32' && child.pid) {
                const kill = spawn(path.join(process.env.SystemRoot || 'C:/Windows', 'System32/taskkill.exe'),
                    ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
                kill.on('error', () => child.kill());
                kill.on('close', code => { if (code !== 0) child.kill(); });
            } else {
                child.kill();
            }
        }, 18_000);
        child.once('close', () => { clearTimeout(timeout); resolve(); });
        child.stdin.end();
    });
}

function command(frame) {
    if (!ready || quitting || !live?.stdin.writable || live.stdin.writableNeedDrain) {
        throw new Error('Runtime unavailable or busy. Try again.');
    }
    live.stdin.write(JSON.stringify({ v: 1, ...frame }) + '\n');
}

function handle(name, fn) {
    ipcMain.handle('hub:' + name, (event, ...args) => {
        if (!window || event.sender !== window.webContents || !event.senderFrame ||
            event.senderFrame !== window.webContents.mainFrame) throw new Error('Unauthorized request');
        return fn(...args);
    });
}

handle('start', () => {
    if (!switching) start(resumeFrom);
});
handle('submit', (id, text) => {
    if (typeof id !== 'string' || !/^[a-f0-9-]{36}$/.test(id) ||
        typeof text !== 'string' || !text.trim() || text.length > 8000 || !text.isWellFormed()) {
        throw new Error('Enter a valid transcript of 1 to 8,000 characters.');
    }
    command({ type: 'submit_transcript', id, text });
});
handle('voice-settings', () => {
    const { key, ...settings } = speech;
    return { ...settings, hasKey: Boolean(key) };
});
handle('voice-catalog', async draft => {
    const { key, region } = updateSpeech(speech, { ...speech, key: draft?.key, region: draft?.region });
    const config = speechSdk.SpeechConfig.fromSubscription(key, region);
    const catalog = new speechSdk.SpeechSynthesizer(config, null);
    try {
        const result = await catalog.getVoicesAsync();
        if (result.reason !== speechSdk.ResultReason.VoicesListRetrieved) {
            throw new Error('Azure voice catalog unavailable.');
        }
        return result.voices
            .filter(voice => voice.gender === speechSdk.SynthesisVoiceGender.Female)
            .map(voice => ({ id: voice.shortName, name: voice.displayName, locale: voice.localeName || voice.locale }));
    } catch {
        throw new Error('Azure voice catalog unavailable.');
    } finally {
        catalog.close(undefined, () => {});
    }
});
handle('configure-voice', draft => {
    if (quitting) throw new Error('Hub is closing.');
    const next = updateSpeech(speech, draft);
    try { saveSpeech(speechFile, next); }
    catch { throw new Error('Could not save local Azure Speech settings.'); }
    cancelSynthesis();
    speech = next;
});
handle('preview-voice', draft => synthesize('Hi, this is how I sound with these settings.', updateSpeech(speech, draft)));
handle('synthesize', text => {
    if (!ready || switching || typeof text !== 'string' ||
        !text.trim() || text.length > 16_384 || !text.isWellFormed()) return null;
    return synthesize(text, speech);
});

function synthesize(text, settings) {
    if (!settings.key || quitting || synthesis) return null;
    if (connection && (connection.key !== settings.key || connection.region !== settings.region)) {
        cancelSynthesis();
    }
    return new Promise(resolve => {
        const finish = audio => {
            clearTimeout(timeout);
            if (synthesis !== finish) return;
            synthesis = undefined;
            resolve(audio);
        };
        const timeout = setTimeout(cancelSynthesis, 12_000);
        synthesis = finish;
        try {
            if (!synthesizer) {
                const config = speechSdk.SpeechConfig.fromSubscription(settings.key, settings.region);
                config.speechSynthesisOutputFormat = speechSdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm;
                synthesizer = new speechSdk.SpeechSynthesizer(config, null);
                connection = settings;
            }
            const failed = () => { if (synthesis === finish) cancelSynthesis(); };
            synthesizer.speakSsmlAsync(speechSsml(text, settings), result => {
                if (result.reason === speechSdk.ResultReason.SynthesizingAudioCompleted && result.audioData?.byteLength) {
                    finish(result.audioData);
                } else failed();
            }, failed);
        } catch {
            cancelSynthesis();
        }
    });
}
handle('cancel-voice', cancelSynthesis);
handle('context', enabled => {
    if (typeof enabled !== 'boolean') throw new Error('Expected a recording preference.');
    command({ type: 'record_context', enabled });
});
handle('runs', async () => {
    const dirs = await readdir(runRoot, { withFileTypes: true }).catch(error => {
        if (error.code === 'ENOENT') return [];
        throw error;
    });
    const runs = await Promise.all(dirs.filter(dir => dir.isDirectory() && runId.test(dir.name) &&
        dir.name !== currentRun).map(async dir => {
        const db = await stat(path.join(runRoot, dir.name, 'journal.sqlite3')).catch(() => null);
        return db?.isFile() ? { id: dir.name, time: db.birthtime.toISOString() } : null;
    }));
    return runs.filter(Boolean).sort((a, b) => b.time.localeCompare(a.time));
});
handle('replay', (id, token) => {
    if (id !== null && (typeof id !== 'string' || !runId.test(id) || id === currentRun ||
        !Number.isSafeInteger(token))) throw new Error('Select a previous run.');
    const previous = replay;
    replay = undefined;
    previous?.kill();
    if (id === null) return;
    const child = worker(['--replay', id], frame => {
        if (child === replay) deliver(token, frame);
    }, code => {
        if (child !== replay) return;
        replay = undefined;
        deliver(token, { type: 'replay_end', ok: code === 0 });
    });
    replay = child;
});
handle('resume', async id => {
    if (typeof id !== 'string' || !runId.test(id) || id === currentRun ||
        quitting || switching || (live && !ready)) throw new Error('Select a previous run.');
    const source = await stat(path.join(runRoot, id, 'journal.sqlite3')).catch(() => null);
    if (!source?.isFile() || quitting || switching || id === currentRun || (live && !ready)) {
        throw new Error('The selected run is unavailable.');
    }
    switching = true;
    ready = false;
    cancelSynthesis();
    const previous = replay;
    replay = undefined;
    previous?.kill();
    try {
        if (live) await stopLive(live);
        start(id);
    } finally {
        switching = false;
    }
});

if (!app.requestSingleInstanceLock()) {
    app.quit();
} else {
    app.on('second-instance', () => {
        if (window?.isMinimized()) window.restore();
        window?.focus();
    });
    app.whenReady().then(() => {
        window = new BrowserWindow({
            title: 'Liac Hub', width: 1360, height: 870, minWidth: 760, minHeight: 520,
            backgroundColor: '#f5f6fd', autoHideMenuBar: true,
            webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true,
                contextIsolation: true, nodeIntegration: false },
        });
        window.webContents.on('will-navigate', event => event.preventDefault());
        window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
        window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
        window.webContents.session.setPermissionCheckHandler(() => false);
        window.webContents.on('render-process-gone', () => app.quit());
        window.loadFile(path.join(__dirname, 'index.html'));
    });
}

app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
    cancelSynthesis();
    replay?.kill();
    if (!live) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    ready = false;
    if (switching) live.once('close', () => app.quit());
    else stopLive(live).then(() => app.quit());
});
