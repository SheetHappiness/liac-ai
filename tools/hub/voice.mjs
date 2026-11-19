const sentences = new Intl.Segmenter(undefined, { granularity: 'sentence' });
// A trailing ASCII period needs more text to distinguish a sentence from a decimal.
const unambiguousEnd = /[!?…。！？]["'”’»）)\]]*\s*$/u;

export class VoicePlayback {
    #submission;
    #turn;
    #segment;
    #playing;

    constructor({ now, synthesize, cancelSynthesis, play, onLatency, onError }) {
        Object.assign(this, { now, synthesize, cancelSynthesis, play, onLatency, onError });
    }

    submit(id) {
        this.clear();
        this.#submission = { id, at: this.now() };
    }

    reject(id) {
        if (this.#submission?.id === id) this.#submission = undefined;
    }

    begin(id, perceptions) {
        const submission = this.#submission;
        if (!submission || !perceptions.includes(submission.id)) return;
        this.#submission = undefined;
        this.#turn = { id, transcriptAt: submission.at, text: '', offset: 0 };
    }

    delta(id, text) {
        const turn = this.#turn;
        if (turn?.id !== id || turn.final) return;
        turn.previewAt ??= this.now();
        turn.text += text;
        this.#pump();
    }

    finish(id, text) {
        const turn = this.#turn;
        if (turn?.id !== id) return;
        if (!text || !text.startsWith(turn.text.slice(0, turn.offset))) {
            this.clear();
            return;
        }
        turn.text = text;
        turn.final = true;
        this.#pump();
    }

    clear() {
        this.#submission = undefined;
        this.#turn = undefined;
        const segment = this.#segment;
        this.#segment = undefined;
        if (segment && !segment.audio) this.cancelSynthesis();
        const playing = this.#playing;
        this.#playing = undefined;
        playing?.stop?.();
    }

    #pump() {
        if (this.#segment) {
            if (this.#segment.audio && !this.#playing) {
                const segment = this.#segment;
                this.#segment = undefined;
                this.#start(segment);
            }
            return;
        }
        const turn = this.#turn;
        if (!turn) return;
        const remaining = turn.text.slice(turn.offset);
        if (!remaining.trim()) {
            if (turn.final && !this.#playing) this.#turn = undefined;
            return;
        }
        const { segment } = sentences.segment(remaining)[Symbol.iterator]().next().value;
        if (!turn.final && segment.length === remaining.length && !unambiguousEnd.test(segment)) return;
        turn.offset += segment.length;
        this.#segment = { turn };
        void this.#prepare(this.#segment, segment.trim());
    }

    async #prepare(segment, text) {
        try {
            const audio = await this.synthesize(text);
            if (this.#segment !== segment) return;
            if (!audio) throw new Error('No audio');
            segment.audio = audio;
        } catch {
            if (this.#segment !== segment) return;
            this.clear();
            this.onError();
        }
        this.#pump();
    }

    #start(playing) {
        this.#playing = playing;
        const { turn } = playing;
        try {
            playing.stop = this.play(playing.audio, startedAt => {
                if (this.#playing !== playing || turn.measured) return;
                turn.measured = true;
                const elapsed = time => time == null ? null : Math.max(0, Math.round(startedAt - time));
                this.onLatency(turn.id, { transcriptMs: elapsed(turn.transcriptAt), previewMs: elapsed(turn.previewAt) });
            }, () => {
                if (this.#playing !== playing) return;
                this.#playing = undefined;
                this.#pump();
            });
        } catch {
            this.clear();
            this.onError();
        }
        this.#pump();
    }
}

export function playAudio(context, audio, onStart, onEnd) {
    const source = context.createBufferSource();
    source.buffer = audio;
    source.connect(context.destination);
    const start = context.currentTime;
    let timer, outputDeadline, measured = false;
    const checkOutput = () => {
        const output = context.getOutputTimestamp();
        if (output.performanceTime && output.contextTime >= start) {
            measured = true;
            onStart(output.performanceTime + (start - output.contextTime) * 1000);
            if (outputDeadline != null) onEnd();
        } else if (outputDeadline != null && performance.now() >= outputDeadline) {
            onEnd();
        } else {
            timer = setTimeout(checkOutput, 16);
        }
    };
    source.onended = () => {
        source.disconnect();
        outputDeadline = performance.now() + Math.max(250, context.outputLatency * 1000 + 50);
        if (measured) onEnd();
    };
    source.start(start);
    checkOutput();
    return () => {
        clearTimeout(timer);
        source.onended = null;
        if (outputDeadline == null) source.stop();
        source.disconnect();
    };
}
