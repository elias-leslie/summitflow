"""Admission regression fixtures: no real builds/scans or external services."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path

import pytest

from app.utils import heavy_work as guard

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "lane"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", directory)
    monkeypatch.delenv("ST_HEAVY_LEASE", raising=False)
    # Strict single-heavy semantics unless a test opts into spare capacity.
    monkeypatch.setattr(guard, "_spare_capacity", lambda: False)
    return directory


def _bootstrap(lane: Path) -> str:
    return (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(BACKEND)!r}); "
        "from app.utils import heavy_work as guard; "
        f"guard._LOCK_DIRECTORY = Path({str(lane)!r}); "
        "guard._spare_capacity = lambda: False; "
    )


def _queued_actor(lane: Path, tmp_path: Path, label: str, *, paused: bool = False) -> subprocess.Popen[str]:
    code = _bootstrap(lane) + f"""
import time
ready = Path({str(tmp_path / (label + '-ready'))!r})
resume = Path({str(tmp_path / (label + '-resume'))!r})
original_sleep = time.sleep
def sleep(duration):
    ready.touch()
    while {paused!r} and not resume.exists():
        original_sleep(0.01)
    original_sleep(duration)
guard.time.sleep = sleep
with guard.heavy_work({label!r}):
    with Path({str(tmp_path / 'order')!r}).open('a') as order:
        order.write({label!r} + '\\n')
