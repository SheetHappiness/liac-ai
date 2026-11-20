const { randomUUID } = require('node:crypto');
const { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } = require('node:fs');
const { dirname } = require('node:path');
const { parseEnv } = require('node:util');

const validKey = /^[A-Za-z0-9_-]{1,256}$/;
const validRegion = /^[a-z0-9]{1,32}$/i;
const validVoice = /^[\p{L}\p{M}\p{N}:._-]{1,100}$/u;

function loadSpeech(file, env) {
    let saved = {};
    try {
        saved = parseEnv(readFileSync(file, 'utf8'));
    } catch (error) {
        if (error.code !== 'ENOENT') console.warn('Could not read local Azure Speech settings.');
    }
    const region = saved.SPEECH_REGION || env.SPEECH_REGION;
    const voice = saved.LIAC_TTS_VOICE || env.LIAC_TTS_VOICE;
    const key = saved.SPEECH_KEY || env.SPEECH_KEY?.trim();
    const pitch = Number(saved.LIAC_TTS_PITCH ?? 30);
    const rate = Number(saved.LIAC_TTS_RATE ?? 1);
    return {
        key: validKey.test(key ?? '') ? key : '',
        region: validRegion.test(region ?? '') ? region.toLowerCase() : 'eastus',
        voice: validVoice.test(voice ?? '') ? voice : 'en-US-AshleyNeural',
        pitch: Number.isInteger(pitch) && pitch >= -50 && pitch <= 50 ? pitch : 30,
        rate: rate >= 0.5 && rate <= 2 ? rate : 1,
    };
}

function updateSpeech(current, draft) {
    const { key, region, voice, pitch, rate } = draft || {};
    if (typeof key !== 'string' || !validKey.test(key || current.key) ||
        typeof region !== 'string' || !validRegion.test(region) ||
        typeof voice !== 'string' || !validVoice.test(voice) ||
        !Number.isInteger(pitch) || pitch < -50 || pitch > 50 ||
        !Number.isFinite(rate) || rate < 0.5 || rate > 2) {
        throw new Error('Check the Azure key, region, voice, pitch, and rate.');
    }
    return { key: key || current.key, region: region.toLowerCase(), voice, pitch, rate };
}

function saveSpeech(file, { key, region, voice, pitch, rate }) {
    mkdirSync(dirname(file), { recursive: true });
    const pending = file + '.' + randomUUID() + '.tmp';
    try {
        writeFileSync(pending, [
            `SPEECH_KEY=${key}`, `SPEECH_REGION=${region}`, `LIAC_TTS_VOICE=${voice}`,
            `LIAC_TTS_PITCH=${pitch}`, `LIAC_TTS_RATE=${rate}`, '',
        ].join('\n'), { mode: 0o600, flag: 'wx' });
        renameSync(pending, file);
    }
    finally { rmSync(pending, { force: true }); }
}

function speechSsml(text, { voice, pitch, rate }) {
    const locale = voice.match(/^[a-z]{2,3}(?:-[A-Z][a-z]{3})?-[A-Z]{2}(?=-)/)?.[0] ?? 'en-US';
    const escaped = text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, '')
        .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    return `<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="${locale}">` +
        `<voice name="${voice}"><prosody pitch="${pitch >= 0 ? '+' : ''}${pitch}%" rate="${rate}">${escaped}</prosody></voice></speak>`;
}

module.exports = { loadSpeech, updateSpeech, saveSpeech, speechSsml };
