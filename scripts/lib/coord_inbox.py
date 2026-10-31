"""Prompt delivery of `st sessions send --delivery handshake` requests and acks.

The handshake ledger (~/.summitflow/leases/_coord.json, owned by SummitFlow
cli.lib.coord) is passive: before this hook a target only saw a request when it
ran `st pulse` / `st sessions inbox`, hit an edit collision, or reset. This
module surfaces new requests addressed to the current agent (and acks of
requests it sent) on every harness surface that can carry text:

  turn   UserPromptSubmit / PostToolUse(Failure) / SessionStart
                                             additionalContext (Claude + Codex)
  stop   Stop                                decision=block so the turn continues
                                             and answers; on Codex, arms `watch`
  watch  In an Aico window with Tether API 16: queues one content-free
                 `[Message] …` line on the window's gated delivery queue
                 (cli.lib.coord_deliver) and keeps watching; Tether delivers it
                 when the agent is idle and nobody types. Otherwise:
         Claude: asyncRewake background hook (exit 2 wakes an idle session;
                 claude-config labels it a plain "Coordination inbox" notice)
         Codex:  detached idle watcher that types one line into its own tmux
                 pane (Codex has no rewake hook; only armed between turns)

Senders queue the same line when they record a request or ack; the woke state
(cli.lib.coord_wake) keeps the watcher and Pi's idle check from waking the
agent again for an item a line was queued for.

Requests surface once per agent, then again every REMIND seconds while still
unanswered (an eta ack whose minutes ran out counts as unanswered again); an
ack surfaces once. Text starting with URGENT/CONFLICT is flagged as such. The same
surfaces carry memory notices (cli.lib.coord_memory): a process in this pane
killed for memory, a stopped pane, a memory warning. Each shows once per agent
and per subagent, needs no answer and never blocks Stop; SessionStart,
SubagentStart and subagent tool hooks carry only these. Fails open
and is silent when nothing is waiting. Without Tether's queue, pane typing
goes only through cli.lib.coord_wake.type_line (idle pane, empty composer), the
single injection path; `st sessions send --delivery native-thread` to a live
Codex thread writes the ledger and wakes it the same way as a handshake send.
Usage (via scripts/lib/coord-inbox): python coord_inbox.py <summitflow-backend> <mode> [provider]
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, sys.argv[1])
from cli.lib import coord, coord_deliver, coord_lineage, coord_memory, coord_wake, leases  # type: ignore[import-not-found]  # noqa: E402  # SummitFlow backend on sys.path

REMIND = 300
POLL = 2.0
WATCH_SECONDS = int(os.environ.get("ST_COORD_WATCH_SECONDS") or 6 * 3600 - 120)
RETRY = 10.0  # re-check a busy pane this soon instead of waiting for the next ledger change
MEM_RECHECK = 30.0  # a memory notice a Tether line already announced: look again this much later
STATE = coord_wake.STATE
LEDGER = leases.LEASES_DIR / "_coord.json"
_key = coord_wake.state_key
_load_seen = coord_wake.load_seen


def memory(agent: str, resumed: bool = False) -> coord_memory.Notice | None:
    """This agent's memory notice, or None; a failure here never costs the coordination items."""
    try:
        return coord_memory.check(agent, resumed=resumed, paths=coord_memory.Paths(state_dir=STATE))
    except Exception:  # noqa: BLE001 - fail open: no notice
        return None


def _save_seen(agent_id: str, seen: dict[str, float]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 86400
    path = coord_wake.seen_path(agent_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v for k, v in seen.items() if v > cutoff}))
    tmp.replace(path)


def _urgent(text: str) -> bool:
    return text.lstrip("[!( ").upper().startswith(("URGENT", "CONFLICT", "CRITICAL"))


def pending() -> tuple[str, list[tuple[str, str, bool]]]:
    """(agent_id, [(key, line, urgent)]) for requests to me and acks of my requests."""
    agent_id = leases.identify_agent()[0]
    mine = leases.self_ids()
    items: list[tuple[str, str, bool]] = []
    for row in coord.inbox():
        if row["state"] == "open" and row["from"] not in mine:
            urgent = _urgent(row["text"])
            flag = "URGENT " if urgent else ""
            lapsed = f" (your eta:{row['eta_min']} ran out)" if row.get("intent") == "eta" else ""
            items.append((f"{row['id']}:req", (
                f"{flag}REQUEST {row['id']} from {row['from']}{lapsed}: {row['text']} | answer now with "
                f"`st sessions ack {row['id']} yes|no 'reason'|eta:MIN`"), urgent))
        elif row["state"] == "acked" and row["from"] in mine:
            intent = (row.get("intent") or "?") + (f" {row['eta_min']}m" if row.get("eta_min") else "")
            note = f" ({row['note']})" if row.get("note") else ""
            items.append((f"{row['id']}:ack:{row.get('acked_at')}", (
                f"ACK {row['id']} {intent}{note} from {row.get('acked_by')} | close with "
                f"`st sessions confirm {row['id']}`"), False))
    return agent_id, items