"""
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_registered_waiter_cannot_be_overtaken_by_later_process(lane: Path, tmp_path: Path) -> None:
    actors = []
    try:
        with guard.heavy_work("A"):
            actors.append(_queued_actor(lane, tmp_path, "B", paused=True))
            _wait_file(tmp_path / "B-ready", actors[0])
            actors.append(_queued_actor(lane, tmp_path, "C"))
            _wait_file(tmp_path / "C-ready", actors[1])
        # B is deliberately descheduled after registering. C must still wait.
        with pytest.raises(subprocess.TimeoutExpired):
            actors[1].communicate(timeout=0.3)
    finally:
        (tmp_path / "B-resume").touch()
        for actor in actors:
            output = actor.communicate(timeout=5)
            assert actor.returncode == 0, output
    assert (tmp_path / "order").read_text().splitlines() == ["B", "C"]


def test_releasing_owner_reacquires_behind_registered_waiter(lane: Path, tmp_path: Path) -> None:
    actor = None
    resume = None
    try:
        with guard.heavy_work("A"):
            actor = _queued_actor(lane, tmp_path, "B", paused=True)
            _wait_file(tmp_path / "B-ready", actor)
            resume = threading.Timer(0.3, (tmp_path / "B-resume").touch)
            resume.start()
        with guard.heavy_work("A again"), (tmp_path / "order").open("a") as order:
            order.write("A\n")
    finally:
        (tmp_path / "B-resume").touch()
        if resume is not None:
            resume.join(2)
        if actor is not None:
            output = actor.communicate(timeout=5)
            assert actor.returncode == 0, output
    assert (tmp_path / "order").read_text().splitlines() == ["B", "A"]


@pytest.mark.parametrize("victim", ["B", "C"])
def test_killed_head_or_middle_waiter_does_not_block_survivors(lane: Path, tmp_path: Path, victim: str) -> None:
    actors = {}
    try:
        with guard.heavy_work("A"):
            for label in ("B", "C", "D"):
                actors[label] = _queued_actor(lane, tmp_path, label)
                _wait_file(tmp_path / (label + "-ready"), actors[label])
            actors[victim].kill()
            actors[victim].wait(timeout=3)
        for label, actor in actors.items():
            output = actor.communicate(timeout=5)
            assert actor.returncode == (-9 if label == victim else 0), output
    finally:
        for actor in actors.values():
            if actor.poll() is None:
                actor.kill()
            actor.communicate(timeout=5)
    assert (tmp_path / "order").read_text().splitlines() == [label for label in ("B", "C", "D") if label != victim]


def test_light_progresses_alongside_heavy_and_has_only_one_slot(lane: Path) -> None:
    entered, attempting, first_entered, release = (threading.Event() for _ in range(4))
    errors: list[BaseException] = []

    def other_light() -> None:
        try:
            attempting.set()
            with guard.heavy_work("second Ruff", work_class="light"):
                entered.set()
        except BaseException as exc:
            errors.append(exc)

    def light_owner() -> None:
        try:
            with guard.heavy_work("first Ruff", work_class="light"):
                first_entered.set()
                if not release.wait(5):
                    raise AssertionError("fixture release did not arrive")
        except BaseException as exc:
            errors.append(exc)

    owner, contender = threading.Thread(target=light_owner), threading.Thread(target=other_light)
    # Independent threads have no same-thread admission to reuse.
    with guard.heavy_work("suite"):
        try:
            owner.start()
            assert first_entered.wait(2), "light could not progress beside heavy"
            contender.start()
            assert attempting.wait(2)
            assert not entered.wait(0.2), "light capacity exceeded one"
        finally:
            release.set()
            owner.join(3)
            if contender.ident is not None:
                contender.join(3)
        assert not errors, errors
        assert entered.is_set() and not owner.is_alive() and not contender.is_alive()


def test_spare_heavy_slot_admits_second_owner_only_with_headroom(
    lane: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    headroom = threading.Event()
    monkeypatch.setattr(guard, "_spare_capacity", headroom.is_set)
    entered, third_attempting, third_entered, release = (threading.Event() for _ in range(4))
    lanes: list[str] = []

    def second() -> None:
        with guard.heavy_work("second suite") as work:
            lanes.append(work.lane)
            entered.set()
            assert release.wait(5)

    def third() -> None:
        third_attempting.set()
        with guard.heavy_work("third suite"):
            third_entered.set()

    with guard.heavy_work("first suite") as first:
        assert first.lane == "heavy"
        contender = threading.Thread(target=second)
        contender.start()
        assert not entered.wait(0.3), "spare slot opened without headroom"
        headroom.set()
        assert entered.wait(2), "spare slot did not open with headroom"
        assert lanes == ["heavy2"]
        late = threading.Thread(target=third)
        late.start()
        assert third_attempting.wait(2)
        assert not third_entered.wait(0.3), "heavy capacity exceeded two"
        release.set()
        contender.join(3)
        assert third_entered.wait(2)
        late.join(3)


def test_spare_slot_descendant_reenters_its_own_lane(lane: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "_spare_capacity", lambda: True)
    held, release = threading.Event(), threading.Event()

    def holder() -> None:
        with guard.heavy_work("slot zero"):
            held.set()
            assert release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(2)
        with guard.heavy_work("spare owner") as work:
            assert work.lane == "heavy2" and work.token.startswith("heavy2:")
            code = _bootstrap(lane) + (
                "\nwith guard.heavy_work('descendant suite') as nested:\n"
                "    assert nested.lane == 'heavy2', nested.lane\n"
                "with guard.heavy_work('descendant Ruff', work_class='light') as nested:\n"
                "    assert nested.lane == 'heavy2' and nested.work_class == 'heavy'\n"
            )
            result = work.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, result.stderr
    finally:
        release.set()
        thread.join(3)


def test_spare_capacity_requires_memory_headroom_and_low_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    files = {"/proc/meminfo": "MemTotal: 30000000 kB\nMemAvailable: 20000000 kB\n",
             "/proc/pressure/memory": "some avg10=0.50 avg60=0.10 avg300=0.00 total=1\n"}
    monkeypatch.setattr(guard.Path, "read_text", lambda self, *a, **k: files[str(self)])
    assert guard._spare_capacity()
    files["/proc/pressure/memory"] = "some avg10=12.00 avg60=3.00 avg300=1.00 total=1\n"
    assert not guard._spare_capacity()
    files["/proc/pressure/memory"] = "some avg10=0.00 avg60=0.00 avg300=0.00 total=1\n"
    files["/proc/meminfo"] = "MemAvailable: 4000000 kB\n"
    assert not guard._spare_capacity()
    del files["/proc/pressure/memory"]
    monkeypatch.setattr(guard.Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError()))
    assert not guard._spare_capacity()


def test_light_cannot_upgrade_to_heavy_in_thread_or_exec_descendant(lane: Path) -> None:
    with guard.heavy_work("Ruff", work_class="light") as work:
        with guard.heavy_work("nested Ruff", work_class="light") as nested:
            assert nested is work
        with pytest.raises(guard.HeavyWorkError, match="cannot be upgraded"), guard.heavy_work("suite"):
            pytest.fail("light upgraded")
        code = _bootstrap(lane) + """
