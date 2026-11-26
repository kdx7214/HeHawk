#!/usr/bin/env python3
"""Local MPV playback controller for NUTCRACKER (Linux, standard library)."""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time


class PlayerError(RuntimeError):
    pass


def timestamp(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'


class Player:
    def __init__(self, video, geometry='70%', volume=75):
        self.video = Path(video).resolve(strict=True)
        self.temp = None
        self.process = None
        self.sock = None
        self.buffer = b''
        self.request_id = 0
        self.tracks = {}
        self.window = None
        self.replays = 0
        self.started = time.monotonic()
        self.temp = tempfile.TemporaryDirectory(prefix='nutcracker-', dir='/tmp')
        try:
            self.socket_path = str(Path(self.temp.name) / 'mpv.sock')
            self.process = subprocess.Popen([
                'mpv', '--no-config', '--idle=yes', '--pause=yes',
                '--keep-open=yes', '--force-window=yes', '--sub-auto=no',
                '--sid=no', '--terminal=no', '--osc=yes',
                f'--geometry={geometry}', f'--volume={volume}',
                f'--input-ipc-server={self.socket_path}',
                '--title=NUTCRACKER Review', '--', str(self.video)])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise PlayerError('MPV exited during startup')
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.connect(self.socket_path)
                except OSError:
                    sock.close()
                    time.sleep(.05)
                    continue
                self.sock = sock
                break
            if self.sock is None:
                raise PlayerError('MPV IPC startup timed out')
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    self.duration = float(self.get('duration'))
                    if math.isfinite(self.duration) and self.duration > 0:
                        break
                except (PlayerError, TypeError, ValueError):
                    pass
                time.sleep(.1)
            else:
                raise PlayerError('Media duration unavailable')
        except BaseException:
            self.close()
            raise

    def command(self, *args):
        # Synchronous single-client IPC. Unsolicited events are ignored.
        self.request_id += 1
        rid = self.request_id
        self.sock.settimeout(5)
        self.sock.sendall((json.dumps({'command': args, 'request_id': rid},
                                     allow_nan=False) + '\n').encode())
        deadline = time.monotonic() + 5
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PlayerError('IPC response timed out')
            if b'\n' not in self.buffer:
                self.sock.settimeout(remaining)
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise PlayerError('MPV disconnected')
                self.buffer += chunk
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            msg = json.loads(line)
            if msg.get('request_id') != rid:
                continue
            if msg.get('error') != 'success':
                raise PlayerError(f'{args[0]}: {msg.get("error")}')
            return msg.get('data')

    def get(self, name):
        return self.command('get_property', name)

    def set(self, name, value):
        return self.command('set_property', name, value)

    def set_window(self, start, end):
        if not (0 <= start < end <= self.duration):
            raise ValueError('Invalid playback interval')
        self.set('pause', True)
        self.set('ab-loop-a', 'no')
        self.set('ab-loop-b', 'no')
        self.set('ab-loop-a', start)
        self.set('ab-loop-b', end)
        self.command('seek', start, 'absolute+exact')
        self.window = (start, end)

    def replay(self):
        if self.window is None:
            raise PlayerError('No review window selected')
        self.command('seek', self.window[0], 'absolute+exact')
        self.set('pause', False)
        self.replays += 1

    def add_subtitles(self, label, path):
        if label in self.tracks:
            raise ValueError('Duplicate subtitle label')
        path = str(Path(path).resolve(strict=True))
        before = {t['id'] for t in self.get('track-list') if t['type'] == 'sub'}
        self.command('sub-add', path, 'select', label)
        after = {t['id'] for t in self.get('track-list') if t['type'] == 'sub'}
        added = after - before
        if len(added) != 1:
            raise PlayerError('Could not identify new subtitle track')
        self.tracks[label] = added.pop()

    def select_subtitles(self, label=None):
        self.set('sid', 'no' if label is None else self.tracks[label])
        self.set('sub-visibility', True)

    def remove_subtitles(self, label):
        self.command('sub-remove', self.tracks[label])
        del self.tracks[label]

    def add_preview(self, label, cues):
        """Cues are (episode_start_seconds, episode_end_seconds, plain_text)."""
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                suffix='.srt', dir=self.temp.name, delete=False) as f:
            path = Path(f.name)
            for i, (start, end, text) in enumerate(cues, 1):
                if not (0 <= start < end <= self.duration):
                    raise ValueError('Invalid subtitle interval')
                a, b = timestamp(start), timestamp(end)
                if a == b:
                    raise ValueError('Subtitle interval below SRT resolution')
                text = '\n'.join(line for line in text.splitlines() if line.strip())
                if not text:
                    raise ValueError('Empty preview cue')
                f.write(f'{i}\n{a.replace(".", ",")} --> {b.replace(".", ",")}\n{text}\n\n')
        self.add_subtitles(label, path)

    def state(self):
        return {key: self.get(key) for key in
                ('time-pos', 'pause', 'volume', 'speed', 'sid', 'sub-scale')}

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.temp is not None:
            self.temp.cleanup()
            self.temp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('video', type=Path)
    p.add_argument('--start', type=float, required=True)
    p.add_argument('--end', type=float, required=True)
    p.add_argument('--original', type=Path)
    p.add_argument('--recovered', type=Path)
    p.add_argument('--geometry', default='70%')
    args = p.parse_args()
    with Player(args.video, args.geometry) as player:
        player.set_window(args.start, args.end)
        for label in ('original', 'recovered'):
            path = getattr(args, label)
            if path is not None:
                player.add_subtitles(label, path)
        # Synthetic presentation test, never a recognition hypothesis.
        player.add_preview('test', [(args.start, args.end,
                                     '[SYNTHETIC PREVIEW TEST]')])
        player.select_subtitles(None)
        print(f'Window: {timestamp(args.start)} - {timestamp(args.end)} '
              f'({args.start:.3f} - {args.end:.3f}s)')
        print('A-B loop active. No evidence database is opened.')
        print('Commands: p play/replay, pause, original, recovered, test, none,')
        print('volume N, speed N, size N, state, q quit')
        try:
            while True:
                parts = input('NUTCRACKER player> ').strip().split()
                if not parts:
                    continue
                cmd = parts[0].lower()
                try:
                    if cmd == 'q':
                        break
                    elif cmd == 'p':
                        player.replay()
                    elif cmd == 'pause':
                        player.set('pause', not player.get('pause'))
                    elif cmd == 'none':
                        player.select_subtitles()
                    elif cmd in player.tracks:
                        player.select_subtitles(cmd)
                    elif cmd in ('volume', 'speed', 'size') and len(parts) == 2:
                        value = float(parts[1])
                        prop, low, high = {'volume': ('volume', 0, 100),
                            'speed': ('speed', .25, 2), 'size': ('sub-scale', .5, 3)}[cmd]
                        if not low <= value <= high:
                            raise ValueError(f'Allowed range: {low} to {high}')
                        player.set(prop, value)
                    elif cmd == 'state':
                        state = player.state()
                        pos = state.pop('time-pos')
                        print('Position:', timestamp(pos), f'({pos:.3f}s)')
                        print(state)
                    else:
                        print('Unknown command or unavailable track')
                except (ValueError, PlayerError, KeyError) as exc:
                    print('Error:', exc)
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            print(f'Replay commands: {player.replays}')
            print(f'Session elapsed: {time.monotonic()-player.started:.3f}s')


if __name__ == '__main__':
    main()
