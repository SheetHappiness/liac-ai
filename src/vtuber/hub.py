"""Local JSONL transport between the Electron main process and Single Mind."""

import argparse
import asyncio
import json
import re
import shutil
import sys
from contextlib import aclosing, closing
from dataclasses import asdict
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from uuid import UUID

from vtuber.cli import input_lines
from vtuber.contracts.events import RuntimeOutput, utc_now
from vtuber.contracts.perception import Perception
from vtuber.minds.luna_stream import LunaStream, LunaStreamError
from vtuber.minds.m6_context import TokenBudget
from vtuber.runtime.journal import Journal
from vtuber.runtime.perception_bus import PerceptionBus, PerceptionQueueFull
from vtuber.runtime.single_mind import SingleMindRuntime
from vtuber.tracing import QueuedTraceRecorder, read_trace


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / '.data/hub/runs'
CHARACTER = 'primary'


def send(frame_type: str, **fields) -> None:
    print(json.dumps(dict(v=1, type=frame_type, **fields), ensure_ascii=True), flush=True)


def transcript(frame: dict) -> Perception:
    identifier, text = frame.get('id'), frame.get('text')
    if not isinstance(identifier, str) or len(identifier) != 36 or str(UUID(identifier)) != identifier:
        raise ValueError('Invalid transcript ID.')
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError('Transcript must contain 1 to 8,000 characters.')
    text.encode('utf-8')
    return Perception('hub_' + identifier, 'voice', 'electron', 'local', text.strip(),
                      utc_now(), delivery='direct', author_id='local')


def emit_journal(journal: Journal, write, after: int = 0) -> int:
    while rows := journal.read(CHARACTER, after=after):
        for event in rows:
            envelope = asdict(event)
            del envelope['payload_json']
            write('journal', event={**envelope, 'payload': event.payload})
        after = rows[-1].sequence
    return after


def journal_path(path: Path) -> Path:
    db = path / 'journal.sqlite3'
    if db.resolve().parent != path.resolve():
        raise ValueError('Invalid journal path')
    return db


def resume_journal(source: Path, destination: Path) -> None:
    with closing(Journal(journal_path(source), read_only=True)) as journal:
        journal.backup_to(destination)


def read_replay(path: Path, write=send) -> None:
    with closing(Journal(journal_path(path), read_only=True)) as journal:
        emit_journal(journal, write)
    expected = 0
    try:
        summary = json.loads((path / 'capture.json').read_text(encoding='utf-8')) if (
            path / 'capture.json').is_file() else {}
        expected = int(summary.get('records', 0))
        rows = read_trace(path, expected_records=expected)
        for row in rows:
            data = {}
            if row['file'] and 'capture_gap' not in row:
                try:
                    datetime.fromisoformat(row['time'])
                    data = json.loads((path / row['file']).read_text(encoding='utf-8'))['data']
                    if not isinstance(data, dict):
                        raise ValueError('Invalid trace payload')
                except (OSError, ValueError, KeyError, TypeError):
                    row['capture_gap'] = 'Trace timestamp or payload is unreadable.'
                    data = {}
            write('trace', row={**row, 'data': data})
        if summary.get('error') or summary.get('dropped') or len(rows) < expected:
            write('trace', row=dict(kind='capture.gap', capture_gap=summary.get('error')
                                     or 'Some trace events were not recorded.'))
    except (OSError, ValueError, TypeError, AttributeError):
        write('trace', row=dict(kind='capture.gap', capture_gap='Trace index is unreadable.'))


