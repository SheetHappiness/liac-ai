import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { frames } from "./frames.mjs";
import { screenCapture } from "./screen.mjs";
import { InvalidToolCall, runTurn } from "./turn.mjs";

const provider = "openai-codex";
const modelId = "gpt-6-luna";
const authDir = new URL("../../.data/m6-auth/", import.meta.url);
process.env.PI_CODING_AGENT_DIR = fileURLToPath(authDir);
delete process.env.PI_REQ_DEBUG;
// pi-ai 18.22.1 uses this guard to suppress automatic 400/413 request dumps.
process.env.PI_TEST_RUNTIME = "1";

const schema = new URL("../../src/vtuber/minds/turn_tools.json", import.meta.url);
const tools = JSON.parse(await readFile(schema, "utf8"));
const recapTools = [{ ...tools[0], name: "save_recap", description: "Save the conversation recap." }];
const capture = screenCapture(process.env.LIAC_SCREEN_DISPLAY);

function send(id, type, fields) {
    process.stdout.write(JSON.stringify({ id, type, ...fields }) + "\n");
}

async function run() {
    const { AuthStorage, streamSimple } = await import("@oh-my-pi/pi-ai");
    const { getBundledModel } = await import("@oh-my-pi/pi-catalog");
    const model = getBundledModel(provider, modelId);
    if (!model || model.id !== modelId || model.provider !== provider) throw new Error("Luna model unavailable");
    const db = new URL("codex.sqlite", authDir);
    const auth = await stat(db).then(() => AuthStorage.create(fileURLToPath(db)), () => null);
    let active;
    try {
        await auth?.credentials.reload();
        try {
            for await (const frame of frames(process.stdin)) {
                if (frame.type === "shutdown") break;
                if (frame.type === "check" && typeof frame.id === "string" && !active) {
                    const signal = AbortSignal.timeout(8_000);
                    try {
                        if (!await auth?.oauth.access(provider, undefined, { signal })) {
                            throw new Error("OAuth unavailable");
                        }
                        signal.throwIfAborted();
                        send(frame.id, "ready", {});
                    } catch {
                        send(frame.id, "error", { kind: "oauth_unavailable" });
                    }
                    continue;
                }
                if (frame.type === "cancel" && frame.id === active?.id) active.controller.abort();
                if (frame.type !== "turn") continue;
                if (active) {
                    if (frame.id !== active.id) send(frame.id, "error", { kind: "busy" });
                    continue;
                }
                if (frame.reasoning !== "low" || typeof frame.system !== "string" ||
                    (frame.recap !== undefined && frame.recap !== true) ||
                    !Array.isArray(frame.messages) || typeof frame.id !== "string") {
                    send(frame.id, "error", { kind: "invalid_request" });
                    continue;
                }
                const controller = new AbortController();
                active = {
                    id: frame.id,
                    controller,
                    task: turn(frame, controller.signal).finally(() => { active = undefined; }),
                };
            }
        } finally {
            active?.controller.abort();
            await active?.task;
        }
    } finally {
        auth?.close();
    }

    async function turn(frame, cancelled) {
        const { id, system, messages, recap } = frame;
        const signal = AbortSignal.any([cancelled, AbortSignal.timeout(30_000)]);
        const start = performance.now();
        const elapsed = () => Math.round(performance.now() - start);
        let errorKind = "oauth_unavailable";
        try {
            const oauth = await auth?.oauth.access(provider, undefined, { signal });
            if (!oauth) throw new Error("OAuth unavailable");
            signal.throwIfAborted();
            errorKind = "provider_error";
            const result = await runTurn({
                messages, tools: recap ? recapTools : tools, capture: recap ? undefined : capture,
                recap, signal, modelId, provider, elapsed,
                onSpeech: text => send(id, "speak_delta", { text }),
                stream: context => streamSimple(model, { systemPrompt: system, ...context }, {
                    apiKey: oauth.accessToken,
                    reasoning: "low",
                    maxTokens: recap ? 2048 : 256,
                    hideThinkingSummary: true,
                    toolChoice: "required",
                    signal,
                    onPayload(payload) {
                        if (payload.model !== modelId || payload.reasoning?.effort !== "low") {
                            errorKind = "request_mismatch";
                            throw new Error("Unexpected Luna request");
                        }
                    },
                }),
            });
            signal.throwIfAborted();
            send(id, "result", result);
        } catch (error) {
            if (error instanceof InvalidToolCall) errorKind = "invalid_tool_call";
            send(id, "error", { kind: cancelled.aborted ? "cancelled" : errorKind });
        }
    }
}

run().catch(() => { process.exitCode = 1; });
