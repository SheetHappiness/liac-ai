export class PcmPlayback {
    #stops = new Set();
    #end = 0;

    constructor(context) {
        this.context = context;
    }

    push(pcm, sampleRate, onStart) {
        const context = this.context;
        if (!(pcm instanceof ArrayBuffer) || !pcm.byteLength || pcm.byteLength % 2 || sampleRate !== 24_000) {
            throw new Error('Invalid PCM chunk');
        }
        const frames = pcm.byteLength / 2;
        const now = context.currentTime;
        const start = this.#end > now ? this.#end : now + 0.025;
        if (start + frames / sampleRate - now > 300) throw new Error('Audio queue full');

        const audio = context.createBuffer(1, frames, sampleRate);
        const samples = audio.getChannelData(0);
        const data = new DataView(pcm);
        for (let index = 0; index < frames; index++) samples[index] = data.getInt16(index * 2, true) / 32_768;
        const stop = playAudio(context, audio, onStart, () => this.#stops.delete(stop), start);
        this.#stops.add(stop);
        this.#end = start + audio.duration;
    }

    clear() {
        for (const stop of this.#stops) stop();
        this.#stops.clear();
        this.#end = 0;
    }
}

export function playAudio(context, audio, onStart, onEnd, start = context.currentTime) {
    const source = context.createBufferSource();
    source.buffer = audio;
    source.connect(context.destination);
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
        if (!onStart || measured) onEnd();
    };
    source.start(start);
    if (onStart) checkOutput();
    return () => {
        clearTimeout(timer);
        source.onended = null;
        if (outputDeadline == null) source.stop();
        source.disconnect();
    };
}
