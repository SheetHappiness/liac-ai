import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { PcmPlayback, playAudio } from './voice.mjs';
import { loadSpeech, saveSpeech, speechSsml, updateSpeech, voiceLocale } from './speech-settings.cjs';

test('Azure preferences and key survive restart and drive escaped SSML', t => {
    const directory = mkdtempSync(join(tmpdir(), 'liac-speech-'));
    const file = join(directory, '.env');
    t.after(() => {
        rmSync(file, { force: true });
        rmdirSync(directory);
    });
    const initial = loadSpeech(file, {});
    assert.deepEqual(initial, { key: '', region: 'eastus', voice: 'en-GB-MaisieNeural', pitch: -10, rate: 1.05 });
    const settings = updateSpeech(initial, {
        key: 'test-key', region: 'EastUS', voice: 'uk-UA-PolinaNeural', pitch: -15, rate: 1.25,
    });
    saveSpeech(file, settings);
    const restored = loadSpeech(file, { SPEECH_KEY: 'ignored-env-key' });
    assert.deepEqual(restored, settings);
    assert.throws(() => updateSpeech(restored, { ...restored, voice: '"><break/>' }));
    assert.throws(() => updateSpeech(restored, { ...restored, key: 'abc\nSPEECH_KEY=bad' }));
    assert.match(speechSsml('A & B <break/>', restored),
        /xml:lang="uk-UA"><voice name="uk-UA-PolinaNeural"><prosody pitch="-15%" rate="1.25">A &amp; B &lt;break\/&gt;/);
    const voice = 'en-US-Dana:DragonHDOmniLatestNeural';
    const changed = updateSpeech(restored, { ...restored, key: '', voice, pitch: 20 });
    saveSpeech(file, changed);
    assert.deepEqual(loadSpeech(file, {}), { ...restored, voice, pitch: 20 });
    assert.match(speechSsml('Hello.', changed),
        /xml:lang="en-US"><voice name="en-US-Dana:DragonHDOmniLatestNeural"><prosody pitch="\+20%" rate="1.25">/);
    for (const id of ['hu-HU-Réka:MAI-Voice-2', 'en-US-Iris:MAI-Voice-2.1-Flash']) {
        const catalogVoice = updateSpeech(changed, { ...changed, key: '', voice: id });
        saveSpeech(file, catalogVoice);
        assert.equal(loadSpeech(file, {}).voice, id);
        assert.ok(speechSsml('Hello.', catalogVoice).includes(`<voice name="${id}">`));
    }
});

test('PCM starts from the first chunk, preserves order and stops queued audio', () => {
    const sources = [];
    const context = {
        currentTime: 1,
        createBuffer(_channels, frames, rate) {
            const samples = new Float32Array(frames);
            return { duration: frames / rate, getChannelData: () => samples };
        },
        createBufferSource() {
            const source = { connect() {}, disconnect() {}, start(at) { this.at = at; },
                stop() { this.stopped = true; } };
            sources.push(source);
            return source;
        },
    };
    const playback = new PcmPlayback(context);
    const pcm = new Int16Array([-32_768, 0, 16_384]).buffer;
    playback.push(pcm, 24_000);
    assert.equal(sources[0].at, 1.025);
    assert.deepEqual([...sources[0].buffer.getChannelData(0)], [-1, 0, 0.5]);
    playback.push(pcm, 24_000);
    assert.equal(sources[1].at, sources[0].at + sources[0].buffer.duration);
    assert.throws(() => playback.push(new ArrayBuffer(3), 24_000));
    playback.clear();
    assert.ok(sources.every(source => source.stopped));
    context.currentTime = 2;
    playback.push(pcm, 24_000);
    assert.equal(sources[2].at, 2.025);
    playback.clear();
});