async def run_hub(bun_command: str, resume: Path | None = None) -> bool:
    bun = shutil.which(bun_command)
    if bun is None:
        send('status', state='error', message='Install Bun or set LIAC_BUN to its executable.')
        return False
    try:
        budget = TokenBudget.luna()
    except (ImportError, OSError, ValueError):
        send('status', state='error', message="Install the Luna extra with python -m pip install -e '.[luna]'.")
        return False
    capture_context = False
    record_turn_context = False
    model_turn: dict = {}
    recorder = None
    journal = None
    cursor = 0
    sequence = 0

    def flush_journal() -> None:
        nonlocal cursor
        if journal is not None:
            cursor = emit_journal(journal, send, cursor)

    def trace(kind: str, request_id: str, data: dict) -> None:
        nonlocal sequence, model_turn, record_turn_context
        if kind == 'model.started':
            model_turn = {key: data[key] for key in ('turn_id', 'batch_id')}
            record_turn_context = capture_context
        sequence += 1
        row = dict(sequence=sequence, time=utc_now(), kind=kind, request_id=request_id, data=data)
        if recorder is not None:
            recorder(kind, request_id, data)
        send('trace', row=row)
        if kind == 'admission.decided':
            flush_journal()

    def bridge_input(frame: dict) -> None:
        if record_turn_context:
            trace('model.bridge_input', model_turn['batch_id'], {**model_turn,
                  'system': frame['system'], 'messages': frame['messages'], 'reasoning': frame['reasoning']})

    command = (bun, '--no-env-file', str(ROOT / 'tools/luna-bridge/bridge.mjs'))
    mind = LunaStream(command, on_bridge_input=bridge_input)
    handoff = LunaStream(command, recap=True)
    try:
        await mind.check_ready()
        recorder = QueuedTraceRecorder(RUNS)
        db = recorder.path / 'journal.sqlite3'
        if resume is not None:
            resume_journal(resume, db)
        with closing(Journal(db)) as journal:
            def output(event: RuntimeOutput) -> None:
                if event.kind == 'reply.delta':
                    send('preview', **asdict(event))
                else:
                    flush_journal()

            identity = files('vtuber.minds').joinpath('character.md').read_text(encoding='utf-8')
            bus = PerceptionBus(live_gap=0.8, max_window=None, trace=trace)
            runtime = SingleMindRuntime(CHARACTER, journal, mind, output, identity=identity,
                                        bus=bus, trace=trace, budget=budget, summarize=handoff.summarize,
                                        model_metrics=mind.trace_metrics)
            await runtime.start()
            try:
                flush_journal()
                send('status', state='ready', run=recorder.path.name)
                async with asyncio.TaskGroup() as tasks:
                    owner = tasks.create_task(runtime.run())
                    try:
                        async with aclosing(input_lines()) as lines:
                            async for line in lines:
                                try:
                                    frame = json.loads(line)
                                except ValueError:
                                    continue
                                if not isinstance(frame, dict) or frame.get('v') != 1:
                                    continue
                                if frame.get('type') == 'record_context' and type(frame.get('enabled')) is bool:
                                    capture_context = frame['enabled']
                                if frame.get('type') == 'submit_transcript':
                                    try:
                                        item = transcript(frame)
                                        accepted = await runtime.publish(item)
                                        send('ack', id=frame['id'], accepted=accepted,
                                             message='' if accepted else 'Transcript already queued.')
                                    except (ValueError, PerceptionQueueFull) as error:
                                        send('ack', id=frame.get('id'), accepted=False, message=str(error))
                    finally:
                        # The task may not have acquired ownership if stdin closed immediately.
                        await runtime.close()
                        owner.cancel()
            finally:
                await runtime.close()
                flush_journal()
        return True
    except LunaStreamError as error:
        message = ('Sign in with bun --no-env-file tools/luna-bridge/probe.mjs --login.'
                   if str(error) == 'oauth_unavailable' else
                   'Check Bun and run npm ci --ignore-scripts --prefix tools/luna-bridge.')
        send('status', state='error', message=message)
        return False
    finally:
        try:
            try:
                await mind.close()
            finally:
                await handoff.close()
        finally:
            if recorder is not None:
                await recorder.aclose()
                try:
                    (recorder.path / 'capture.json').write_text(json.dumps(
                        dict(records=recorder.records_written, dropped=recorder.dropped,
                             error=recorder.error)), encoding='utf-8')
                except OSError:
                    pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bun', default='bun')
    run_mode = parser.add_mutually_exclusive_group()
    run_mode.add_argument('--replay')
    run_mode.add_argument('--resume')
    args = parser.parse_args()
    try:
        run = None
        if selected := args.replay or args.resume:
            if not re.fullmatch(r'run-[a-f0-9]{32}', selected):
                raise ValueError('Invalid run ID')
            run = RUNS / selected
            if run.resolve().parent != RUNS.resolve():
                raise ValueError('Invalid run path')
        if args.replay:
            read_replay(run)
        elif not asyncio.run(run_hub(args.bun, run)):
            sys.exit(1)
    except Exception:
        message = ('Replay could not read this run.' if args.replay else
                   'The selected run could not be resumed.' if args.resume else
                   'Liac stopped unexpectedly. Check write access to .data and retry.')
        send('status', state='error', message=message)
        sys.exit(1)


if __name__ == '__main__':
    main()
