import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { runTurn } from "./turn.mjs";

const tools = JSON.parse(readFileSync(new URL("../../src/vtuber/minds/turn_tools.json", import.meta.url), "utf8"));
const inspect = { name: "inspect_screen", arguments: {} };
const speak = { name: "speak", arguments: { message: "I see it." } };
const silent = { name: "stay_silent", arguments: {} };
const image = { type: "image", mimeType: "image/jpeg", data: "frame-base64" };

function setup(steps, capture, signal = new AbortController().signal, turnTools = tools) {
    const requests = [];
    const deltas = [];
    const messages = [{ role: "user", content: "That character looks creepy." }];
    const run = () => runTurn({
        messages, tools: turnTools, capture, signal,
        modelId: "gpt-6-luna", provider: "openai-codex", elapsed: () => 0,
        onSpeech: text => deltas.push(text),
        stream(context) {
            const call = { type: "toolCall", id: `id_${requests.length}`, ...steps[requests.length] };
            requests.push(context);
            return {
                async *[Symbol.asyncIterator]() {
                    yield { type: "toolcall_delta", contentIndex: 0, partial: { content: [call] },
                        delta: JSON.stringify(call.arguments) };
                    yield { type: "toolcall_end", contentIndex: 0, toolCall: call };
                },
                async result() {
                    return { role: "assistant", stopReason: "toolUse", content: [call],
                        model: "gpt-6-luna", provider: "openai-codex",
                        usage: { input: 2, output: 1, cacheRead: 3, cacheWrite: 0 } };
                },
            };
        },
    });
    return { run, requests, deltas, messages };
}

test("ordinary speech and silence take one request and never capture", async () => {
    for (const call of [speak, silent]) {
        let captures = 0;
        const { run, requests } = setup([call], async () => { captures++; });
        assert.equal((await run()).action, call.name);
        assert.equal(requests.length, 1);
        assert.equal(captures, 0);
    }
});

test("the next Luna step receives a paired image result and only terminal speech leaves the turn", async () => {
    const { run, requests, deltas, messages } = setup([inspect, speak], async () => image);
    const result = await run();
    assert.deepEqual(requests[0].messages, messages);
    assert.equal(messages.length, 1);
    assert.deepEqual(requests[0].tools.map(tool => tool.name), ["speak", "stay_silent", "inspect_screen"]);
    const [, assistant, observation] = requests[1].messages;
    assert.equal(observation.role, "toolResult");
    assert.equal(observation.toolCallId, assistant.content[0].id);
    assert.deepEqual(observation.content, [image]);
    assert.deepEqual(deltas, ["I see it."]);
    assert.equal(result.action, "speak");
    assert.equal(result.tool_call_id, "id_1");
    assert.equal(result.usage.input, 4);
    assert.doesNotMatch(JSON.stringify(result), /frame-base64/);
});

test("failed captures are observations, and four attempts exhaust the tool budget", async () => {
    const { run, requests } = setup([inspect, inspect, inspect, inspect, silent], async () => {
        throw new Error("private capture error");
    });
    assert.equal((await run()).action, "stay_silent");
    assert.equal(requests.length, 5);
    assert.deepEqual(requests[4].tools, tools);
    assert.match(requests[1].messages.at(-1).content[0].text, /unavailable/i);
    assert.doesNotMatch(JSON.stringify(requests[4]), /private capture error/);
});

test("disabled and malformed screen calls cannot capture", async () => {
    const disabled = setup([inspect]);
    await assert.rejects(disabled.run, /tool call/);
    let captures = 0;
    const malformed = setup([{ ...inspect, arguments: { display: "2" } }], async () => { captures++; });
    await assert.rejects(malformed.run, /arguments/);
    assert.equal(captures, 0);
});

test("cancellation during capture cannot send another request or publish speech", async () => {
    const controller = new AbortController();
    const { run, requests, deltas } = setup([inspect, speak], async signal => {
        assert.equal(signal, controller.signal);
        controller.abort();
        return image;
    }, controller.signal);
    await assert.rejects(run, { name: "AbortError" });
    assert.equal(requests.length, 1);
    assert.deepEqual(deltas, []);
});