try:
    with guard.heavy_work('descendant suite'):
        raise AssertionError('light upgraded in descendant')
except guard.HeavyWorkError as exc:
    assert 'cannot be upgraded' in str(exc)
with guard.heavy_work('descendant Ruff', work_class='light'):
    pass
"""
        result = work.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
    with guard.heavy_work("heavy owner") as heavy, guard.heavy_work("nested Ruff", work_class="light") as nested:
        assert nested is heavy and nested.work_class == "heavy"


def test_wait_status_is_bounded_and_verifies_holder(lane: Path, capsys: pytest.CaptureFixture[str]) -> None:
    entered = threading.Event()

    def waiter() -> None:
        with guard.heavy_work("B") as work:
            assert work.queue_seconds >= 0.1
            entered.set()

    with guard.heavy_work("suite", project="fixture-project"):
        thread = threading.Thread(target=waiter)
        thread.start()
        assert not entered.wait(0.15)
        output = capsys.readouterr().err
        assert "class=heavy" in output and "wait_age=" in output
        assert f"holder=suite project=fixture-project pid={os.getpid()} active_age=" in output
        assert len(output.splitlines()[0]) < 400
    thread.join(3)
    assert entered.is_set() and not thread.is_alive()


def test_deleted_working_directory_still_creates_admission_metadata(lane: Path, tmp_path: Path) -> None:
    cwd = tmp_path / "deleted-cwd"
    cwd.mkdir()
    code = _bootstrap(lane) + f"""
import os
os.chdir({str(cwd)!r})
os.rmdir({str(cwd)!r})
with guard.heavy_work('deleted cwd'):
    print('admitted', flush=True)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "admitted"
    assert json.loads((lane / "heavy-holder.json").read_text())["project"] == "unknown"


def test_old_protocol_owner_blocks_new_queue_without_replacing_capacity_files(lane: Path, tmp_path: Path) -> None:
    # Seed the exact pre-FIFO capacity protocol without new helper metadata.
    descriptors = [os.open(lane / name, os.O_CREAT | os.O_RDWR, 0o600)
                   for name in ("admission.lock", "activity.lock")]
    before = [os.fstat(fd).st_ino for fd in descriptors]
    # Incomplete holder diagnostics are advisory and must remain unknown.
    (lane / "heavy-holder.json").touch(mode=0o600)
    (lane / "heavy-holder.json").write_text("incomplete")
    actor = None
    try:
        fcntl.flock(descriptors[0], fcntl.LOCK_EX)
        fcntl.flock(descriptors[1], fcntl.LOCK_SH)
        os.write(descriptors[0], f"{os.getpid()}:1:{'a' * 32}".encode())
        actor = _queued_actor(lane, tmp_path, "B")
        _wait_file(tmp_path / "B-ready", actor)
        with pytest.raises(subprocess.TimeoutExpired):
            actor.communicate(timeout=0.2)
        # An old owner's admission may close while a descendant keeps activity.
        os.close(descriptors[0])
        descriptors[0] = -1
        with pytest.raises(subprocess.TimeoutExpired):
            actor.communicate(timeout=0.2)
    finally:
        for descriptor in descriptors:
            if descriptor >= 0:
                os.close(descriptor)
        if actor is not None:
            output = actor.communicate(timeout=5)
            assert actor.returncode == 0, output
            assert "holder=unknown" in output[1]
    assert [(lane / name).stat().st_ino for name in ("admission.lock", "activity.lock")] == before


