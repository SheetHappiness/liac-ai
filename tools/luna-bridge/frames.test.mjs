import assert from "node:assert/strict";
import test from "node:test";
import { frames } from "./frames.mjs";

test("reads multiple frames and a split multibyte frame above 64 KiB", async () => {
    const message = "項".repeat(25_000);
    const data = Buffer.from(JSON.stringify({ message }) + '\n{"type":"check"}\n');
    const split = 13;
    const received = [];
    for await (const frame of frames([data.subarray(0, split), data.subarray(split)])) {
        received.push(frame);
    }
    assert.deepEqual(received, [{ message }, { type: "check" }]);
});

test("rejects an oversized unterminated frame before requesting another chunk", async () => {
    async function* input() {
        yield Buffer.alloc(8 * 1024 * 1024, 97);
        assert.fail("Read past the limit");
    }
    await assert.rejects(frames(input()).next(), /Input frame too large/);
});

test("counts the newline toward the request ceiling", async () => {
    const prefix = '{"message":"';
    const suffix = '"}\n';
    const message = "x".repeat(8 * 1024 * 1024 - prefix.length - suffix.length);
    const frame = Buffer.from(prefix + message + suffix);
    assert.equal((await frames([frame]).next()).value.message.length, message.length);
    await assert.rejects(frames([Buffer.concat([frame.subarray(0, -3), Buffer.from('x"}\n')])]).next(),
        /Input frame too large/);
});
