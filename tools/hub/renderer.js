import { VoicePlayback, playAudio } from './voice.mjs';

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
let audioContext, audioReady;
const voice = new VoicePlayback({
    now: () => performance.now(),
    async synthesize(text) {
        if (!audioReady) return null;
        const [, wav] = await Promise.all([audioReady, window.liac.synthesize(text)]);
        return wav && audioContext.decodeAudioData(wav);
    },
    cancelSynthesis: () => { window.liac.cancelVoice().catch(() => {}); },
    play: (audio, onStart, onEnd) => playAudio(audioContext, audio, onStart, onEnd),
    onLatency(id, result) {
        live.latency.set(id, result);
        schedule();
    },
    onError() { ui['voice-status'].textContent = 'TTS unavailable · Text chat active'; },
});

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
    if (!view.chatDirty) return;
    view.chatDirty = false;
    const atBottom = ui.messages.scrollHeight - ui.messages.scrollTop - ui.messages.clientHeight < 40;
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
        voice.clear();
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
            if (state !== 'ready') voice.clear();
            if (state === 'error') {
                pending.clear();
            }
        }
    } else if (frame.type === 'retry_available') {
        ui.retry.hidden = false;
    } else if (frame.type === 'ack' && !frame.accepted) {
        const text = pending.get(frame.id);
        pending.delete(frame.id);
        if (stream === 'live') voice.reject('hub_' + frame.id);
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
        if (stream === 'live' && !isReplay) voice.delta(frame.turn_id, frame.text);
    } else if (frame.type === 'journal') {
        const event = frame.event;
        if (event.kind === 'perception.received') {
            view.raw.set(event.event_id, event.payload);
            if (stream === 'live' && event.event_id.startsWith('hub_')) pending.delete(event.event_id.slice(4));
        } else if (event.kind !== 'character.reply.started') {
            if (event.kind === 'user.message.completed') {
                view.turns.set(event.turn_id, event.payload);
                if (stream === 'live' && !isReplay && voiceEnabled()) {
                    voice.begin(event.turn_id, event.payload.perception_ids || []);
                }
            } else if (stream === 'live' && !isReplay && event.kind.startsWith('character.reply.')) {
                const spoken = event.kind === 'character.reply.completed' && event.payload.action === 'speak';
                voice.finish(event.turn_id, spoken ? event.payload.text : null);
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
    voice.clear();
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

ui['voice-toggle'].onchange = () => {
    if (ui['voice-toggle'].checked && !voiceAvailable) {
        ui['voice-toggle'].checked = false;
        ui['voice-error'].hidden = true;
        ui['voice-setup'].showModal();
        return;
    }
    if (!ui['voice-toggle'].checked) {
        voice.clear();
        audioReady = undefined;
    }
    updateVoiceStatus();
};
ui['voice-cancel'].onclick = () => ui['voice-setup'].close();
ui['voice-setup'].onclose = () => { ui['voice-key'].value = ''; };
ui['voice-form'].onsubmit = async event => {
    event.preventDefault();
    ui['voice-save'].disabled = true;
    ui['voice-error'].hidden = true;
    try {
        const key = ui['voice-key'].value.trim();
        ui['voice-key'].value = '';
        await window.liac.configureVoice(key, ui['voice-region'].value.trim());
        voiceAvailable = true;
        ui['voice-toggle'].checked = true;
        ui['voice-setup'].close();
        updateVoiceStatus();
    } catch {
        ui['voice-error'].textContent = 'Enter a Speech key and region from your Azure resource.';
        ui['voice-error'].hidden = false;
        ui['voice-key'].focus();
    } finally {
        ui['voice-save'].disabled = false;
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
    if (voiceEnabled()) {
        voice.submit('hub_' + id);
        updateVoiceStatus();
        try {
            audioContext ??= new AudioContext();
            const resume = audioContext.resume();
            audioReady = resume;
            resume.catch(() => {
                if (audioReady === resume && voiceEnabled() && !isReplay) {
                    ui['voice-status'].textContent = 'TTS unavailable · Text chat active';
                }
            });
        } catch {
            audioReady = undefined;
            ui['voice-status'].textContent = 'TTS unavailable · Text chat active';
        }
    }
    pending.set(id, text);
    ui.transcript.value = '';
    inputError = false;
    notice = '';
    schedule();
    try { await window.liac.submit(id, text); }
    catch {
        pending.delete(id);
        voice.reject('hub_' + id);
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
    voice.clear();
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
