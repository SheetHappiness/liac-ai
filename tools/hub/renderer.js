import { PcmPlayback } from './voice.mjs';

const ui = Object.fromEntries([...document.querySelectorAll('[id]')].map(node => [node.id, node]));
const names = {
    'perception.enqueued': 'Perception queued',
    'batch.opened': 'Batch opened',
    'batch.closed': 'Batch settled',
    'admission.decided': 'Admission decision',
    'turn.started': 'Consciousness turn started',
    'turn.completed': 'Action committed',
    'turn.failed': 'Turn ended',
    'model.started': 'Luna request started',
    'model.completed': 'Luna request ended',
    'model.bridge_input': 'Bridge input',
    'handoff.started': 'Recap started',
    'handoff.completed': 'Recap finished',
    'handoff.failed': 'Recap failed',
    'handoff.skipped': 'Recap skipped',
    'capture.gap': 'Capture gap',
};
const reasons = {
    fresh_direct_input: 'Fresh direct input',
    no_fresh_direct_input: 'No fresh direct input',
    quiet: 'Quiet window',
    max_window: 'Maximum wait',
    immediate: 'Queued backlog',
    shutdown: 'Runtime shutdown',
};
const clock = new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' });
const calendar = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
const pending = new Map();
let live = session();
let recorded = session();
let isReplay = false;
let token = 0;
let state = 'starting';
let notice = 'Checking the Luna bridge and sign-in.';
let inputError = false;
let replayNotice = '';
let replayLoaded = false;
let switching = false;
let renderPending = false;
let voiceAvailable = false;
let audioContext, playback, voiceInput, speechTurn;
let preview;
let voiceCatalogRequest;

function clearVoice(cancel = true) {
    voiceInput = speechTurn = undefined;
    playback?.clear();
    if (cancel) window.liac.cancelVoice().catch(() => {});
}

function playSpeech(frame) {
    const turn = speechTurn;
    if (turn?.id !== frame.turn_id) return;
    try {
        if (frame.type === 'voice_failed') throw new Error('Azure synthesis failed');
        if (turn.firstPcmAt !== undefined) {
            playback.push(frame.pcm, frame.sample_rate);
            return;
        }
        const firstPcmAt = turn.firstPcmAt = performance.now();
        const latency = {
            previewToPcmMs: turn.previewAt == null ? null : Math.round(firstPcmAt - turn.previewAt),
        };
        live.latency.set(turn.id, latency);
        schedule();
        playback.push(frame.pcm, frame.sample_rate, startedAt => {
            if (speechTurn !== turn) return;
            const elapsed = time => time == null ? null : Math.max(0, Math.round(startedAt - time));
            latency.transcriptMs = elapsed(turn.transcriptAt);
            latency.previewMs = elapsed(turn.previewAt);
            latency.pcmToOutputMs = elapsed(firstPcmAt);
            schedule();
        });
    } catch {
        clearVoice(frame.type !== 'voice_failed');
        ui['voice-status'].textContent = 'TTS unavailable · Text chat active';
    }
}

function voiceEnabled() {
    return state === 'ready' && voiceAvailable && ui['voice-toggle'].checked;
}

function updateVoiceStatus() {
    ui['voice-status'].textContent = state !== 'ready' ? 'STT simulation' :
        !voiceAvailable ? 'TTS off · Configure Azure Speech' :
        voiceEnabled() ? 'STT simulation · Azure TTS' : 'STT simulation · TTS off';
}

function session() {
    return { rows: [], raw: new Map(), messages: [], turns: new Map(), batches: new Map(),
        previews: new Map(), latency: new Map(),
        selected: null, count: 100, chatDirty: true };
}

function node(tag, content, className) {
    const element = document.createElement(tag);
    if (content != null) element.textContent = content;
    if (className) element.className = className;
    return element;
}

function current() { return isReplay ? recorded : live; }

function schedule() {
    if (renderPending) return;
    renderPending = true;
    requestAnimationFrame(() => { renderPending = false; render(); });
}

function select(row) {
    current().selected = row;
    schedule();
}