test('main streams Luna deltas directly to Azure and forwards only current PCM', () => {
    const frames = [];
    const synthesizers = [];
    const handlers = new Map();
    const require = createRequire(import.meta.url);
    const sdk = {
        Connection: {
            fromSynthesizer: synth => {
                synth.connectionWrappers = (synth.connectionWrappers || 0) + 1;
                return { openConnection: (_ready, failed) => {
                    synth.opens = (synth.opens || 0) + 1;
                    failed('test connection failure');
                } };
            },
        },
        SpeechConfig: { fromEndpoint: (url, key) => ({ url, key }) },
        SpeechSynthesisOutputFormat: { Raw24Khz16BitMonoPcm: 'pcm' },
        SpeechSynthesisRequestInputType: { TextStream: 3 },
        SpeechSynthesisRequest: class {
            writes = [];
            inputStream = {
                write: text => this.writes.push(text),
                close: () => { this.closed = true; },
            };
        },
        ResultReason: { SynthesizingAudioCompleted: 'completed' },
        SpeechSynthesizer: class {
            constructor(config) { this.config = config; synthesizers.push(this); }
            speakAsync(request, done) { this.request = request; this.done = done; }
            close() { this.closed = true; }
        },
    };
    const mocks = {
        electron: { app: { requestSingleInstanceLock: () => false, quit() {}, on() {} },
            ipcMain: { handle: (name, handler) => handlers.set(name, handler) } },
        'microsoft-cognitiveservices-speech-sdk': sdk,
        './speech-settings.cjs': { loadSpeech: () => ({ key: 'test-key', region: 'germanywestcentral',
            voice: 'en-GB-MaisieNeural', pitch: -10, rate: 1.05 }), voiceLocale },
    };
    const source = readFileSync(new URL('./main.cjs', import.meta.url), 'utf8');
    const sender = { mainFrame: {}, send: (_channel, _stream, frame) => frames.push(frame) };
    const main = runInNewContext(source + `
        window = testWindow;
        ready = true;
        live = { stdin: { writable: true, write() {} } };
        ({ streamSpeech, cancelSynthesis });
    `, {
        require: name => mocks[name] ?? require(name), __dirname: tmpdir(),
        process: { env: {}, platform: process.platform }, URL, setTimeout, clearTimeout,
        testWindow: { isDestroyed: () => false, webContents: sender },
    });
    let input = 0;
    const submit = speak => {
        const id = String(++input).padStart(36, '0');
        const event = { sender, senderFrame: sender.mainFrame };
        handlers.get('hub:submit')(event, id, 'Test transcript', speak);
        return 'hub_' + id;
    };
    const start = (id, perceptionId = submit(true)) => {
        main.streamSpeech({ type: 'journal', event: { kind: 'user.message.completed', turn_id: id,
            payload: { perception_ids: [perceptionId] } } });
    };
    const delta = (id, text) => main.streamSpeech({ type: 'preview', turn_id: id, text });
    const emit = synth => synth.synthesizing?.(null, { result: { audioData: new ArrayBuffer(2) } });
    try {
        submit(false);
        assert.equal(synthesizers.length, 0);
        const firstInput = submit(true);
        const old = synthesizers[0];
        assert.equal(old?.opens, 1);
        assert.equal(old.request, undefined);
        start('old', firstInput);
        delta('old', 'Hel');
        const staleCallback = old.synthesizing;
        assert.match(old.config.url.href, /germanywestcentral.*websocket\/v2/);
        assert.equal(old.config.speechSynthesisVoiceName, 'en-GB-MaisieNeural');
        assert.equal(old.config.speechSynthesisLanguage, 'en-GB');
        assert.equal(old.request.pitch, '-10%');
        assert.equal(old.request.rate, '+5%');
        assert.deepEqual(old.request.writes, ['Hel']);
        emit(old);
        assert.deepEqual(frames.map(frame => [frame.type, frame.turn_id]), [['voice_pcm', 'old']]);
        main.cancelSynthesis();
        assert.ok(old.closed);
        start('new');
        delta('old', 'ignored');
        delta('new', 'New');
        staleCallback(null, { result: { audioData: new ArrayBuffer(2) } });
        const current = synthesizers[1];
        delta('new', ' sentence.');
        main.streamSpeech({ type: 'journal', event: { kind: 'character.reply.completed', turn_id: 'new',
            payload: { action: 'speak', text: 'New sentence. End.' } } });
        assert.deepEqual(current.request.writes, ['New', ' sentence.', ' End.']);
        assert.ok(current.request.closed);
        emit(current);
        current.done({ reason: 'completed', audioData: new ArrayBuffer(8) });
        assert.deepEqual(frames.map(frame => [frame.type, frame.turn_id]), [['voice_pcm', 'old'], ['voice_pcm', 'new']]);
        start('silent');
        main.streamSpeech({ type: 'journal', event: { kind: 'character.reply.completed', turn_id: 'silent',
            payload: { action: 'stay_silent', text: '' } } });
        assert.equal(synthesizers.length, 2);
        assert.equal(current.connectionWrappers, 1);
        start('error');
        delta('error', 'Another reply');
        current.done({ reason: 'failed' });
        assert.equal(frames.at(-1).type, 'voice_failed');
        assert.equal(frames.at(-1).turn_id, 'error');
    } finally {
        main.cancelSynthesis();
    }
});
test('an unavailable output clock does not stall the next fragment or report a measurement', async () => {
    const source = { connect() {}, disconnect() {}, start() {} };
    const context = { currentTime: 1, outputLatency: 0, createBufferSource: () => source,
        getOutputTimestamp: () => ({ contextTime: 0, performanceTime: 0 }) };
    const ended = new Promise(resolve => playAudio(context, {}, () => assert.fail('No output timestamp'), resolve));
    source.onended();
    await ended;
});