def due(agent_id: str, items: list[tuple[str, str, bool]]) -> list[tuple[str, str, bool]]:
    seen = _load_seen(agent_id)
    now = time.time()
    # Requests re-surface every REMIND seconds until answered; an ack surfaces once.
    return [item for item in items
            if (item[0] not in seen if ":ack:" in item[0] else now - seen.get(item[0], 0) >= REMIND)]


def wakeable(agent_id: str, items: list[tuple[str, str, bool]]) -> list[tuple[str, str, bool]]:
    """Due items no Tether line was queued for lately: a request again after REMIND, an ack once."""
    woke = coord_wake.load_woke(agent_id)
    now = time.time()
    return [item for item in items
            if (item[0] not in woke if ":ack:" in item[0] else now - woke.get(item[0], 0) >= REMIND)]


def tether_wake(agent_id: str, items: list[tuple[str, str, bool]],
                note: coord_memory.Notice | None) -> bool:
    """Queue this agent's [Message] line on its Aico window through Tether (coord_deliver); False keeps today's path."""
    try:
        queued = coord_deliver.wake(agent_id, [key for key, _, _ in items], memory=note.text if note else None)
    except Exception:  # noqa: BLE001 - fail open to the direct wake
        return False
    if queued is None:
        return False
    _trace(agent_id, f"tether-queued:{queued['delivery'].get('id')}",
           [key for key, _, _ in items] + ([coord_deliver.memory_key(note.text)] if note else []))
    return True


