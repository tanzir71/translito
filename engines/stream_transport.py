"""Bounded WebSocket transport. Construction never connects or reads a key."""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import queue
import ssl
import threading

import numpy as np

from engines.provider import AuthenticationError, ProviderError
from engines.usage import Units


@asynccontextmanager
async def websocket_connection(protocol, headers):
    from websockets.asyncio.client import connect
    logging.getLogger("websockets.client").setLevel(logging.WARNING)
    async with connect(protocol.endpoint, additional_headers=headers, ssl=ssl.create_default_context(),
                       open_timeout=4, close_timeout=1, ping_interval=None, max_size=2 * 1024 * 1024) as socket:
        yield socket


class SocketStream:
    def __init__(self, protocol, credentials, on_update, on_error, *, connector=websocket_connection, authorize=lambda: None):
        self.protocol, self.credentials = protocol, credentials
        self.name = protocol.name
        self.on_update, self.on_error, self.connector, self.authorize = on_update, on_error, connector, authorize
        self.thread, self.frames, self.generation = None, 0, 0
        self.threads = []

    def estimate_usage(self, seconds):
        # Token-priced streams retain a conservative allocation until usage is known.
        if self.name == "soniox":
            import math
            context = len(json.dumps(self.protocol.start()).encode()) if self.thread is None or not self.thread.is_alive() else 0
            return Units(audio_seconds=seconds, requests=0, input_tokens=context, output_tokens=math.ceil(seconds * 64))
        return Units(audio_seconds=seconds, requests=0)

    def open_stream(self):
        self.authorize()
        headers = self.protocol.headers(self.credentials)
        work = queue.Queue(maxsize=300)
        self.work, self.frames = work, 0
        self.generation += 1
        generation = self.generation
        self.thread = threading.Thread(target=self._run, args=(work, headers, generation), daemon=True)
        self.threads.append(self.thread)
        self.thread.start()

    def push_audio(self, samples):
        try:
            self.frames += 1
            pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
            self.work.put_nowait(("audio", pcm))
            return True
        except queue.Full:
            return False

    def finalize(self):
        try:
            self.work.put_nowait(("finalize", None))
        except queue.Full:
            self.on_error("Cloud audio queue is full. Continuing on this PC.")

    def close_stream(self):
        try:
            self.work.put_nowait(("close", None))
        except queue.Full:
            self.on_error("Cloud audio queue is full. Continuing on this PC.")

    def _run(self, work, headers, generation):
        try:
            asyncio.run(self.run_session(work, headers, generation))
        except Exception as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            if isinstance(error, AuthenticationError) or status in {401, 403}:
                self.on_error("The provider key was rejected. Continuing on this PC.")
            else:
                self.on_error("Cloud streaming failed. Continuing on this PC.")

    async def run_session(self, work, headers, generation=1):
        ready, done, eof = asyncio.Event(), asyncio.Event(), asyncio.Event()
        frames = 0
        async def send(socket, value):
            if value is not None:
                await socket.send(json.dumps(value) if isinstance(value, dict) else value)
        async def receive(socket):
            while not done.is_set():
                message = await socket.recv()
                if not isinstance(message, str):
                    raise ProviderError()
                value = json.loads(message)
                update = self.protocol.parse(value)
                if update.ready:
                    ready.set()
                self.on_update(update, generation)
                if update.done or (eof.is_set() and self.name == "elevenlabs" and any(p.final for p in update.pieces)):
                    done.set()
        async def upload(socket):
            nonlocal frames
            if self.protocol.wait_for_ready:
                await asyncio.wait_for(ready.wait(), 4)
            while not done.is_set():
                try:
                    kind, pcm = work.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(.01)
                    continue
                if kind == "audio":
                    await send(socket, self.protocol.audio(pcm))
                    frames += 1
                elif kind == "finalize":
                    value = ({"type": "finalize"} if self.name == "soniox" else
                             {"message": "ForceEndOfUtterance"} if self.name == "speechmatics" else self.protocol.finish(frames))
                    await send(socket, value)
                elif kind == "close":
                    eof.set()
                    await send(socket, self.protocol.finish(frames))
                    return
        async with asyncio.timeout(120):
            async with self.connector(self.protocol, headers) as socket:
                await send(socket, self.protocol.start())
                receiving, uploading = asyncio.create_task(receive(socket)), asyncio.create_task(upload(socket))
                try:
                    finished, _ = await asyncio.wait((receiving, uploading), return_when=asyncio.FIRST_COMPLETED)
                    for task in finished:
                        task.result()
                    if receiving in finished and not eof.is_set():
                        raise ProviderError()
                    await uploading
                    try:
                        await asyncio.wait_for(receiving, 2)
                    except TimeoutError:
                        if not eof.is_set():
                            raise
                finally:
                    for task in (receiving, uploading):
                        task.cancel()
                    await asyncio.gather(receiving, uploading, return_exceptions=True)
