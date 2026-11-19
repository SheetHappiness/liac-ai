import assert from 'node:assert/strict';
import { test } from 'node:test';

import { VoicePlayback, playAudio } from './voice.mjs';

const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
    const requests = [], played = [], latency = [], errors = [];
    let now = 1000;
    let cancellations = 0;
    const voice = new VoicePlayback({
        now: () => now,
        synthesize: text => new Promise(resolve => requests.push({ text, resolve })),
        cancelSynthesis: () => { cancellations++; },
        play: (audio, onStart, onEnd) => {
            const item = { audio, onStart, onEnd, stopped: false };
            played.push(item);
            return () => { item.stopped = true; };
        },
        onLatency: (id, result) => latency.push({ id, ...result }),
        onError: () => errors.push('unavailable'),
    });
    const begin = (id, at = now) => {
        const before = now;
        now = at;
        voice.submit('input-' + id);
        voice.begin(id, ['input-' + id]);
        now = before;
    };
    return { voice, requests, played, latency, errors, time: value => { now = value; },
        begin, cancellations: () => cancellations };
}

test('plays a split sentence before commit and synthesizes one segment ahead', async () => {
    const { voice, begin, requests, played, latency, time } = fixture();
    begin('turn', 600);
    voice.delta('turn', 'Hey, Lu');
    assert.equal(requests.length, 0);
    time(1050);
    voice.delta('turn', 'na! Look at that. Wild');
    assert.deepEqual(requests.map(r => r.text), ['Hey, Luna!']);
    requests[0].resolve('audio-1');
    await tick();
    assert.deepEqual(played.map(p => p.audio), ['audio-1']);
    played[0].onStart(1100);
    assert.deepEqual(latency, [{ id: 'turn', transcriptMs: 500, previewMs: 100 }]);
    assert.deepEqual(requests.map(r => r.text), ['Hey, Luna!', 'Look at that.']);
    requests[1].resolve('audio-2');
    await tick();
    voice.finish('turn', 'Hey, Luna! Look at that. Wild');
    assert.equal(played.length, 1);
    assert.equal(requests.length, 2);
    played[0].onEnd();
    assert.deepEqual(played.map(p => p.audio), ['audio-1', 'audio-2']);
    assert.equal(requests[2].text, 'Wild');
    requests[2].resolve('audio-3');
    await tick();
    played[1].onEnd();
    assert.deepEqual(played.map(p => p.audio), ['audio-1', 'audio-2', 'audio-3']);
});

test('interruption stops playback and ignores late audio and deltas for that turn', async () => {
    const { voice, begin, requests, played, latency, cancellations } = fixture();
    begin('old');
    voice.delta('old', 'First. Second!');
    requests[0].resolve('first');
    await tick();
    voice.clear();
    assert.equal(played[0].stopped, true);
    assert.equal(cancellations(), 1);
    voice.delta('old', ' Third.');
    voice.finish('old', 'First. Second! Third.');
    begin('new', 900);
    voice.finish('new', 'New reply');
    requests[1].resolve('stale');
    requests[2].resolve('new');
    await tick();
    played[0].onStart(1040);
    played[1].onStart(1050);
    assert.deepEqual(played.map(p => p.audio), ['first', 'new']);
    assert.deepEqual(latency, [{ id: 'new', transcriptMs: 150, previewMs: null }]);
});

test('silence, failure and a mismatched committed prefix discard provisional audio', async () => {
    for (const final of [null, 'Different.']) {
        const { voice, begin, requests, played } = fixture();
        begin('turn');
        voice.delta('turn', 'Provisional!');
        voice.finish('turn', final);
        requests[0].resolve('stale');
        await tick();
        assert.deepEqual(played, []);
    }
});

test('a synthesis error drops that reply and leaves the next turn usable', async () => {
    const { voice, begin, requests, played, errors } = fixture();
    begin('turn');
    voice.finish('turn', 'Text remains in chat.');
    requests[0].resolve(null);
    await tick();
    assert.equal(errors.length, 1);
    begin('next');
    voice.finish('next', 'Next');
    requests[1].resolve('next');
    await tick();
    assert.deepEqual(played.map(p => p.audio), ['next']);
});

test('only a batch containing the latest submission can start speech', () => {
    const { voice, requests } = fixture();
    voice.submit('old-input');
    voice.submit('new-input');
    voice.begin('old-turn', ['old-input']);
    voice.delta('old-turn', 'Stale!');
    voice.finish('old-turn', 'Stale!');
    assert.equal(requests.length, 0);
    voice.begin('new-turn', ['other-input', 'new-input']);
    voice.delta('new-turn', 'Current!');
    assert.deepEqual(requests.map(r => r.text), ['Current!']);
});

test('a trailing period gets lookahead so a streamed decimal stays in one sentence', () => {
    const { voice, begin, requests } = fixture();
    begin('turn');
    voice.delta('turn', 'The price is 3.');
    assert.equal(requests.length, 0);
    voice.delta('turn', '14 dollars. That is low.');
    assert.deepEqual(requests.map(r => r.text), ['The price is 3.14 dollars.']);
});

test('an unavailable output clock does not stall the next fragment or report a measurement', async () => {
    const source = { connect() {}, disconnect() {}, start() {} };
    const context = { currentTime: 1, outputLatency: 0, createBufferSource: () => source,
        getOutputTimestamp: () => ({ contextTime: 0, performanceTime: 0 }) };
    const ended = new Promise(resolve => playAudio(context, {}, () => assert.fail('No output timestamp'), resolve));
    source.onended();
    await ended;
});
