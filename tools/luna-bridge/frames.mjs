const MAX_REQUEST_BYTES = 8 * 1024 * 1024;

export async function* frames(input) {
    let size = 0;
    let pending = Buffer.alloc(0);
    for await (const chunk of input) {
        let start = 0;
        while (start < chunk.length) {
            const newline = chunk.indexOf(10, start);
            const end = newline === -1 ? chunk.length : newline;
            const piece = chunk.subarray(start, end);
            const total = size + piece.length;
            if (total >= MAX_REQUEST_BYTES) throw new Error("Input frame too large");
            if (size || newline === -1) {
                if (pending.length < total) {
                    const next = Buffer.allocUnsafe(Math.min(MAX_REQUEST_BYTES,
                        Math.max(total, pending.length * 2)));
                    pending.copy(next, 0, 0, size);
                    pending = next;
                }
                piece.copy(pending, size);
            }
            if (newline !== -1) {
                const line = size ? pending.subarray(0, total) : piece;
                size = 0;
                yield JSON.parse(line.toString("utf8"));
            } else {
                size = total;
            }
            start = end + 1;
        }
    }
    if (size) throw new Error("Incomplete input frame");
}
