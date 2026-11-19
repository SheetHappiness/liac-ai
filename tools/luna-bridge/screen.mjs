import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execute = promisify(execFile);
const script = fileURLToPath(new URL("./screen.ps1", import.meta.url));

export function screenCapture(display) {
    if (process.platform !== "win32" || !/^[1-9][0-9]*$/.test(display ?? "")) return undefined;
    return async signal => {
        const { stdout } = await execute("powershell.exe", [
            "-NoProfile", "-NonInteractive", "-File", script, display,
        ], { encoding: "buffer", maxBuffer: 512 * 1024, timeout: 3_000, windowsHide: true, signal });
        if (stdout.length < 4 || stdout.readUInt16BE(0) !== 0xffd8 ||
            stdout.readUInt16BE(stdout.length - 2) !== 0xffd9) throw new Error("Invalid JPEG");
        return { type: "image", mimeType: "image/jpeg", data: stdout.toString("base64") };
    };
}
