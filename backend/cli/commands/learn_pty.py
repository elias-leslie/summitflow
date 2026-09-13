"""Native PTY bridge with streaming redaction and a private sanitized spool."""

from __future__ import annotations

import codecs
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time
import tty
from collections.abc import Callable, Iterable
from contextlib import suppress
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

_ANSI = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\))|(?:\x1b\[[0-?]*[ -/]*[@-~])|(?:\x1b[@-_])"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")
_PRIVATE_KEY_END = re.compile(r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----")
_MAX_PENDING_CHARS = 1_048_576
_REDACTIONS = (
    re.compile(r"pwn\.college\{[^}\r\n]{0,4096}\}", re.IGNORECASE),
    re.compile(
        r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*\Z", re.DOTALL),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:dojo_auth_token|api[_-]?key)\s*[=:]\s*)[^\s]+"),
    re.compile(r"(?i)((?:password|secret(?:\s+token)?|access[_-]?token)\s*[=:]\s*)[^\s]+"),
    re.compile(r"\b(?:sk-(?:proj-)?|gh[opusr]_)[A-Za-z0-9_-]{16,}\b"),
)


class TranscriptSpoolBusy(Exception):
    """Another local terminal already owns this study session."""


def sanitize_terminal_text(text: str) -> str:
    sanitized = _CONTROL.sub("", _ANSI.sub("", text.replace("\r\n", "\n").replace("\r", "\n")))
    for pattern in _REDACTIONS:
        if pattern.groups:
            sanitized = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", sanitized)
        else:
            sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


class StreamingRedactor:
    """Emit complete lines while holding an unsafe suffix across terminal reads."""

    def __init__(self, carry_chars: int = 16_384):
        self.carry_chars = carry_chars
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.buffer = ""
        self.discard_line = False
        self.discard_private_key = False
        self.discard_buffer = ""

    def _resume_after_discard(self, text: str) -> str:
        if self.discard_private_key:
            text = self.discard_buffer + text
            end = _PRIVATE_KEY_END.search(text)
            if not end:
                self.discard_buffer = text[-128:]
                return ""
            text = text[end.end() :]
            self.discard_private_key = False
            self.discard_buffer = ""
        if self.discard_line:
            newline = text.find("\n")
            if newline < 0:
                return ""
            text = text[newline + 1 :]
            self.discard_line = False
        return text

    @staticmethod
    def _unclosed_private_key(text: str) -> int | None:
        offset = 0
        while begin := _PRIVATE_KEY_BEGIN.search(text, offset):
            end = _PRIVATE_KEY_END.search(text, begin.end())
            if not end:
                return begin.start()
            offset = end.end()
        return None

    def _emit_ready(self) -> str:
        if len(self.buffer) <= self.carry_chars:
            return ""
        target = len(self.buffer) - self.carry_chars
        newline = self.buffer.rfind("\n", 0, target + 1)
        if newline < 0:
            return ""
        boundary = newline + 1
        for begin in _PRIVATE_KEY_BEGIN.finditer(self.buffer, 0, boundary):
            end = _PRIVATE_KEY_END.search(self.buffer, begin.end())
            if not end or end.end() > boundary:
                boundary = begin.start()
                break
        if boundary <= 0:
            return ""
        output, self.buffer = self.buffer[:boundary], self.buffer[boundary:]
        return sanitize_terminal_text(output)

    def feed(self, data: bytes) -> str:
        decoded = self._resume_after_discard(self.decoder.decode(data))
        self.buffer += decoded
        output = self._emit_ready()
        if len(self.buffer) <= _MAX_PENDING_CHARS:
            return output
        unclosed = self._unclosed_private_key(self.buffer)
        if unclosed is not None:
            output += sanitize_terminal_text(self.buffer[:unclosed])
            self.discard_private_key = True
            self.discard_buffer = self.buffer[-128:]
        else:
            self.discard_line = True
        self.buffer = ""
        return output + "[REDACTED OVERSIZE TERMINAL OUTPUT]\n"

    def finish(self) -> str:
        decoded = self._resume_after_discard(self.decoder.decode(b"", final=True))
        self.buffer += decoded
        output, self.buffer = sanitize_terminal_text(self.buffer), ""
        self.discard_line = False
        self.discard_private_key = False
        self.discard_buffer = ""
        return output


class TranscriptSpool:
    """Persist only sanitized chunks until idempotent server upload succeeds."""

    def __init__(
        self,
        session_id: str,
        harness: str,
        start_sequence: int,
        *,
        state_root: Path | None = None,
    ):
        root = state_root or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        directory = root / "learn-o-tron" / "transcripts"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        session_identity = hashlib.sha256(session_id.encode()).hexdigest()[:24]
        lock_path = directory / f"{session_identity}.lock"
        self.lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock_descriptor)
            raise TranscriptSpoolBusy(
                "Another local terminal already owns this study session"
            ) from exc
        lock_path.chmod(0o600)
        self.path = directory / f"{session_identity}.jsonl"
        self.session_id = session_id
        self.harness = harness
        pending = list(self.records())
        self.next_sequence = max(
            [start_sequence, *(int(item["sequence"]) + 1 for item in pending)],
        )

    def close(self):
        if self.lock_descriptor >= 0:
            fcntl.flock(self.lock_descriptor, fcntl.LOCK_UN)
            os.close(self.lock_descriptor)
            self.lock_descriptor = -1

    def records(self) -> Iterable[dict]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if value.get("session_id") != self.session_id or not value.get("harness"):
                raise ValueError("Transcript spool identity mismatch")
            result.append(value)
        return result

    def append(self, sanitized_text: str) -> list[dict]:
        records = []
        for offset in range(0, len(sanitized_text), 48_000):
            text = sanitized_text[offset : offset + 48_000]
            if not text:
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            record = {
                "command_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"learn-o-tron:transcript:{self.session_id}:{self.harness}:{self.next_sequence}:{digest}",
                    )
                ),
                "session_id": self.session_id,
                "sequence": self.next_sequence,
                "harness": self.harness,
                "text": text,
            }
            encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self.path.chmod(0o600)
            self.next_sequence += 1
            records.append(record)
        return records

    def drain(self, upload: Callable[[dict], None]) -> bool:
        records = list(self.records())
        try:
            for record in records:
                upload(record)
        except Exception:
            return False
        if self.path.exists():
            self.path.unlink()
        return True


