import pytest

from cli.commands.learn_pty import (
    StreamingRedactor,
    TranscriptSpool,
    TranscriptSpoolBusy,
    sanitize_terminal_text,
)

_KEY_LABEL = b"OPENSSH PRIVATE KEY"
_KEY_BEGIN = b"-----BEGIN " + _KEY_LABEL + b"-----"
_KEY_END = b"-----END " + _KEY_LABEL + b"-----"


def test_streaming_redactor_catches_split_flags_credentials_and_terminal_controls():
    redactor = StreamingRedactor(carry_chars=64)
    output = redactor.feed(b"A" * 80 + b"\x1b[31mpwn.college{split-")
    output += redactor.feed(b"secret}\x1b[0m password: hidden\n")
    output += redactor.finish()
    assert "split-secret" not in output
    assert "hidden" not in output
    assert "\x1b" not in output
    assert output.count("[REDACTED]") == 2


def test_streaming_redactor_holds_partial_credentials_and_private_key_blocks():
    redactor = StreamingRedactor(carry_chars=16)
    output = redactor.feed(b"safe line\npassword: sec")
    output += redactor.feed(
        b"ret\n" + _KEY_BEGIN + b"\nprivate-material\n"
    )
    output += redactor.feed(_KEY_END + b"\nafter\n")
    output += redactor.finish()
    assert "secret" not in output
    assert "private-material" not in output
    assert "safe line" in output
    assert "after" in output
    assert output.count("[REDACTED]") == 2


def test_streaming_redactor_redacts_second_unfinished_private_key_at_eof():
    redactor = StreamingRedactor(carry_chars=16)
    output = redactor.feed(
        _KEY_BEGIN
        + b"\nfirst\n"
        + _KEY_END
        + b"\nsafe\n"
        + _KEY_BEGIN
        + b"\nsecond-private-material"
    )
    output += redactor.finish()
    assert "first" not in output
    assert "second-private-material" not in output
    assert "safe" in output
    assert output.count("[REDACTED]") == 2


def test_streaming_redactor_bounds_a_terminal_line_without_newlines():
    redactor = StreamingRedactor(carry_chars=16)
    output = redactor.feed(b"x" * 1_048_577)
    output += redactor.feed(b"discarded-sensitive-suffix\nsafe-after\n")
    output += redactor.finish()
    assert output == "[REDACTED OVERSIZE TERMINAL OUTPUT]\nsafe-after\n"


def test_streaming_redactor_discards_oversized_unfinished_private_key_until_end():
    redactor = StreamingRedactor(carry_chars=16)
    output = redactor.feed(
        _KEY_BEGIN + b"\n" + b"x" * 1_048_577
    )
    output += redactor.feed(
        b"private-suffix\n" + _KEY_END + b"\nsafe-after\n"
    )
    output += redactor.finish()
    assert "private-suffix" not in output
    assert output.endswith("safe-after\n")


def test_oversized_private_key_discard_handles_split_end_marker():
    redactor = StreamingRedactor(carry_chars=16)
    output = redactor.feed(
        _KEY_BEGIN + b"\n" + b"x" * 1_048_577
    )
    output += redactor.feed(b"private-suffix\n-----END OPENSSH PRIV")
    output += redactor.feed(b"ATE KEY-----\nsafe-after\n")
    output += redactor.finish()
    assert "private-suffix" not in output
    assert output.endswith("safe-after\n")


def test_oversized_private_key_preserves_end_prefix_from_threshold_read():
    redactor = StreamingRedactor(carry_chars=16)
    output = redactor.feed(
        _KEY_BEGIN
        + b"\n"
        + b"x" * 1_048_577
        + b"\n-----END OPENSSH PRIV"
    )
    output += redactor.feed(b"ATE KEY-----\nsafe-after\n")
    output += redactor.finish()
    assert output.endswith("safe-after\n")


def test_sanitized_spool_is_private_idempotent_and_removed_after_upload(tmp_path):
    text = sanitize_terminal_text("flag pwn.college{raw-secret}\n")
    spool = TranscriptSpool(
        "study-session:one",
        "codex",
        0,
        state_root=tmp_path,
    )
    records = spool.append(text)
    assert len(records) == 1
    assert "raw-secret" not in spool.path.read_text()
    assert spool.path.stat().st_mode & 0o077 == 0
    uploaded = []
    assert spool.drain(uploaded.append) is True
    assert uploaded == records
    assert not spool.path.exists()
    spool.close()


def test_transcript_spool_exclusively_locks_a_session_across_harnesses(tmp_path):
    first = TranscriptSpool("study-session:one", "codex", 0, state_root=tmp_path)
    records = first.append("pending\n")
    with pytest.raises(TranscriptSpoolBusy):
        TranscriptSpool("study-session:one", "claude", 0, state_root=tmp_path)
    first.close()
    second = TranscriptSpool("study-session:one", "claude", 0, state_root=tmp_path)
    assert list(second.records()) == records
    assert second.next_sequence == 1
    second.close()