function selectTurn(turnId) {
    const turn = current().turns.get(turnId);
    if (!turn) return;
    const trace = current().batches.get(turn.batch_id);
    const row = trace?.findLast(item => item.kind.startsWith('turn.') && item.kind !== 'turn.started') ||
        trace?.find(item => item.kind === 'admission.decided');
    ui.filter.value = '';
    if (row) {
        current().count = Math.max(current().count, current().rows.length - current().rows.indexOf(row));
        select(row);
        requestAnimationFrame(() => ui.timeline.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'nearest' }));
    } else {
        select({ kind: 'Journal turn', data: { turn_id: turnId, batch_id: turn.batch_id } });
    }
}

function rowSummary(row) {
    const data = row.data || {};
    if (row.kind === 'admission.decided') return data.admitted ? 'Run mind' : 'Skip';
    if (data.action) return data.action;
    if (row.kind === 'batch.closed') return reasons[data.reason] || data.reason;
    return data.status || data.perception_kind || data.kind || '';
}

function renderTimeline(view) {
    const filter = ui.filter.value.split('|');
    const filtered = ui.filter.value
        ? view.rows.filter(row => row.kind === 'capture.gap' || filter.includes(row.kind.split('.')[0]))
        : view.rows;
    ui.count.textContent = `${view.rows.length} ${view.rows.length === 1 ? 'event' : 'events'}`;
    const items = filtered.slice(-view.count).reverse().map(row => {
        const button = node('button', null, 'trace-row');
        if (view.selected === row) button.setAttribute('aria-current', 'true');
        const timestamp = Date.parse(row.time);
        const stamp = Number.isFinite(timestamp) ? clock.format(timestamp) : '—';
        button.append(node('time', stamp), node('span', names[row.kind] || row.kind), node('small', rowSummary(row)));
        button.onclick = () => select(row);
        return button;
    });
    if (filtered.length > view.count) {
        const earlier = node('button', 'Show earlier events');
        earlier.onclick = () => { view.count += 100; schedule(); };
        items.push(earlier);
    }
    if (!items.length) items.push(node('p', isReplay && replayNotice ? replayNotice :
        ui.filter.value ? 'No matching events.' : 'Events will appear here.', 'empty'));
    const focusIndex = Array.prototype.indexOf.call(ui.timeline.children, document.activeElement);
    const focusRow = ui.timeline.children[focusIndex]?.traceRow;
    items.forEach((element, index) => { element.traceRow = filtered[filtered.length - index - 1]; });
    ui.timeline.replaceChildren(...items);
    if (focusIndex >= 0) {
        const focus = focusRow ? items.find(element => element.traceRow === focusRow) : items.at(-1);
        focus?.focus({ preventScroll: true });
    }
}

function renderDetails(view) {
    const row = view.selected;
    ui['clear-selection'].hidden = !row;
    ui['detail-title'].textContent = row ? (names[row.kind] || row.kind) : 'Event details';
    if (!row) {
        ui['detail-body'].replaceChildren(node('p', 'Select an event or a chat message to inspect it.'));
        return;
    }
    const data = row.data || {};
    const batch = view.batches.get(data.batch_id || row.request_id) || [];
    const admission = batch.find(item => item.kind === 'admission.decided')?.data;
    const close = batch.find(item => item.kind === 'batch.closed')?.data;
    const turnId = data.turn_id || admission?.turn_id;
    const turn = view.turns.get(turnId);
    const modelStart = batch.find(item => item.kind === 'model.started')?.data;
    const modelEnd = batch.find(item => item.kind === 'model.completed')?.data;
    const finish = batch.find(item => item.kind === 'turn.completed' || item.kind === 'turn.failed')?.data;
    const ids = turn?.perception_ids || close?.perception_ids;
    const inputs = (Array.isArray(ids) ? ids : [row.request_id]).map(id => view.raw.get(id)).filter(Boolean);
    const content = [];
    if (row.capture_gap) content.push(node('p', row.capture_gap));
    if (admission) content.push(node('p', `${admission.admitted ? 'Run mind' : 'Skip'} · ${reasons[admission.reason] || admission.reason}`));
    if (close) content.push(node('p', `Batch settled · ${reasons[close.reason] || close.reason}`));
    if (modelStart && modelEnd) {
        const elapsed = Date.parse(modelEnd.ended_at) - Date.parse(modelStart.started_at);
        content.push(node('p', `Luna duration · ${Math.max(0, elapsed).toLocaleString()} ms`));
    }
    if (finish) content.push(node('p', `Outcome · ${finish.action || finish.status}`));
    const latency = view.latency.get(turnId);
    if (latency?.transcriptMs != null) content.push(node('p',
        `Transcript to audio output · ${latency.transcriptMs.toLocaleString()} ms (estimated)`));
    if (latency?.previewMs != null) content.push(node('p',
        `First speech preview to audio output · ${latency.previewMs.toLocaleString()} ms (estimated)`));
    if (latency?.previewToPcmMs != null) content.push(node('p',
        `First speech preview to first PCM · ${latency.previewToPcmMs.toLocaleString()} ms`));
    if (latency?.pcmToOutputMs != null) content.push(node('p',
        `First PCM to audio output · ${latency.pcmToOutputMs.toLocaleString()} ms (estimated)`));
    for (const input of inputs) {
        content.push(node('h3', `${input.source} · ${input.kind} · ${input.delivery}`),
            node('pre', input.content));
    }
    const preview = view.previews.get(turnId);
    if (preview) content.push(node('h3', 'Provisional speech'), node('pre', preview));
    content.push(node('h3', row.kind === 'model.bridge_input' ? 'Exact Python → Bun request content' : 'Trace payload'),
        node('pre', JSON.stringify(data, null, 2)));
    ui['detail-body'].replaceChildren(...content);
}

