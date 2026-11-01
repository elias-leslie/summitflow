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

Two delivery classes (Tether API 24, coord_deliver). Wake items: a request, an ack with a note or an eta, a
memory notice. Ride-along items: an FYI note (`st sessions send --fyi`) and an `ack yes` that closed the
request for its sender (bare, or from the sender's own lane: coord_deliver.settle_bare_ack). They are shown
once by the turn hook, never wake an idle agent (`wakeable` and the watcher leave them out, Pi's idle check
too), never block Stop, and ride along with the next wake. Tether's own
ride-along lines (a lane's repeated went-idle line, a coordination line for these items) are taken at the
window's next prompt (UserPromptSubmit; Pi's next tool result), only by the window's own agent (not a harness
nested in it): peeked first thing (GET /v1/sessions/<window>/due?ride=peek) and taken once printed (DELETE
...?token=, Tether API 25), so a hook that times out loses none; API 24 takes them at once (?ride=1).

Senders queue the same line when they record a request or ack; the woke state
(cli.lib.coord_wake) keeps the watcher and Pi's idle check from waking the
agent again for an item a line was queued for.

An idle wake (the watcher, Pi's idle check) comes once per item: a request or
ack the agent was woken for or shown in a turn never wakes it again; an eta ack
whose minutes ran out wakes it once more. An item younger than GRACE seconds is
left to its sender, who queues the line right after writing the ledger row, so
the watcher never races it into a second wake. Turn hooks and Stop still show
an unanswered request again every REMIND seconds. Text starting with
URGENT/CONFLICT is flagged as such. The same surfaces carry memory notices (cli.lib.coord_memory): a process in this pane
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
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

STARTED = time.monotonic()
sys.path.insert(0, sys.argv[1])
from cli.lib import coord, coord_deliver, coord_lineage, coord_memory, coord_wake, leases  # type: ignore[import-not-found]  # noqa: E402  # SummitFlow backend on sys.path

REMIND = 300
GRACE = 5.0  # a ledger item this young is its sender's to wake for (coord_deliver.wake right after the write)
POLL = 2.0
WATCH_SECONDS = int(os.environ.get("ST_COORD_WATCH_SECONDS") or 6 * 3600 - 120)
RETRY = 10.0  # re-check a busy pane this soon instead of waiting for the next ledger change
MEM_RECHECK = float(REMIND)  # a memory notice a Tether line announced: its text (and key) changes, so not sooner
# The harnesses' turn-hook limit (~/.claude/settings.json, ~/.codex/hooks.json, pi-coord-extension.ts runHook).
HOOK_SECONDS = float(os.environ.get("ST_COORD_HOOK_SECONDS") or 5)
# Ride-along lines are confirmed (taken) only with this much of it left: a hook killed after the take would lose
# them, while one left unconfirmed shows them again next turn (the confirm's own timeout is 0.5 s).
CONFIRM_LEFT = 1.5
# withdraw_stale's worst case (a delete, a re-queue and their lookups): run only with that much hook time left, since a
# hook killed after it printed loses its output and the closed acks it already marked shown.
WITHDRAW_LEFT = 3.0
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


class Item(NamedTuple):
    """One inbox item: its state key, the line shown, URGENT, and when it happened (epoch seconds; 0 unknown).

    ``at`` is the request's creation, the time an eta ack's minutes ran out, or the ack's time. ``ride`` marks
    a ride-along item (an FYI note, a closed bare ack): shown once, never an idle wake.
    """

    key: str
    line: str
    urgent: bool
    at: float = 0.0
    ride: bool = False


def _epoch(stamp: object) -> float:
    try:
        return datetime.fromisoformat(str(stamp)).timestamp()
    except ValueError:
        return 0.0


def pending() -> tuple[str, list[Item]]:
    """(agent_id, items) for requests to me and acks of my requests."""
    agent_id = leases.identify_agent()[0]
    mine = leases.self_ids()
    items: list[Item] = []
    for row in coord.inbox():
        if row["state"] == "fyi" and row["from"] not in mine:
            items.append(Item(f"{row['id']}:fyi", (
                f"FYI {row['id']} from {row['from']}: {row['text']} | no reply needed"), False,
                _epoch(row.get("created")), True))
        elif row["state"] == "open" and row["from"] not in mine:
            urgent = _urgent(row["text"])
            flag = "URGENT " if urgent else ""
            eta = row.get("intent") == "eta"
            lapsed = f" (your eta:{row['eta_min']} ran out)" if eta else ""
            at = _epoch(row.get("created"))
            if eta and row.get("acked_at") and row.get("eta_min") is not None:
                at = _epoch(row["acked_at"]) + 60 * int(row["eta_min"])
            items.append(Item(f"{row['id']}:req", (
                f"{flag}REQUEST {row['id']} from {row['from']}{lapsed}: {row['text']} | answer now: "
                f"{coord.ACK_HINT.format(id=row['id'])}"), urgent, at))
        elif row["state"] == "acked" and row["from"] in mine:
            intent = (row.get("intent") or "?") + (f" {row['eta_min']}m" if row.get("eta_min") else "")
            note = f" ({row['note']})" if row.get("note") else ""
            items.append(Item(f"{row['id']}:ack:{row.get('acked_at')}", (
                f"ACK {row['id']} {intent}{note} from {row.get('acked_by')} | close with "
                f"`st sessions confirm {row['id']}`"), False, _epoch(row.get("acked_at"))))
    for row in coord.closed_acks():
        note = f" ({row['note']})" if row.get("note") else ""
        items.append(Item(f"{row['id']}:ack:{row.get('acked_at')}", (
            f"ACK {row['id']} yes{note} from {row.get('acked_by')} | closed; nothing to do"), False,
            _epoch(row.get("acked_at")), True))
    return agent_id, items


def due(agent_id: str, items: list[Item]) -> list[Item]:
    """What a turn hook or Stop shows: a request again every REMIND seconds until answered, an ack or FYI once."""
    seen = _load_seen(agent_id)
    now = time.time()
    return [item for item in items
            if (item.key not in seen if ":ack:" in item.key or item.ride else now - seen.get(item.key, 0) >= REMIND)]


def wakeable(agent_id: str, items: list[Item], now: float | None = None) -> list[Item]:
    """What an idle wake is for: items the agent was neither woken for nor shown since they happened.

    Once per item: a request or ack whose key a Tether line was queued for (woke) or a hook showed
    (seen) at or after its time never wakes the agent again; an eta that ran out since does, once.
    Items younger than GRACE are left to the sender's own line (see ``settling``). Ride-along items
    (an FYI note, a closed bare ack) never wake an idle agent.
    """
    seen, woke = _load_seen(agent_id), coord_wake.load_woke(agent_id)
    now = time.time() if now is None else now

    def new(item: Item) -> bool:
        stamp = max(seen.get(item.key, 0.0), woke.get(item.key, 0.0))
        return stamp < item.at if item.at else not stamp  # no known time: only if never woken or shown

    return [item for item in items if not item.ride and item.at <= now - GRACE and new(item)]


def settling(items: list[Item], now: float | None = None) -> float | None:
    """When the youngest item still inside GRACE leaves it (look again then), or None."""
    now = time.time() if now is None else now
    ends = [item.at + GRACE for item in items if item.at > now - GRACE]
    return min(ends) if ends else None


def tether_wake(agent_id: str, items: list[Item],
                note: coord_memory.Notice | None) -> str:
    """Queue this agent's [Message] line on its Aico window through Tether (coord_deliver).

    "queued"; "covered" when the window's line would name nothing (an ack its own
    reply wait reports: Tether's [Ready] line is the wake); "retry" when Tether did
    not answer (never type then: the line may be queued, and a retry replaces
    it); "direct" for today's path. The memory notice's lock is released before
    any HTTP call.
    """
    try:
        if not coord_deliver.enabled() or (who := coord_deliver.target(agent_id)) is None:
            return "direct"
        text = note.text if note else None
        if note:
            note.done(delivered=False)  # the turn hook shows it in full
        queued = coord_deliver.wake(agent_id, [item.key for item in items], memory=text)
        if queued is None and text is None and coord_deliver.summary(who) is None:
            _trace(agent_id, "tether-covered", [item.key for item in items])
            return "covered"
    except coord_deliver.Unsettled:
        return "retry"
    except Exception:  # noqa: BLE001 - fail open to the direct wake
        return "direct"
    if queued is None:
        return "direct"
    _trace(agent_id, f"tether-queued:{queued['delivery'].get('id')}",
           [item.key for item in items] + ([coord_deliver.memory_key(text)] if text else []))
    return "queued"


def superseded(agent_id: str) -> bool:
    """A context reset gave this window a newer main identity; its own watcher takes over."""
    try:
        found = coord_deliver.target(agent_id) if coord_deliver.enabled() else None
    except Exception:  # noqa: BLE001 - keep watching
        return False
    return found is not None and found.agent_id != agent_id


def _trace(agent_id: str, how: str, keys: list[str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with open(STATE / "surfaced.log", "a") as log:  # content-free delivery trace
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z"
        log.write(f"{stamp} {agent_id} {how} {','.join(keys)}\n")


def mark(agent_id: str, items: list[Item], how: str = "") -> None:
    seen = _load_seen(agent_id)
    now = time.time()
    seen.update({item.key: now for item in items})
    _save_seen(agent_id, seen)
    _trace(agent_id, how, [item.key for item in items])


def render(items: list[Item]) -> str:
    waiting = any(":req" in item.key for item in items)
    if waiting:
        head = "st coordination (another agent is waiting on you; reply before continuing):"
    elif all(item.ride for item in items):
        head = "st coordination (FYI; nothing to answer):"
    else:
        head = "st coordination (update on a request you sent):"
    return "\n".join([head, *(item.line for item in sorted(items, key=lambda i: not i.urgent))])


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


SCRIPT = os.path.realpath(__file__)


def _lock_holder(lock) -> int | None:  # noqa: ANN001 - an open file
    """PID holding the flock on ``lock``'s file, or None.

    /proc/locks names the file by inode (its device field is the superblock's, which differs from
    st_dev on btrfs), so a candidate counts only when it has this very file open.
    """
    info = os.fstat(lock.fileno())
    try:
        lines = Path("/proc/locks").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) < 6 or parts[1] != "FLOCK" or not parts[4].isdigit() or parts[5].rsplit(":", 1)[-1] != str(info.st_ino):
            continue
        pid = int(parts[4])
        try:
            fds = list(Path(f"/proc/{pid}/fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                other = fd.stat()
            except OSError:
                continue
            if (other.st_dev, other.st_ino) == (info.st_dev, info.st_ino):
                return pid
    return None


def take_over(lock) -> bool:  # noqa: ANN001 - an open file
    """Stop a watcher of another release holding this agent's lock and take the lock; False leaves it running.

    A watcher lives up to WATCH_SECONDS on the code it started with, and every later hook start finds
    the lock held, so a fix reached running sessions only hours after a deploy (2026-10-31: watchers
    from before the Tether change still woke agents a second time). Now a deploy takes effect at the
    agent's next turn. Only a coord_inbox.py watcher from another path is stopped.
    """
    pid = _lock_holder(lock)
    if pid is None or pid == os.getpid():
        return False
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    scripts = [a.decode(errors="replace") for a in argv if a.endswith(b"coord_inbox.py")]
    if not scripts or b"watch" not in argv or os.path.realpath(scripts[0]) == SCRIPT:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            time.sleep(0.05)
    return False


def watch(provider: str) -> int:
    agent_id = leases.identify_agent()[0]
    anchor = coord_lineage.harness()[0]
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / f"{_key(agent_id)}.{provider}-watch.lock", "w")  # noqa: SIM115
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not take_over(lock):
            return 0  # one watcher per agent
    deadline = time.time() + WATCH_SECONDS
    last_mtime = -1.0
    recheck = 0.0  # read the ledger again by then even when it did not change
    mem_retry = 0.0
    while time.time() < deadline:
        if anchor and not coord_lineage.anchor_alive(anchor):
            return 0
        try:
            mtime = LEDGER.stat().st_mtime
        except OSError:
            mtime = 0.0
        now = time.time()
        fresh: list[Item] = []
        if mtime != last_mtime or now >= recheck:
            last_mtime, recheck = mtime, now + 60
            agent_id, items = pending()
            fresh = wakeable(agent_id, items, now)
            settled = settling(items, now)
            if settled is not None:
                recheck = min(recheck, settled)  # its sender's line has had GRACE to be queued by then
        if fresh and superseded(agent_id):
            return 0
        note = memory(agent_id) if now >= mem_retry else None
        if note and coord_deliver.memory_key(note.text) in coord_wake.load_woke(agent_id):
            note.done(delivered=False)  # a Tether line already says so; the turn hook shows it
            note, mem_retry = None, now + MEM_RECHECK
        if fresh or note:
            how = tether_wake(agent_id, fresh, note)
            if how != "direct":
                # Tether delivers when the agent is idle and nobody types; keep watching for new items.
                if note:
                    mem_retry = now + (MEM_RECHECK if how == "queued" else RETRY)
                if how == "retry":
                    recheck = now + RETRY
                time.sleep(POLL)
                continue
            if note and note._lock.closed:
                note = memory(agent_id)  # released for a Tether call that was refused: take it again
            if provider == "codex":
                # Codex: wake the pane; its UserPromptSubmit hook then shows the memory notice in full
                if note:
                    note.done(delivered=False)
                sock = os.environ.get("TMUX", "").split(",")[0]
                line = (coord_wake.pane_line(render(fresh), sum(":req" in item.key for item in fresh)) if fresh
                        else coord_memory.WAKE_LINE)
                if not coord_wake.type_line(line, sock, os.environ.get("TMUX_PANE", "")):
                    recheck = now + RETRY  # busy composer: leave it queued, look again soon
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
    # Ride-along lines first, before the slower inbox work below eats the hook's time.
    ride = take_ride(leases.identify_agent()[0]) if mode == "turn" and takes_ride(provider, event) else None
    agent_id, items = pending()
    if mode == "turn" and provider == "codex" and event == "UserPromptSubmit":
        disarm_codex(agent_id)
    # Pi's idle check is a wake of its own: once per item, like the watcher (a Tether line may already wake it).
    fresh = wakeable(agent_id, items) if provider == "pi" and event == "PiIdle" else due(agent_id, items)
    if mode == "stop":
        if any(":req" in item.key for item in fresh):  # only a waiting requester justifies continuing
            print(json.dumps({"decision": "block", "reason": render(fresh)}), flush=True)
            mark(agent_id, fresh, f"{provider}-stop-block")
        elif provider == "codex":
            arm_codex(agent_id, backend)
        return 0
    # Printed before marked seen: a hook killed in between shows an item again, never loses it (a closed ack's note).
    emit(event, fresh, memory(agent_id), ride.text if ride else "")
    if fresh:
        mark(agent_id, fresh, f"{provider}-{event or mode}")
    if ride:  # printed: now Tether may let them go, unless the hook may be killed before it exits
        if time.monotonic() - STARTED <= HOOK_SECONDS - CONFIRM_LEFT:
            sys.stdout.flush()
            coord_deliver.confirm_ride(ride.widget, ride.lines)
        else:
            _trace(agent_id, "ride-unconfirmed", [])
    if mode == "turn" and time.monotonic() - STARTED <= HOOK_SECONDS - WITHDRAW_LEFT:
        try:  # a queued [Message] line nothing waits for any more is taken back before it is pasted
            if coord_deliver.withdraw_stale(agent_id):
                _trace(agent_id, "tether-withdrawn", [])
        except Exception:  # noqa: BLE001 - best effort; a stale line only costs one look at an empty inbox
            pass
    return 0


def takes_ride(provider: str, event: str) -> bool:
    """The turns that carry Tether's ride-along lines: a new prompt (Claude Code, Codex), Pi's next tool result."""
    return event == "UserPromptSubmit" or (provider == "pi" and event == "PostToolUse")


class Ride(NamedTuple):
    """Ride-along lines peeked for this window: the text to print, and what confirms them once printed."""

    widget: str
    lines: coord_deliver.Ride

    @property
    def text(self) -> str:
        return self.lines.text


def take_ride(agent_id: str) -> Ride | None:
    """The ride-along lines Tether holds for this window (a lane's repeated went-idle line, ...), or None.

    Only for the window's own agent: a harness nested in it (a ``claude -p`` or ``codex exec`` an agent runs)
    inherits AICO_WIDGET_ID but is not the one they are for (coord_deliver.target answers None for it).
    """
    widget = os.environ.get("AICO_WIDGET_ID", "")
    try:
        if not widget or not coord_deliver.enabled():
            return None
        who = coord_deliver.target(agent_id)
        if who is None or who.widget != widget:
            return None
        lines = coord_deliver.take_ride(widget)
    except Exception:  # noqa: BLE001 - best effort; they stay queued or join the next wake
        return None
    return Ride(widget, lines) if lines else None


def emit(event: str, fresh: list[Item], note: coord_memory.Notice | None, ride: str = "") -> None:
    """Print coordination items, Tether's ride-along lines and a memory notice as one additionalContext; the notice counts once printed."""
    text = "\n\n".join(t for t in (render(fresh) if fresh else "", ride, note.text if note else "") if t)
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