def _copy_window_size(source: int, target: int):
    try:
        size = fcntl.ioctl(source, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(target, termios.TIOCSWINSZ, size)
    except OSError:
        fcntl.ioctl(target, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))


def run_terminal(
    command: list[str],
    on_sanitized: Callable[[str], None],
    on_heartbeat: Callable[[], None],
    *,
    heartbeat_seconds: int = 300,
) -> int:
    """Proxy a native terminal while forwarding only sanitized output to callbacks."""
    child_pid, child_fd = pty.fork()
    if child_pid == 0:
        os.execvp(command[0], command)

    input_fd = sys.stdin.fileno()
    output_fd = sys.stdout.fileno()
    interactive = os.isatty(input_fd)
    prior_attributes = termios.tcgetattr(input_fd) if interactive else None
    redactor = StreamingRedactor()
    prior_winch = signal.getsignal(signal.SIGWINCH)

    def resize(_signum=None, _frame=None):
        _copy_window_size(input_fd, child_fd)

    resize()
    signal.signal(signal.SIGWINCH, resize)
    if interactive:
        tty.setraw(input_fd)
    next_heartbeat = time.monotonic() + heartbeat_seconds
    status = 1
    child_reaped = False
    pending_error: BaseException | None = None
    input_open = True
    try:
        while True:
            inputs = [child_fd, *([input_fd] if input_open else [])]
            readable, _, _ = select.select(inputs, [], [], 1)
            if child_fd in readable:
                try:
                    output = os.read(child_fd, 65_536)
                except OSError:
                    output = b""
                if not output:
                    break
                os.write(output_fd, output)
                sanitized = redactor.feed(output)
                if sanitized:
                    on_sanitized(sanitized)
            if input_fd in readable:
                typed = os.read(input_fd, 4096)
                if typed:
                    os.write(child_fd, typed)
                else:
                    input_open = False
                    os.write(child_fd, b"\x04")
            if time.monotonic() >= next_heartbeat:
                on_heartbeat()
                next_heartbeat = time.monotonic() + heartbeat_seconds
        _, raw_status = os.waitpid(child_pid, 0)
        child_reaped = True
        status = os.waitstatus_to_exitcode(raw_status)
    except BaseException as exc:
        pending_error = exc
    finally:
        try:
            final = redactor.finish()
            if final:
                on_sanitized(final)
        except BaseException as exc:
            if pending_error is None:
                pending_error = exc
        if not child_reaped:
            with suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGHUP)
            with suppress(ChildProcessError):
                os.waitpid(child_pid, 0)
        signal.signal(signal.SIGWINCH, prior_winch)
        if interactive and prior_attributes is not None:
            termios.tcsetattr(input_fd, termios.TCSADRAIN, prior_attributes)
        os.close(child_fd)
    if pending_error is not None:
        raise pending_error
    return status