function renderChat(view) {
    const draft = view.draft;
    if (!view.chatDirty && !draft) return;
    const atBottom = ui.messages.scrollHeight - ui.messages.scrollTop - ui.messages.clientHeight < 40;
    if (!view.chatDirty && draft.button?.isConnected) {
        draft.button.lastChild.data = view.previews.get(draft.id);
        if (atBottom) ui.messages.scrollTop = ui.messages.scrollHeight;
        return;
    }
    view.chatDirty = false;
    const focused = document.activeElement.dataset?.eventId;
    const items = view.messages.map(event => {
        const input = event.kind === 'user.message.completed';
        const speech = event.kind === 'character.reply.completed' && event.payload.action === 'speak';
        const labels = { 'character.reply.completed': 'Stayed silent',
            'character.reply.failed': 'Turn failed', 'character.reply.cancelled': 'Turn cancelled' };
        const button = node('button', input || speech ? null : labels[event.kind],
            input || speech ? `bubble${input ? ' user' : ''}` : 'outcome');
        if (input || speech) button.append(node('strong', input ? 'You · STT' : 'Luna · TTS'),
            document.createTextNode(event.payload.text));
        button.dataset.eventId = event.event_id;
        button.onclick = () => selectTurn(event.turn_id);
        return button;
    });
    if (draft) {
        draft.button ??= node('button', null, 'bubble');
        draft.button.replaceChildren(node('strong', 'Luna · TTS'),
            document.createTextNode(view.previews.get(draft.id)));
        draft.button.dataset.eventId = draft.id;
        draft.button.onclick = () => selectTurn(draft.id);
        items.push(draft.button);
    }
    if (!items.length) items.push(node('p', isReplay ? 'No messages in this run.' :
        'Send a transcript to start the conversation.', 'empty'));
    ui.messages.replaceChildren(...items);
    if (atBottom) ui.messages.scrollTop = ui.messages.scrollHeight;
    if (focused) items.find(item => item.dataset.eventId === focused)?.focus({ preventScroll: true });
}

function render() {
    const view = current();
    ui['live-tab'].setAttribute('aria-pressed', String(!isReplay));
    ui['replay-tab'].setAttribute('aria-pressed', String(isReplay));
    ui.runs.hidden = !isReplay;
    ui.resume.hidden = !isReplay;
    ui.resume.disabled = switching || !replayLoaded || state === 'starting';
    ui['capture-setting'].hidden = isReplay;
    ui.capture.disabled = state !== 'ready';
    ui.status.dataset.state = state;
    ui.status.lastElementChild.textContent = { ready: 'Ready', starting: 'Starting', error: 'Offline' }[state];
    ui.transcript.disabled = isReplay || state !== 'ready';
    ui['voice-toggle'].disabled = ui.transcript.disabled;
    ui.submit.disabled = ui.transcript.disabled || !ui.transcript.value.trim();
    ui.notice.textContent = isReplay ? replayNotice : notice || (pending.size > 0 ?
        `${pending.size} waiting for batch` : 'Ready for an STT transcript.');
    ui.notice.dataset.error = String(!isReplay && (state === 'error' || inputError));
    renderTimeline(view);
    renderDetails(view);
    renderChat(view);
}

