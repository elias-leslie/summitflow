"""Finite reads of optional Linux sensors and power providers."""
from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any

from .common import availability, base, bounded_text, error, item, limits, pack
from .logs import _run

HWMON = Path("/sys/class/hwmon")
CPUFREQ = Path("/sys/devices/system/cpu/cpufreq")
POWER_SUPPLY = Path("/sys/class/power_supply")
MAX_DEVICES = 32
MAX_FILES = 32
GPU_FIELDS = (("temperature.gpu", "celsius"), ("utilization.gpu", "%"),
              ("memory.used", "MiB"), ("memory.total", "MiB"),
              ("power.draw", "watts"))


def _read(path: Path) -> str:
    with path.open("r", encoding="utf-8") as stream:
        return stream.read(256).strip()


def _numeric(path: Path) -> int | None:
    try:
        return int(_read(path))
    except ValueError:
        return None


def _listed(root: Path, pattern: str) -> tuple[list[Path], int]:
    devices = sorted(root.glob(pattern), key=lambda p: p.name)
    return devices[:MAX_DEVICES], len(devices)


def query_sensors(*, limit: int = 10, max_bytes: int = 4096) -> dict[str, Any]:
    """Read hwmon, CPU frequency and power supply metrics when exposed by sysfs."""
    limits(limit, max_bytes)
    payload = base("sensors")
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    providers: dict[str, str] = {}
    scan: dict[str, dict[str, int]] = {}
    capped = False
    if shutil.which("nvidia-smi"):
        command = ["nvidia-smi", "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                   "--format=csv,noheader,nounits"]
        try:
            output, _stderr, returncode, clipped = _run(command)
            if returncode or clipped:
                providers["nvidia_gpu"] = "error"
                errors.append(error("source_truncated" if clipped else "error", "nvidia-smi"))
                capped |= clipped
            else:
                rows = list(csv.reader(output.decode("utf-8", "replace").splitlines()))
                scan["nvidia_gpu"] = {"devices_seen": len(rows), "devices_scanned": min(len(rows), MAX_DEVICES)}
                if len(rows) > MAX_DEVICES:
                    capped = True
                    errors.append(error("source_truncated", "nvidia-smi", "GPU row cap reached"))
                providers["nvidia_gpu"] = "ok" if rows else "unsupported"
                for row in rows[:MAX_DEVICES]:
                    if len(row) != 7:
                        errors.append(error("error", "nvidia-smi", "malformed GPU row"))
                        continue
                    index, name = row[0].strip(), bounded_text(row[1].strip(), 64)
                    for (metric, unit), raw in zip(GPU_FIELDS, row[2:], strict=True):
                        try:
                            reading = float(raw.strip())
                        except ValueError:
                            reading = None
                        entries.append(item("nvidia-smi", name, "ok" if reading is not None else "unsupported",
                                            {"gpu_index": index, "metric": metric, "reading": reading}, unit=unit))
        except (OSError, TimeoutError) as exc:
            providers["nvidia_gpu"] = availability(exc)
            errors.append(error(availability(exc), "nvidia-smi"))
    else:
        providers["nvidia_gpu"] = "unsupported"
    sources = (("hwmon", HWMON), ("cpufreq", CPUFREQ), ("power_supply", POWER_SUPPLY))
    for provider, root in sources:
        try:
            devices, device_count = _listed(root, "hwmon[0-9]*" if provider == "hwmon" else
                                            "policy[0-9]*" if provider == "cpufreq" else "*")
            scan[provider] = {"devices_seen": device_count, "devices_scanned": len(devices)}
            if device_count > len(devices):
                capped = True
                errors.append(error("source_truncated", str(root), "device scan cap reached"))
            if not devices:
                providers[provider] = "unsupported"
                continue
            providers[provider] = "ok"
            for device in devices:
                if provider == "hwmon":
                    try:
                        chip = bounded_text(_read(device / "name"), 64)
                    except OSError:
                        chip = device.name
                    files = sorted(device.iterdir(), key=lambda p: p.name)
                    scan[provider]["files_seen"] = scan[provider].get("files_seen", 0) + len(files)
                    scan[provider]["files_scanned"] = scan[provider].get("files_scanned", 0) + min(len(files), MAX_FILES)
                    if len(files) > MAX_FILES:
                        capped = True
                        errors.append(error("source_truncated", str(HWMON), "sensor file scan cap reached"))
                    for path in files[:MAX_FILES]:
                        if not path.is_file() or not path.name.endswith("_input"):
                            continue
                        stem = path.name.removesuffix("_input")
                        unit, scale = (("celsius", 1000) if stem.startswith("temp") else
                                       ("millivolts", 1) if stem.startswith("in") else
                                       ("rpm", 1) if stem.startswith("fan") else
                                       ("microwatts", 1) if stem.startswith("power") else (None, 1))
                        if unit is None:
                            continue
                        try:
                            value = _numeric(path)
                            label_path = device / f"{stem}_label"
                            label = bounded_text(_read(label_path), 64) if label_path.exists() else stem
                            entries.append(item(str(HWMON), chip, "ok" if value is not None else "error",
                                                {"device": device.name, "sensor": stem, "label": label,
                                                 "reading": value / scale if value is not None else None}, unit=unit))
                        except OSError as exc:
                            errors.append(error(availability(exc), str(HWMON)))
                elif provider == "cpufreq":
                    for filename in ("scaling_cur_freq", "cpuinfo_min_freq", "cpuinfo_max_freq"):
                        try:
                            value = _numeric(device / filename)
                            if value is not None:
                                entries.append(item(str(CPUFREQ), device.name, "ok",
                                                    {"metric": filename, "reading": value}, unit="kHz"))
                        except OSError as exc:
                            errors.append(error(availability(exc), str(CPUFREQ)))
                else:
                    for filename, unit in (("capacity", "%"), ("energy_now", "microwatt_hours"),
                                           ("power_now", "microwatts"), ("voltage_now", "microvolts")):
                        path = device / filename
                        if not path.exists():
                            continue
                        try:
                            value = _numeric(path)
                            if value is not None:
                                entries.append(item(str(POWER_SUPPLY), device.name, "ok",
                                                    {"metric": filename, "reading": value}, unit=unit))
                        except OSError as exc:
                            errors.append(error(availability(exc), str(POWER_SUPPLY)))
        except OSError as exc:
            providers[provider] = availability(exc)
            errors.append(error(availability(exc), str(root)))
    payload["coverage"] = {"availability": "ok" if entries else ("permission_denied" if
                           any(x == "permission_denied" for x in providers.values()) else "unsupported"),
                           "providers": providers, "scan": scan, "metrics_seen": len(entries),
                           "source_capped": capped}
    payload["errors"] = errors[:8]
    return pack(payload, entries, limit=limit, max_bytes=max_bytes, more=capped)
