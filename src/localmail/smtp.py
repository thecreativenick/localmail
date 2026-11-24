"""A minimal RFC 5321 SMTP server on asyncio that stores mail in an in-memory mailbox.

Localhost only: there is no relaying, no auth and no real mail. IMAP, MIME
parsing and threading come in later milestones and read from the same store.
"""

from __future__ import annotations

import asyncio
import re
import threading
from dataclasses import dataclass, field

ADDR_RE = re.compile(r"<([^<>]*)>")
MAX_LINE = 1000  # RFC 5321 4.5.3.1.6 (including CRLF)


@dataclass
class Message:
    sender: str
    recipients: list[str]
    data: bytes  # raw RFC 5322 bytes, CRLF line endings, dot-unstuffed


@dataclass
class MailStore:
    messages: list[Message] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def deliver(self, msg: Message) -> None:
        with self.lock:
            self.messages.append(msg)

    def for_recipient(self, addr: str) -> list[Message]:
        with self.lock:
            return [m for m in self.messages if addr.lower() in (r.lower() for r in m.recipients)]


class SMTPSession:
    def __init__(self, store: MailStore, hostname: str):
        self.store = store
        self.hostname = hostname
        self.reset()

    def reset(self) -> None:
        self.sender: str | None = None
        self.recipients: list[str] = []

    async def run(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        def send(line: str) -> None:
            writer.write(line.encode() + b"\r\n")

        send(f"220 {self.hostname} localmail ESMTP ready")
        greeted = False
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    return
                if len(raw) > MAX_LINE:
                    send("500 5.5.2 Line too long")
                    continue
                line = raw.rstrip(b"\r\n").decode("utf-8", "replace")
                verb, _, arg = line.partition(" ")
                verb = verb.upper()

                if verb in ("EHLO", "HELO"):
                    greeted = True
                    self.reset()
                    if verb == "EHLO":
                        send(f"250-{self.hostname} greets {arg or 'client'}")
                        send("250-8BITMIME")
                        send("250 PIPELINING")
                    else:
                        send(f"250 {self.hostname}")
                elif verb == "MAIL":
                    if not greeted:
                        send("503 5.5.1 Send EHLO first")
                    elif self.sender is not None:
                        send("503 5.5.1 Sender already given")
                    elif not (m := ADDR_RE.search(arg)) or not arg.upper().startswith("FROM:"):
                        send("501 5.5.4 Syntax: MAIL FROM:<address>")
                    else:
                        self.sender = m.group(1)
                        send("250 2.1.0 OK")
                elif verb == "RCPT":
                    if self.sender is None:
                        send("503 5.5.1 Need MAIL first")
                    elif not (m := ADDR_RE.search(arg)) or not arg.upper().startswith("TO:") or not m.group(1):
                        send("501 5.5.4 Syntax: RCPT TO:<address>")
                    else:
                        self.recipients.append(m.group(1))
                        send("250 2.1.5 OK")
                elif verb == "DATA":
                    if not self.recipients:
                        send("503 5.5.1 Need RCPT first")
                        continue
                    send("354 End data with <CR><LF>.<CR><LF>")
                    await writer.drain()
                    body = await self._read_data(reader)
                    if body is None:
                        return
                    self.store.deliver(Message(self.sender or "", list(self.recipients), body))
                    self.reset()
                    send("250 2.0.0 Queued")
                elif verb == "RSET":
                    self.reset()
                    send("250 2.0.0 OK")
                elif verb == "NOOP":
                    send("250 2.0.0 OK")
                elif verb == "QUIT":
                    send(f"221 2.0.0 {self.hostname} closing")
                    await writer.drain()
                    return
                else:
                    send("500 5.5.2 Command not recognized")
                await writer.drain()
        finally:
            writer.close()

    @staticmethod
    async def _read_data(reader: asyncio.StreamReader) -> bytes | None:
        lines = []
        while True:
            raw = await reader.readline()
            if not raw:
                return None
            if raw in (b".\r\n", b".\n"):
                return b"".join(lines)
            if raw.startswith(b"."):
                raw = raw[1:]  # dot-unstuffing, RFC 5321 4.5.2
            if not raw.endswith(b"\r\n"):
                raw = raw.rstrip(b"\n") + b"\r\n"
            lines.append(raw)


class SMTPServer:
    """Runs the server on its own event loop in a background thread."""

    def __init__(self, store: MailStore | None = None, host: str = "127.0.0.1", port: int = 0,
                 hostname: str = "localmail.test"):
        self.store = store or MailStore()
        self.host, self.port, self.hostname = host, port, hostname
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: asyncio.base_events.Server | None = None

    def start(self) -> "SMTPServer":
        ready = threading.Event()

        def main() -> None:
            self._loop = asyncio.new_event_loop()

            async def boot() -> None:
                self._server = await asyncio.start_server(
                    lambda r, w: SMTPSession(self.store, self.hostname).run(r, w),
                    self.host, self.port,
                )
                self.port = self._server.sockets[0].getsockname()[1]
                ready.set()

            self._loop.run_until_complete(boot())
            self._loop.run_forever()
            self._loop.close()

        self._thread = threading.Thread(target=main, daemon=True)
        self._thread.start()
        ready.wait(5)
        return self

    def stop(self) -> None:
        if self._loop and self._server:
            async def shutdown() -> None:
                self._server.close()
                # Python 3.12+ wait_closed() also waits for open client
                # connections; don't let a stuck client hang shutdown.
                try:
                    await asyncio.wait_for(self._server.wait_closed(), 2)
                except TimeoutError:
                    pass
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(5)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)

    def __enter__(self) -> "SMTPServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


if __name__ == "__main__":
    srv = SMTPServer(port=2525).start()
    print(f"localmail SMTP listening on {srv.host}:{srv.port} (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.stop()