@pytest.mark.parametrize("abandoned", ["start-mismatch", "zombie"])
def test_abandoned_identity_reclaims_waiter_even_if_another_process_retains_fd(lane: Path, abandoned: str) -> None:
    record = lane / f"wait-heavy-{'0' * 20}-{'b' * 32}.json"
    descriptor = os.open(record, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    zombie = None
    contender = None
    entered = threading.Event()
    errors: list[BaseException] = []
    try:
        if abandoned == "zombie":
            read_fd, write_fd = os.pipe()
            zombie = os.fork()
            if zombie == 0:
                os.close(write_fd)
                os.read(read_fd, 1)
                os._exit(0)
            os.close(read_fd)
            pid = zombie
            start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
            os.write(descriptor, json.dumps({"pid": pid, "start": start}).encode())
            os.write(write_fd, b"x")
            os.close(write_fd)
            deadline = time.monotonic() + 3
            while Path(f"/proc/{zombie}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z":
                assert time.monotonic() < deadline
                time.sleep(0.01)
        else:
            os.write(descriptor, json.dumps({"pid": os.getpid(), "start": "0"}).encode())
        def next_owner() -> None:
            try:
                with guard.heavy_work("next owner"):
                    entered.set()
            except BaseException as exc:
                errors.append(exc)

        contender = threading.Thread(target=next_owner)
        contender.start()
        assert entered.wait(2), "abandoned identity blocked admission"
        assert not record.exists()
        # Reclamation affects only metadata, even while this FD stays locked.
        assert os.fstat(descriptor).st_nlink == 0
        assert (lane / "admission.lock").exists() and (lane / "activity.lock").exists()
    finally:
        os.close(descriptor)
        if zombie is not None:
            assert os.waitpid(zombie, 0)[1] == 0
        if contender is not None:
            contender.join(3)
            assert not contender.is_alive() and not errors, errors


def test_nested_context_reenters_but_other_thread_queues(lane: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered = threading.Event()
    attempted = threading.Event()

    def other() -> None:
        attempted.set()
        with guard.heavy_work("independent thread"):
            entered.set()

    with guard.heavy_work("outer") as outer:
        # A real marker for this own generation cannot authorize another thread.
        monkeypatch.setenv("ST_HEAVY_LEASE", outer.token)
        with guard.heavy_work("nested") as nested:
            assert nested is outer
        thread = threading.Thread(target=other)
        thread.start()
        assert attempted.wait(1)
        assert not entered.wait(0.1)
    thread.join(2)
    assert entered.is_set() and not thread.is_alive()


def test_inherited_process_threads_serialize_sibling_contexts(lane: Path) -> None:
    code = _bootstrap(lane) + """
import threading
started, release, attempted, entered = (threading.Event() for _ in range(4))
def first():
    with guard.heavy_work('first inherited thread'):
        started.set()
        assert release.wait(5)
def second():
    attempted.set()
    with guard.heavy_work('second inherited thread'):
        entered.set()
one, two = threading.Thread(target=first), threading.Thread(target=second)
one.start()
assert started.wait(2)
two.start()
assert attempted.wait(2)
assert not entered.wait(0.15), 'inherited threads overlapped'
release.set()
one.join(2)
two.join(2)
assert entered.is_set() and not one.is_alive() and not two.is_alive()
"""
    with guard.heavy_work("outer owner") as work:
        result = work.run([sys.executable, "-c", code], text=True, capture_output=True, timeout=8)
    assert result.returncode == 0, result.stderr


def test_fork_children_take_next_depth_and_nested_descendant_reenters(lane: Path, tmp_path: Path) -> None:
    marker, release = tmp_path / "fork-running", tmp_path / "fork-release"
    completed = tmp_path / "nested-completed"
    grandchild = _bootstrap(lane) + (
        f"\nwith guard.heavy_work('nested fork descendant'): Path({str(completed)!r}).touch()\n"
    )
    children: list[int] = []

    def start_child(first: bool) -> int:
        pid = os.fork()
        if pid == 0:
            status = 1
            try:
                with guard.heavy_work("fork child") as work:
                    descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(descriptor)
                    if first:
                        result = work.run([sys.executable, "-c", grandchild], capture_output=True, timeout=5)
                        assert result.returncode == 0, result.stderr
                        while not release.exists():
                            time.sleep(0.01)
                    marker.unlink()
                    status = 0
            finally:
                os._exit(status)
        return pid

    with guard.heavy_work("fork owner"):
        try:
            children.append(start_child(True))
            deadline = time.monotonic() + 5
            while not completed.exists():
                assert time.monotonic() < deadline
                time.sleep(0.01)
            children.append(start_child(False))
            time.sleep(0.15)
        finally:
            release.touch()
            statuses = [os.waitpid(pid, 0)[1] for pid in children]
    assert statuses == [0, 0], "copied fork TLS bypassed sibling depth admission"


def test_reentrant_descendant_after_default_close_fds(lane: Path, tmp_path: Path) -> None:
    grandchild = _bootstrap(lane) + "\nwith guard.heavy_work('grandchild'): print('nested-complete')\n"
    child = (
        _bootstrap(lane)
        + "import subprocess; "
        + f"result = subprocess.run([sys.executable, '-c', {grandchild!r}], close_fds=True, "
        + "capture_output=True, text=True, check=True); print(result.stdout)"
    )
    before = os.getpriority(os.PRIO_PROCESS, 0)
    with guard.heavy_work("outer") as work:
        result = work.run([sys.executable, "-c", child], capture_output=True, text=True,
                          env={"HOME": str(tmp_path / "empty-home"), "PATH": os.defpath}, timeout=8)
    assert result.returncode == 0 and "nested-complete" in result.stdout
    assert os.getpriority(os.PRIO_PROCESS, 0) == before


@pytest.mark.parametrize("relative_path", [False, True])
def test_executable_discovery_uses_child_cwd(lane: Path, tmp_path: Path, relative_path: bool) -> None:
    child_cwd = tmp_path / "child"
    binary_dir = child_cwd / "scripts"
    binary_dir.mkdir(parents=True)
    executable = binary_dir / "validate-fixture"
    executable.write_text("#!/bin/sh\nprintf 'child-command\\n'\nexit 7\n")
    executable.chmod(0o755)
    command = "validate-fixture" if relative_path else "./scripts/validate-fixture"
    environment = {"PATH": "scripts" if relative_path else os.defpath}
    with guard.heavy_work("child-directory command") as work:
        result = work.run([command], cwd=child_cwd, env=environment, capture_output=True, text=True)
    assert result.returncode == 7 and result.stdout == "child-command\n"


def test_worker_settings_preserve_smaller_values_and_only_child_priority(lane: Path) -> None:
    before = os.getpriority(os.PRIO_PROCESS, 0)
    code = ("import os,json,subprocess; print(json.dumps([os.getpriority(os.PRIO_PROCESS,0),"
            "dict(os.environ),subprocess.check_output(['ionice','-p',str(os.getpid())],text=True)]))")
    parent_io = subprocess.check_output(["ionice", "-p", str(os.getpid())], text=True)
    with guard.heavy_work("fixture") as work:
        environment = work.environment({"GOMAXPROCS": "1", "VITEST_MAX_WORKERS": "99",
                                        "UV_CONCURRENT_BUILDS": "1", "PATH": os.defpath})
        assert environment["GOMAXPROCS"] == environment["UV_CONCURRENT_BUILDS"] == "1"
        assert environment["VITEST_MAX_WORKERS"] == "1"
        assert environment["CIRCLE_NODE_TOTAL"] == "3"
        result = work.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True)
    priority, received, child_io = json.loads(result.stdout)
    assert priority >= min(before + 10, 19)
    assert os.getpriority(os.PRIO_PROCESS, 0) == before
    assert received["RAYON_NUM_THREADS"] == received["UV_THREADPOOL_SIZE"] == "2"
    assert child_io.strip() == "idle"
    assert subprocess.check_output(["ionice", "-p", str(os.getpid())], text=True) == parent_io


@pytest.mark.parametrize("unsafe", ["symlink-directory", "public-directory", "symlink-lock", "public-lock"])
def test_private_storage_is_validated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    directory = tmp_path / "lane"
    if unsafe == "symlink-directory":
        directory.symlink_to(target, target_is_directory=True)
    else:
        directory.mkdir(mode=0o700)
    if unsafe == "public-directory":
        directory.chmod(0o755)
    if unsafe == "symlink-lock":
        destination = target / "other"
        destination.touch(mode=0o600)
        (directory / "admission.lock").symlink_to(destination)
    if unsafe == "public-lock":
        (directory / "admission.lock").touch(mode=0o644)
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", directory)
    with pytest.raises(guard.HeavyWorkError), guard.heavy_work("unsafe"):
        pytest.fail("unsafe admission bypassed")


def test_forged_or_stale_environment_cannot_grant_reentry(lane: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with guard.heavy_work("real") as work:
        admission = os.open(lane / "admission.lock", os.O_RDONLY)
        activity = os.open(lane / "activity.lock", os.O_RDONLY)
        try:
            assert guard._inherited(activity, admission, {"ST_HEAVY_LEASE": "1:1:" + "a" * 32 + ":8"}) is None
            token = work.token
        finally:
            os.close(admission)
            os.close(activity)
    # Even the exact old generation is stale once no live ancestor holds it.
    monkeypatch.setenv("ST_HEAVY_LEASE", token)
    with guard.heavy_work("new") as current:
        assert current.token != token


def test_depth_provenance_rejects_well_formed_copied_tokens(lane: Path) -> None:
    # A real descendant can validate the untouched six-field token. Alter only
    # depth or the EX descriptor; no record edits or syntax shortcuts.
    (lane / "depth-1.lock").touch(mode=0o600)
    code = _bootstrap(lane) + """
import os
admission=os.open(guard._LOCK_DIRECTORY/'admission.lock',os.O_RDONLY)
activity=os.open(guard._LOCK_DIRECTORY/'activity.lock',os.O_RDONLY)
parts=os.environ['ST_HEAVY_LEASE'].split(':')
assert guard._inherited(activity,admission,os.environ) is not None
wrong_depth=parts.copy()
wrong_depth[4]='1'
assert guard._inherited(activity,admission,{'ST_HEAVY_LEASE':':'.join(wrong_depth)}) is None
wrong_branch=parts.copy()
wrong_branch[5]=parts[3]
assert guard._inherited(activity,admission,{'ST_HEAVY_LEASE':':'.join(wrong_branch)}) is None
os.close(activity)
os.close(admission)
"""
    with guard.heavy_work("provenance") as work:
        result = work.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_wait_cancellation_does_not_unlock_other_owner(lane: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    interrupted = threading.Event()

    def stop_wait(_duration: float) -> None:
        raise KeyboardInterrupt

    def other() -> None:
        try:
            with guard.heavy_work("waiter"):
                pytest.fail("waiter bypassed")
        except KeyboardInterrupt:
            interrupted.set()

    with guard.heavy_work("owner"):
        monkeypatch.setattr(guard.time, "sleep", stop_wait)
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(2)
        assert interrupted.is_set()
        descriptor = os.open(lane / "admission.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


def test_owner_exit_keeps_child_activity_admitted_and_reaps_fixture(lane: Path, tmp_path: Path) -> None:
    started, release = tmp_path / "started", tmp_path / "release"
    child_code = (
        "from pathlib import Path; import time,os; "
        "os.close(int(os.environ['ST_HEAVY_LEASE'].split(':')[5])); "
        f"Path({str(started)!r}).touch();\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(0.01)\n"
    )
    owner_code = (
        _bootstrap(lane) + "import subprocess;\n"
        "with guard.heavy_work('owner') as work:\n"
        f" child=subprocess.Popen([sys.executable,'-c',{child_code!r}], "
        "env=work.environment(),pass_fds=work.pass_fds,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        " print(child.pid,flush=True)\n"
    )
    # Subreaping is confined to this fixture process, not the workstation/app.
    # It lets the real exited owner's child be explicitly reaped, not orphaned.
    driver_code = (
        "import ctypes,os,subprocess,sys; "
        "assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0; "
        f"owner=subprocess.Popen([sys.executable,'-c',{owner_code!r}],stdout=subprocess.PIPE,text=True); "
        "child=int(owner.stdout.readline()); assert owner.wait()==0; "
        "print('owner-exited',flush=True); _,status=os.waitpid(child,0); assert status==0"
    )
    driver = subprocess.Popen([sys.executable, "-c", driver_code], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env={"PATH": os.defpath})
    entered = threading.Event()

    def contender() -> None:
        with guard.heavy_work("next project"):
            entered.set()

    thread = None
    try:
        _wait_file(started, driver)
        assert driver.stdout is not None and driver.stdout.readline().strip() == "owner-exited"
        thread = threading.Thread(target=contender)
        thread.start()
        assert not entered.wait(0.15)
    finally:
        release.touch()
        output = driver.communicate(timeout=5)
        if thread is not None:
            thread.join(2)
    assert driver.returncode == 0, output
    assert entered.is_set() and thread is not None and not thread.is_alive()


def test_timeout_cancels_and_reaps_owned_descendant_in_another_session(lane: Path, tmp_path: Path) -> None:
    descendant = tmp_path / "descendant"
    child_code = (
        "import os,signal,subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True); "
        f"Path({str(descendant)!r}).write_text(str(child.pid)); "
        "signal.signal(signal.SIGTERM,lambda *args:(child.wait(),sys.exit(0))); time.sleep(60)"
    )
    with guard.heavy_work("cancellation fixture") as work, pytest.raises(subprocess.TimeoutExpired):
        work.run([sys.executable, "-c", child_code], capture_output=True, timeout=0.3)
    assert descendant.exists()
    pid = int(descendant.read_text())
    assert not Path(f"/proc/{pid}").exists(), "owned separate-session descendant was not reaped"
    with guard.heavy_work("subsequent job"):
        pass


def _wait_file(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            stdout, stderr = process.communicate(timeout=2)
            raise AssertionError(f"fixture did not start: {stdout} {stderr}")
        time.sleep(0.01)


@pytest.mark.parametrize("inherited", [False, True])
def test_two_canonical_checks_share_a_heavy_lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inherited: bool) -> None:
    """A second project's actual CLI must queue, not overlap the first tool."""
    binary = tmp_path / "bin"
    binary.mkdir()
    scanner = binary / "actionlint"
    marker = tmp_path / "running"
    release = tmp_path / "release"
    scanner.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        "assert os.environ['VITEST_MAX_WORKERS'] == '1'\n"
        "assert os.environ['GOMAXPROCS'] == '2'\n"
        "assert os.getpriority(os.PRIO_PROCESS, 0) >= 10\n"
        "from pathlib import Path\n"
        f"marker = Path({str(marker)!r})\n"
        "try: fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)\n"
        "except FileExistsError: sys.exit(42)\n"
        "os.close(fd)\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(0.01)\n"
        "marker.unlink()\n"
    )
    scanner.chmod(0o700)
    lane = tmp_path / "lane"
    lane.mkdir(mode=0o700)
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", lane)
    bootstrap = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(BACKEND)!r}); "
        "import importlib.util; "
        "spec = importlib.util.find_spec('app.utils.heavy_work'); "
        "guard = __import__('app.utils.heavy_work', fromlist=['_LOCK_DIRECTORY']) if spec else None; "
        f"setattr(guard, '_LOCK_DIRECTORY', Path({str(lane)!r})) if guard else None; "
        "from cli.main import app; app()"
    )
    environment = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{binary}:{os.defpath}",
        "DATABASE_URL": "postgresql://fixture:unused@127.0.0.1:1/import_only",
        "ST_API_BASE": "http://127.0.0.1:1/api",
    }
    projects = [tmp_path / "one", tmp_path / "two"]
    for project in projects:
        project.mkdir()
    command = [sys.executable, "-P", "-c", bootstrap, "check", "actionlint", "--", "fixture.yml"]
    with guard.heavy_work("outer pytest actor") if inherited else nullcontext(None) as work:
        if work is not None:
            environment = work.environment(environment)
        pass_fds = work.pass_fds if work is not None else ()
        first = subprocess.Popen(command, cwd=projects[0], env=environment, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=pass_fds)
        second = None
        try:
            _wait_file(marker, first)
            second = subprocess.Popen(command, cwd=projects[1], env=environment, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=pass_fds)
            # Both independent and genuinely inherited CLI sibling actors must
            # queue. Keep the marker/token intact for the inherited regression.
            try:
                second.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            assert second.poll() is None, "second project overlapped the active heavy tool"
        finally:
            release.touch()
            first_output = first.communicate(timeout=10)
            second_output = second.communicate(timeout=10) if second is not None else None
    assert first.returncode == 0, first_output
    assert second is not None and second.returncode == 0, second_output


def test_lane_activity_reports_holder_without_queueing_or_admitting(lane: Path) -> None:
    assert guard.lane_activity("heavy") == []
    with guard.heavy_work("acceptance", project="neri"):
        occupied = guard.lane_activity("heavy")
        assert [(row["lane"], row["label"], row["project"]) for row in occupied] == [("heavy", "acceptance", "neri")]
        assert guard.lane_activity("light") == []
        assert not list(lane.glob("wait-*.json"))
    assert guard.lane_activity("heavy") == []