function receive(stream, frame) {
    if (stream !== 'live' && (stream !== token || !isReplay)) return;
    if (stream === 'live' && frame.type === 'status' && frame.resuming) {
        clearVoice();
        live = session();
        isReplay = false;
        token++;
        pending.clear();
        ui.capture.checked = false;
        ui.retry.hidden = true;
        inputError = false;
    }
    const view = stream === 'live' ? live : recorded;
    if (frame.type === 'status') {
        if (stream !== 'live') {
            replayNotice = frame.message;
        } else {
            state = frame.state;
            notice = frame.message || '';
            if (state === 'ready') {
                if (!voiceAvailable) ui['voice-toggle'].checked = Boolean(frame.voice_enabled);
                voiceAvailable = Boolean(frame.voice_enabled);
            }
            updateVoiceStatus();
            if (state !== 'ready') {
                clearVoice();
                view.draft = undefined;
                view.chatDirty = true;
            }
            if (state === 'error') {
                pending.clear();
            }
        }
    } else if (frame.type === 'retry_available') {
        ui.retry.hidden = false;
    } else if (frame.type === 'ack' && !frame.accepted) {
        const text = pending.get(frame.id);
        pending.delete(frame.id);
        if (stream === 'live' && voiceInput?.id === 'hub_' + frame.id) voiceInput = undefined;
        if (!ui.transcript.value && text) ui.transcript.value = text;
        notice = frame.message || 'Transcript rejected.';
        inputError = true;
    } else if (frame.type === 'trace') {
        const row = frame.row;
        view.rows.push(row);
        if (row.data?.batch_id) {
            if (!view.batches.has(row.data.batch_id)) view.batches.set(row.data.batch_id, []);
            view.batches.get(row.data.batch_id).push(row);
        }
    } else if (frame.type === 'preview') {
        view.previews.set(frame.turn_id, (view.previews.get(frame.turn_id) || '') + frame.text);
        if (view.draft?.id !== frame.turn_id) view.draft = { id: frame.turn_id };
        if (stream === 'live' && speechTurn?.id === frame.turn_id) speechTurn.previewAt ??= performance.now();
    } else if (frame.type === 'voice_pcm' || frame.type === 'voice_failed') {
        if (stream === 'live' && !isReplay && voiceEnabled()) playSpeech(frame);
        return;
    } else if (frame.type === 'journal') {
        const event = frame.event;
        if (event.kind === 'perception.received') {
            view.raw.set(event.event_id, event.payload);
            if (stream === 'live' && event.event_id.startsWith('hub_')) pending.delete(event.event_id.slice(4));
        } else if (event.kind !== 'character.reply.started') {
            if (event.kind === 'user.message.completed') {
                view.turns.set(event.turn_id, event.payload);
                if (stream === 'live' && !isReplay && voiceInput &&
                    event.payload.perception_ids?.includes(voiceInput.id)) {
                    speechTurn = { id: event.turn_id, transcriptAt: voiceInput.at };
                    voiceInput = undefined;
                }
            } else if (event.kind.startsWith('character.reply.')) {
                if (view.draft?.id === event.turn_id) view.draft = undefined;
                if (stream === 'live' && speechTurn?.id === event.turn_id) {
                    const prefix = view.previews.get(event.turn_id) || '';
                    const spoken = event.kind === 'character.reply.completed' && event.payload.action === 'speak';
                    if (!spoken || !event.payload.text.startsWith(prefix)) clearVoice(false);
                }
            }
            view.messages.push(event);
            view.chatDirty = true;
        }
    } else if (frame.type === 'replay_end' && frame.ok) {
        replayLoaded = true;
        replayNotice = 'Recorded run · Read only';
    } else if (frame.type === 'replay_end') {
        replayNotice = 'Replay could not read this run.';
    }
    schedule();
}