def _trace(agent_id: str, how: str, keys: list[str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with open(STATE / "surfaced.log", "a") as log:  # content-free delivery trace
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z"
        log.write(f"{stamp} {agent_id} {how} {','.join(keys)}\n")


def mark(agent_id: str, items: list[tuple[str, str, bool]], how: str = "") -> None:
    seen = _load_seen(agent_id)
    now = time.time()
    seen.update({key: now for key, _, _ in items})
    _save_seen(agent_id, seen)
    _trace(agent_id, how, [k for k, _, _ in items])


def render(items: list[tuple[str, str, bool]]) -> str:
    waiting = any(":req" in key for key, _, _ in items)
    head = ("st coordination (another agent is waiting on you; reply before continuing):" if waiting
            else "st coordination (update on a request you sent):")
    return "\n".join([head, *(line for _, line, _ in sorted(items, key=lambda i: not i[2]))])


def disarm_codex(agent_id: str) -> None:
    """A turn started: the idle watcher must never type into an active composer."""
    pid = coord_wake.codex_watch_pid(agent_id)
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    coord_wake.codex_pidfile(agent_id).unlink(missing_ok=True)


def arm_codex(agent_id: str, backend: str) -> None:
    """Start one detached idle watcher bound to this Codex identity and tmux pane."""
    if not os.environ.get("TMUX") or not os.environ.get("TMUX_PANE"):
        return
    anchor, provider = coord_lineage.harness()
    if not anchor:
        return
    disarm_codex(agent_id)
    STATE.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "ST_COORD_ANCHOR": anchor, "ST_COORD_HARNESS": provider or "codex"}
    proc = subprocess.Popen(
        [sys.executable, "-I", __file__, backend, "watch", "codex"],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    coord_wake.codex_pidfile(agent_id).write_text(str(proc.pid))


def watch(provider: str) -> int:
    agent_id = leases.identify_agent()[0]
    anchor = coord_lineage.harness()[0]
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / f"{_key(agent_id)}.{provider}-watch.lock", "w")  # noqa: SIM115
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # one watcher per agent
    deadline = time.time() + WATCH_SECONDS
    last_mtime = -1.0
    last_check = 0.0
    mem_retry = 0.0
    while time.time() < deadline:
        if anchor and not coord_lineage.anchor_alive(anchor):
            return 0
        try:
            mtime = LEDGER.stat().st_mtime
        except OSError:
            mtime = 0.0
        now = time.time()
        fresh: list[tuple[str, str, bool]] = []
        if mtime != last_mtime or now - last_check >= 60:
            last_mtime, last_check = mtime, now
            agent_id, items = pending()
            fresh = due(agent_id, items)
        note = memory(agent_id) if now >= mem_retry else None
        if note and coord_deliver.memory_key(note.text) in coord_wake.load_woke(agent_id):
            note.done(delivered=False)  # a Tether line already says so; the turn hook shows it
            note, mem_retry = None, now + MEM_RECHECK
        fresh = wakeable(agent_id, fresh)
        if fresh or note:
            if tether_wake(agent_id, fresh, note):
                # Tether delivers when the agent is idle and nobody types; keep watching for reminders.
                if note:
                    note.done(delivered=False)
                    mem_retry = now + MEM_RECHECK
                time.sleep(POLL)
                continue
            if provider == "codex":
                # Codex: wake the pane; its UserPromptSubmit hook then shows the memory notice in full
                if note:
                    note.done(delivered=False)
                sock = os.environ.get("TMUX", "").split(",")[0]
                line = (coord_wake.pane_line(render(fresh), sum(":req" in key for key, _, _ in fresh)) if fresh
                        else coord_memory.WAKE_LINE)
                if not coord_wake.type_line(line, sock, os.environ.get("TMUX_PANE", "")):
                    last_check = now - 60 + RETRY  # busy composer: leave it queued, look again soon
                    mem_retry = now + RETRY
                    time.sleep(POLL)
                    continue
                if fresh:
                    mark(agent_id, fresh, "codex-tmux-wake")
                coord_wake.codex_pidfile(agent_id).unlink(missing_ok=True)
                return 0
            if fresh:
                mark(agent_id, fresh, "claude-rewake")
            if note:
                note.done()
            print("\n\n".join(t for t in (render(fresh) if fresh else "", note.text if note else "") if t),
                  file=sys.stderr)
            return 2  # asyncRewake: wake Claude, even when idle
        time.sleep(POLL)
    return 0


def main() -> int:
    backend, mode = sys.argv[1], sys.argv[2]
    provider = sys.argv[3] if len(sys.argv) > 3 else "claude_code"
    if mode == "watch" and os.environ.get("ST_COORD_ANCHOR"):
        return watch(provider)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    event = str(payload.get("hook_event_name") or "")
    subagent = str(payload.get("agent_id") or "") if provider == "claude_code" else ""
    if subagent:  # Claude subagent hooks share the parent session id: coordination items stay for the parent
        if mode == "turn":
            emit(event, [], memory(f"{leases.identify_agent()[0]}/{subagent}"))
        return 0
    coord.adopt_hook_identity(payload)
    # Register every turn, not only on edits: an agent that only reads and messages must stay addressable.
    try:
        coord_lineage.observe()
    except Exception:  # noqa: BLE001 - registration is best effort; the inbox still answers
        pass
    if mode == "watch":
        return watch(provider)
    if mode == "turn" and event == "SessionStart":
        emit(event, [], memory(leases.identify_agent()[0], resumed=payload.get("source") == "resume"))
        return 0
    agent_id, items = pending()
    if mode == "turn" and provider == "codex" and event == "UserPromptSubmit":
        disarm_codex(agent_id)
    fresh = due(agent_id, items)
    if provider == "pi" and event == "PiIdle":
        # Pi's idle check is a wake of its own: skip what a Tether line already wakes it for.
        fresh = wakeable(agent_id, fresh)
    if mode == "stop":
        if any(":req" in key for key, _, _ in fresh):  # only a waiting requester justifies continuing
            mark(agent_id, fresh, f"{provider}-stop-block")
            print(json.dumps({"decision": "block", "reason": render(fresh)}))
        elif provider == "codex":
            arm_codex(agent_id, backend)
        return 0
    if fresh:
        mark(agent_id, fresh, f"{provider}-{event or mode}")
    emit(event, fresh, memory(agent_id))
    return 0


def emit(event: str, fresh: list[tuple[str, str, bool]], note: coord_memory.Notice | None) -> None:
    """Print coordination items and a memory notice as one additionalContext; the notice counts once printed."""
    text = "\n\n".join(t for t in (render(fresh) if fresh else "", note.text if note else "") if t)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event or "PostToolUse", "additionalContext": text}}),
              flush=True)
    if note:
        note.done()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never wedge a harness
        print(f"coord-inbox: {type(exc).__name__}; allowing", file=sys.stderr)
        sys.exit(0)
