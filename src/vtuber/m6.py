"""Opt-in local text console for the M6 Single Mind experiment."""

import argparse
import asyncio
import shutil
from contextlib import aclosing, closing
from importlib.resources import files
from pathlib import Path

from vtuber.cli import input_lines
from vtuber.contracts.events import RuntimeOutput, new_id, utc_now
from vtuber.contracts.mind import SingleMindPort
from vtuber.contracts.perception import Perception
from vtuber.contracts.trace import TraceSink
from vtuber.minds.fake import FakeSingleMind
from vtuber.minds.luna_stream import LunaStream
from vtuber.runtime.journal import Journal
from vtuber.runtime.perception_bus import PerceptionQueueFull
from vtuber.runtime.single_mind import SingleMindRuntime
from vtuber.tracing import QueuedTraceRecorder


class ConsoleOutput:
    def __init__(self) -> None:
        self._previewing = False

    def __call__(self, output: RuntimeOutput) -> None:
        if output.kind == 'reply.delta':
            prefix = '' if self._previewing else '[Provisional] '
            print(prefix + output.text, end='', flush=True)
            self._previewing = True
        elif output.kind in ('reply.completed', 'reply.cancelled', 'reply.failed'):
            if self._previewing:
                print(flush=True)
                self._previewing = False
            if output.kind == 'reply.completed' and output.text:
                print(f'[Final] {output.text}', flush=True)
            elif output.kind in ('reply.cancelled', 'reply.failed'):
                print(f'[{output.kind.removeprefix("reply.").capitalize()}] {output.text}', flush=True)


async def run_console(db: Path, mind: SingleMindPort, *, trace: TraceSink | None = None) -> None:
    identity = files('vtuber.minds').joinpath('character.md').read_text(encoding='utf-8')
    with closing(Journal(db)) as journal:
        runtime = SingleMindRuntime('primary', journal, mind, ConsoleOutput(), identity=identity, trace=trace)
        await runtime.start()

        print('Liac Single Mind | Enter text or /quit.', flush=True)
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(runtime.run(), name='m6-consciousness')
                try:
                    async with aclosing(input_lines()) as lines:
                        async for line in lines:
                            if line.strip() in ('/quit', '/exit'):
                                break
                            if line.strip():
                                try:
                                    await runtime.publish(Perception(new_id('perception'), 'chat', 'local', 'local',
                                        line, utc_now(), delivery='direct', author_id='local'))
                                except PerceptionQueueFull as error:
                                    print(str(error), flush=True)
                finally:
                    await runtime.finish_input()
        finally:
            await runtime.close()


async def _run(db: Path, mind: SingleMindPort, *, trace: bool) -> None:
    recorder = QueuedTraceRecorder(Path('.data/traces')) if trace else None
    try:
        await run_console(db, mind, trace=recorder)
    finally:
        try:
            if isinstance(mind, LunaStream):
                await mind.close()
        finally:
            if recorder is not None:
                await recorder.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description='Liac M6 text-only Single Mind experiment')
    parser.add_argument('--backend', choices=('fake', 'luna'), default='fake')
    parser.add_argument('--db', type=Path, help='SQLite database (default depends on backend)')
    parser.add_argument('--reasoning', choices=('low',), default='low')
    parser.add_argument('--bun', default='bun', help='Bun executable for the Luna backend')
    parser.add_argument('--trace', action='store_true', help='Record scheduling metadata in .data/traces')
    args = parser.parse_args()
    try:
        if args.backend == 'fake':
            asyncio.run(_run(args.db or Path('.data/m6-fake.sqlite3'), FakeSingleMind(), trace=args.trace))
        else:
            bun = shutil.which(args.bun)
            if bun is None:
                parser.error('Luna requires Bun on PATH or an explicit --bun executable')
            bridge = Path(__file__).resolve().parents[2] / 'tools/luna-bridge/bridge.mjs'
            if not bridge.is_file():
                parser.error('Run the Luna backend from the Liac source checkout with its bridge installed')
            mind = LunaStream((bun, '--no-env-file', str(bridge)), reasoning=args.reasoning)
            asyncio.run(_run(args.db or Path('.data/m6-0.sqlite3'), mind, trace=args.trace))
    except KeyboardInterrupt:
        print('\nSingle Mind interrupted.', flush=True)


if __name__ == '__main__':
    main()