async function loadReplay() {
    const id = ui.runs.value;
    const request = ++token;
    replayLoaded = false;
    recorded = session();
    replayNotice = id ? 'Loading recorded run…' : 'No recorded runs yet.';
    schedule();
    try { await window.liac.replay(id || null, request); }
    catch { if (request === token) { replayNotice = 'Replay unavailable.'; schedule(); } }
}

ui['replay-tab'].onclick = async () => {
    if (isReplay || switching) return;
    clearVoice();
    isReplay = true;
    replayLoaded = false;
    recorded = session();
    replayNotice = 'Loading runs…';
    schedule();
    try {
        const runs = await window.liac.runs();
        if (!isReplay) return;
        ui.runs.replaceChildren(...(runs.length ? runs.map(run => new Option(calendar.format(new Date(run.time)), run.id)) :
            [new Option('No recorded runs', '')]));
        await loadReplay();
    } catch { replayNotice = 'Could not list recorded runs.'; schedule(); }
};
ui['live-tab'].onclick = () => {
    if (!isReplay || switching) return;
    isReplay = false;
    token++;
    live.chatDirty = true;
    window.liac.replay(null).catch(() => {});
    schedule();
};
ui.runs.onchange = loadReplay;
ui.resume.onclick = async () => {
    if (ui.resume.disabled) return;
    switching = true;
    ui.resume.disabled = true;
    ui.runs.disabled = true;
    try {
        await window.liac.resume(ui.runs.value);
    } catch {
        replayNotice = 'The selected run could not be resumed.';
        schedule();
    } finally {
        switching = false;
        ui.runs.disabled = false;
        schedule();
    }
};
ui.filter.onchange = schedule;
ui['clear-selection'].onclick = () => select(null);

function updateVoiceSliders() {
    const pitch = ui['voice-pitch'].valueAsNumber;
    ui['voice-pitch-value'].value = `${pitch > 0 ? '+' : ''}${pitch}%`;
    ui['voice-rate-value'].value = `${ui['voice-rate'].valueAsNumber.toFixed(2)}×`;
}

function voiceCredentials() {
    return {
        key: ui['voice-key'].value.trim(),
        region: ui['voice-region'].value.trim(),
    };
}

function voiceDraft() {
    return {
        ...voiceCredentials(),
        voice: ui['voice-name'].value || ui['voice-custom'].value.trim(),
        pitch: ui['voice-pitch'].valueAsNumber,
        rate: ui['voice-rate'].valueAsNumber,
    };
}

function updateCustomVoice() {
    const knownVoice = Boolean(ui['voice-name'].value);
    ui['voice-custom-field'].hidden = ui['voice-custom'].disabled = knownVoice;
}

function selectVoice(id) {
    const select = ui['voice-name'];
    select.value = id;
    if (!select.value) select.value = '';
    ui['voice-custom'].value = select.value ? '' : id;
    updateCustomVoice();
}

function filterVoices() {
    const terms = ui['voice-search'].value.toLocaleLowerCase().trim().split(/\s+/);
    for (const group of ui['voice-name'].querySelectorAll('optgroup')) {
        for (const option of group.children) {
            const text = `${group.label} ${option.label} ${option.value} ${option.dataset.name || ''}`.toLocaleLowerCase();
            option.hidden = !option.selected && !terms.every(term => text.includes(term));
        }
        group.hidden = ![...group.children].some(option => !option.hidden);
    }
}

function clearVoiceCatalog() {
    voiceCatalogRequest = undefined;
    const id = ui['voice-name'].value || ui['voice-custom'].value;
    ui['voice-catalog'].replaceChildren();
    selectVoice(id);
    filterVoices();
    ui['voice-catalog-status'].textContent = '';
    ui['voice-load'].disabled = false;
}

