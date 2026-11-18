const property = /^\s*\{\s*("(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[\da-fA-F]{4}))*")\s*:\s*"/;
const stringBody = /^(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[\da-fA-F]{4}))*/;

function speechPrefix(raw) {
    const match = property.exec(raw);
    if (!match || JSON.parse(match[1]) !== "message") return "";
    const body = stringBody.exec(raw.slice(match[0].length))[0];
    return JSON.parse('"' + body + '"').replace(/[\uD800-\uDBFF]$/, "");
}

export class SpeakStream {
    #raw = new Map();
    #index;
    #emitted = 0;

    raw(index) {
        return this.#raw.get(index) ?? "";
    }

    push(index, name, chunk) {
        const raw = this.raw(index) + chunk;
        if (raw.length > 16_384) throw new Error("Tool arguments too large");
        this.#raw.set(index, raw);
        if (name !== "speak") return "";
        this.#index ??= index;
        if (this.#index !== index) return "";
        const prefix = speechPrefix(raw);
        const delta = prefix.slice(this.#emitted);
        this.#emitted = prefix.length;
        return delta;
    }
}

export function completedArguments(name, raw, final) {
    let parsed;
    try {
        parsed = raw ? JSON.parse(raw) : final;
    } catch {
        return null;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) ||
        !final || typeof final !== "object" || Array.isArray(final)) return null;
    if (name === "speak" && typeof parsed.message === "string" && parsed.message.trim() &&
        Object.keys(parsed).length === 1 && Object.keys(final).length === 1 &&
        parsed.message === final.message && parsed.message.isWellFormed()) return parsed;
    if (name === "stay_silent" && !Object.keys(parsed).length && !Object.keys(final).length) return parsed;
    return null;
}