async function loadVoiceCatalog() {
    if (!ui['voice-region'].reportValidity() || !ui['voice-key'].reportValidity()) return;
    const request = voiceCatalogRequest = {};
    ui['voice-load'].disabled = true;
    ui['voice-catalog-status'].textContent = 'Loading Azure voices…';
    try {
        const catalog = await window.liac.voiceCatalog(voiceCredentials());
        if (voiceCatalogRequest !== request || !ui['voice-setup'].open) return;
        const id = ui['voice-name'].value || ui['voice-custom'].value;
        const group = ui['voice-catalog'];
        group.replaceChildren();
        const ids = new Set([...ui['voice-name'].options].map(option => option.value));
        const voices = new Map(catalog.map(voice => [voice.id, voice]));
        const options = [...voices.values()].sort((a, b) =>
            a.locale.localeCompare(b.locale) || a.id.localeCompare(b.id));
        for (const voice of options) {
            if (ids.has(voice.id)) continue;
            const option = new Option(`${voice.locale} · ${voice.id}`, voice.id);
            option.dataset.name = voice.name;
            group.append(option);
        }
        selectVoice(id);
        filterVoices();
        ui['voice-catalog-status'].textContent = `${voices.size} female voices available in this region`;
    } catch {
        if (voiceCatalogRequest !== request) return;
        ui['voice-catalog-status'].textContent = 'Could not load Azure voices. Check the key and region.';
    } finally {
        if (voiceCatalogRequest === request) ui['voice-load'].disabled = false;
    }
}

function voiceError(message) {
    ui['voice-error'].textContent = message;
    ui['voice-error'].hidden = false;
}

async function openVoiceSettings() {
    if (ui['voice-settings'].disabled || ui['voice-setup'].open) return;
    ui['voice-settings'].disabled = true;
    try {
        const settings = await window.liac.voiceSettings();
        ui['voice-search'].value = '';
        clearVoiceCatalog();
        selectVoice(settings.voice);
        ui['voice-region'].value = settings.region;
        ui['voice-pitch'].value = settings.pitch;
        ui['voice-rate'].value = settings.rate;
        ui['voice-key'].required = !settings.hasKey;
        ui['voice-key'].placeholder = settings.hasKey ? 'Leave blank to keep the saved key' : '';
        ui['voice-error'].hidden = true;
        updateVoiceSliders();
        ui['voice-setup'].showModal();
        if (settings.hasKey) void loadVoiceCatalog();
    } catch {
        ui['voice-status'].textContent = 'Could not open voice settings';
    } finally {
        ui['voice-settings'].disabled = false;
    }
}

function stopVoicePreview() {
    if (!preview) return;
    if (preview.source) preview.source.stop();
    else window.liac.cancelVoice().catch(() => {});
    preview = undefined;
    ui['voice-preview'].disabled = false;
}

ui['voice-settings'].onclick = openVoiceSettings;
ui['voice-name'].onchange = () => {
    updateCustomVoice();
    filterVoices();
};
ui['voice-search'].oninput = filterVoices;
ui['voice-search'].onkeydown = event => {
    if (event.key === 'Enter') event.preventDefault();
};
ui['voice-load'].onclick = loadVoiceCatalog;
ui['voice-region'].oninput = ui['voice-key'].oninput = clearVoiceCatalog;
ui['voice-pitch'].oninput = ui['voice-rate'].oninput = updateVoiceSliders;
ui['voice-toggle'].onchange = () => {
    if (ui['voice-toggle'].checked && !voiceAvailable) {
        ui['voice-toggle'].checked = false;
        void openVoiceSettings();
        return;
    }
    if (!ui['voice-toggle'].checked) {
        clearVoice();
    }
    updateVoiceStatus();
};
ui['voice-cancel'].onclick = () => ui['voice-setup'].close();
ui['voice-setup'].oncancel = event => {
    if (ui['voice-save'].disabled) event.preventDefault();
};
ui['voice-setup'].onclose = () => {
    ui['voice-key'].value = '';
    voiceCatalogRequest = undefined;
    stopVoicePreview();
};
ui['voice-preview'].onclick = async () => {
    if (!ui['voice-form'].reportValidity()) return;
    stopVoicePreview();
    clearVoice();
    ui['voice-error'].hidden = true;
    ui['voice-preview'].disabled = true;
    const request = preview = {};
    try {
        audioContext ??= new AudioContext();
        const [, wav] = await Promise.all([audioContext.resume(), window.liac.previewVoice(voiceDraft())]);
        if (!wav) throw new Error('No preview audio');
        const audio = await audioContext.decodeAudioData(wav);
        if (preview !== request || !ui['voice-setup'].open) return;
        const source = request.source = audioContext.createBufferSource();
        source.buffer = audio;
        source.connect(audioContext.destination);
        source.onended = () => {
            source.disconnect();
            if (preview === request) {
                preview = undefined;
                ui['voice-preview'].disabled = false;
            }
        };
        source.start();
    } catch {
        if (preview !== request) return;
        stopVoicePreview();
        voiceError('Preview unavailable. Check the Azure key, region, and voice.');
    }
};
ui['voice-form'].onsubmit = async event => {
    event.preventDefault();
    if (ui['voice-save'].disabled) return;
    stopVoicePreview();
    ui['voice-save'].disabled = ui['voice-cancel'].disabled = ui['voice-preview'].disabled = true;
    ui['voice-error'].hidden = true;
    try {
        await window.liac.configureVoice(voiceDraft());
        clearVoice(false);
        if (!voiceAvailable) ui['voice-toggle'].checked = true;
        voiceAvailable = true;
        ui['voice-setup'].close();
        updateVoiceStatus();
    } catch {
        voiceError('Could not save voice settings. Check the fields and local file access.');
    } finally {
        ui['voice-save'].disabled = ui['voice-cancel'].disabled = ui['voice-preview'].disabled = false;
    }
};

ui.capture.onchange = async () => {
    const enabled = ui.capture.checked;
    ui.capture.disabled = true;
    try { await window.liac.recordContext(enabled); }
    catch {
        ui.capture.checked = !enabled;
        notice = 'Could not change context recording. Try again.';
        inputError = true;
    }
    schedule();
};

ui.transcript.oninput = () => {
    ui.submit.disabled = !ui.transcript.value.trim();
};
ui.transcript.onkeydown = event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!ui.submit.disabled) ui.composer.requestSubmit();
    }
};
ui.composer.onsubmit = async event => {
    event.preventDefault();
    const text = ui.transcript.value.trim();
    if (!text || state !== 'ready' || isReplay) return;
    const id = crypto.randomUUID();
    clearVoice(false);
    if (voiceEnabled()) {
        updateVoiceStatus();
        try {
            audioContext ??= new AudioContext();
            playback ??= new PcmPlayback(audioContext);
            const input = voiceInput = { id: 'hub_' + id, at: performance.now() };
            audioContext.resume().catch(() => {
                if (voiceInput === input || speechTurn?.transcriptAt === input.at) {
                    clearVoice();
                    ui['voice-status'].textContent = 'TTS unavailable · Text chat active';
                }
            });
        } catch {
            ui['voice-status'].textContent = 'TTS unavailable · Text chat active';
        }
    }
    pending.set(id, text);
    ui.transcript.value = '';
    inputError = false;
    notice = '';
    schedule();
    try { await window.liac.submit(id, text, Boolean(voiceInput)); }
    catch {
        pending.delete(id);
        if (voiceInput?.id === 'hub_' + id) voiceInput = undefined;
        if (!ui.transcript.value) ui.transcript.value = text;
        inputError = true;
        notice = 'Transcript could not be sent. Try again.';
        schedule();
    }
};

function resize(percent) {
    const value = Math.min(72, Math.max(40, Math.round(percent)));
    ui.workspace.style.setProperty('--split', `${value}%`);
    ui.divider.setAttribute('aria-valuenow', value);
}
ui.divider.onpointerdown = event => ui.divider.setPointerCapture(event.pointerId);
ui.divider.onpointermove = event => {
    if (!ui.divider.hasPointerCapture(event.pointerId)) return;
    const rect = ui.workspace.getBoundingClientRect();
    resize((event.clientX - rect.left - 20) / (rect.width - 40) * 100);
};
ui.divider.onkeydown = event => {
    const value = Number(ui.divider.getAttribute('aria-valuenow'));
    const keys = { ArrowLeft: value - 2, ArrowRight: value + 2, Home: 40, End: 72 };
    if (event.key in keys) { event.preventDefault(); resize(keys[event.key]); }
};

function start() {
    clearVoice();
    live = session();
    ui.capture.checked = false;
    ui.retry.hidden = true;
    state = 'starting';
    updateVoiceStatus();
    notice = 'Checking the Luna bridge and sign-in.';
    inputError = false;
    schedule();
    window.liac.start().catch(() => {
        state = 'error';
        notice = 'Could not start the runtime.';
        ui.retry.hidden = false;
        schedule();
    });
}
ui.retry.onclick = start;
window.liac.onFrame(receive);
start();
