#!/usr/bin/env python3
"""Measure what a running Silvasonic station costs its host.

Samples every running container and the host for a given duration, prints a
summary and writes every sample to a JSON file. It runs on the station itself
with the system Python: standard library only, no virtual environment.

Usage:
    python3 scripts/measure_station.py --duration 1800 --label recording-only

What it reports:
    * per container: private memory (cgroup ``anon``), page cache (``file``),
      PSS where ``/proc`` allows reading it, CPU as a share of one core, and
      megabytes written;
    * host: load, available memory, CPU, SoC temperature and throttling flags;
    * the storage device under the workspace: megabytes written, and the count
      and duration of write and flush requests (a database's fsync calls reach
      an SD card as flush requests);
    * the Recorder's segments written during the run: count, gaps and the
      volume extrapolated to a day.
"""

import argparse
import itertools
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

CGROUP_ROOT = Path("/sys/fs/cgroup")
SECTOR_BYTES = 512
MIB = 1024 * 1024
GB = 1000**3
# A segment's start may differ from its nominal start by this many seconds
# before it counts as irregular.
SEGMENT_TOLERANCE_S = 1.5

# {start}_{duration}s_{run_id}_{sequence}[_unsynced].wav, written by the Recorder.
SEGMENT_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)_(?P<duration>\d+)s_"
    r"(?P<run>.+)_(?P<seq>\d{8})(?:_unsynced)?\.wav$"
)


# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------


def run(cmd: list[str]) -> str:
    """Return a command's stdout, or an empty string if it cannot run."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def read(path: Path) -> str:
    """Return a file's text, or an empty string if it cannot be read."""
    try:
        return path.read_text()
    except OSError:
        return ""


def parse_key_values(text: str) -> dict[str, int]:
    """Parse ``key value`` lines as cgroup and procfs files print them."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.replace(":", " ").split()
        if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
            values[parts[0]] = int(parts[1])
    return values


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------


@dataclass
class Container:
    """A running container and the cgroup that holds its processes."""

    name: str
    cgroup: Path


@dataclass
class ContainerSample:
    """One reading of one container."""

    anon_mib: float
    file_mib: float
    pss_mib: float | None
    cpu_usec: int
    written_bytes: int | None


def cgroup_of(pid: int) -> Path | None:
    """Return the cgroup directory of a container's main process."""
    for line in read(Path(f"/proc/{pid}/cgroup")).splitlines():
        if line.startswith("0::"):
            path = CGROUP_ROOT / line[3:].lstrip("/")
            # Podman may place the payload in a "container" child of the scope.
            if path.name == "container":
                path = path.parent
            return path if path.is_dir() else None
    return None


def find_containers(pattern: str) -> list[Container]:
    """List the running containers whose name matches the pattern."""
    raw = run(["podman", "ps", "--format", "json"])
    try:
        entries: Any = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        entries = []
    containers: list[Container] = []
    for entry in entries if isinstance(entries, list) else []:
        names = entry.get("Names") or []
        name = str(names[0]) if names else str(entry.get("Id", ""))[:12]
        if not re.search(pattern, name):
            continue
        cgroup = cgroup_of(int(entry.get("Pid") or 0))
        if cgroup is not None:
            containers.append(Container(name=name, cgroup=cgroup))
    return containers


def cgroup_pids(cgroup: Path) -> set[int]:
    """Return every process in a cgroup and its children."""
    pids: set[int] = set()
    for procs in cgroup.glob("**/cgroup.procs"):
        pids.update(int(p) for p in read(procs).split() if p.isdigit())
    return pids


def sample_container(container: Container) -> ContainerSample:
    """Read memory, CPU and write counters of one container."""
    memory = parse_key_values(read(container.cgroup / "memory.stat"))
    cpu = parse_key_values(read(container.cgroup / "cpu.stat"))
    pids = cgroup_pids(container.cgroup)

    # PSS needs /proc/<pid>/smaps_rollup, which only a process of the same
    # user may read. A container that switches user (a database) hides it.
    pss_kb = 0
    pss_complete = bool(pids)
    for pid in pids:
        rollup = parse_key_values(read(Path(f"/proc/{pid}/smaps_rollup")))
        if "Pss" in rollup:
            pss_kb += rollup["Pss"]
        else:
            pss_complete = False

    written: int | None = None
    io_stat = read(container.cgroup / "io.stat")
    if io_stat.strip():
        written = sum(int(m) for m in re.findall(r"wbytes=(\d+)", io_stat))
    else:
        # The io controller is not delegated to this user: fall back to the
        # per-process counters, which miss processes that already exited.
        per_process = [parse_key_values(read(Path(f"/proc/{pid}/io"))) for pid in pids]
        if per_process and all("write_bytes" in p for p in per_process):
            written = sum(p["write_bytes"] for p in per_process)

    return ContainerSample(
        anon_mib=memory.get("anon", 0) / MIB,
        file_mib=memory.get("file", 0) / MIB,
        pss_mib=pss_kb / 1024 if pss_complete else None,
        cpu_usec=cpu.get("usage_usec", 0),
        written_bytes=written,
    )


# ---------------------------------------------------------------------------
# Host and storage
# ---------------------------------------------------------------------------


@dataclass
class HostSample:
    """One reading of the host."""

    load1: float
    mem_available_mib: float
    cpu_busy: int
    cpu_total: int
    temp_c: float | None
    throttled: str | None


@dataclass
class DiskSample:
    """Cumulative counters of the storage device, as ``/sys/block/*/stat`` keeps them."""

    writes: int
    written_bytes: int
    write_ms: int
    flushes: int
    flush_ms: int


def sample_host() -> HostSample:
    """Read load, memory, CPU time, temperature and throttling of the host."""
    load = read(Path("/proc/loadavg")).split()
    meminfo = parse_key_values(read(Path("/proc/meminfo")))
    cpu_line = read(Path("/proc/stat")).splitlines()[:1]
    jiffies = [int(v) for v in cpu_line[0].split()[1:9]] if cpu_line else []
    idle = jiffies[3] + jiffies[4] if len(jiffies) >= 5 else 0
    temp_raw = read(Path("/sys/class/thermal/thermal_zone0/temp")).strip()
    throttled = run(["vcgencmd", "get_throttled"]).strip() if shutil.which("vcgencmd") else ""
    return HostSample(
        load1=float(load[0]) if load else 0.0,
        mem_available_mib=meminfo.get("MemAvailable", 0) / 1024,
        cpu_busy=sum(jiffies) - idle,
        cpu_total=sum(jiffies),
        temp_c=int(temp_raw) / 1000 if temp_raw.lstrip("-").isdigit() else None,
        throttled=throttled.removeprefix("throttled=") or None,
    )


def find_disk(path: Path) -> Path | None:
    """Return the sysfs directory of the disk that holds a path."""
    try:
        device = path.stat().st_dev
    except OSError:
        return None
    node = Path(f"/sys/dev/block/{os.major(device)}:{os.minor(device)}")
    if not node.exists():
        # Some filesystems report a device number of their own (btrfs).
        source = run(["findmnt", "-no", "SOURCE", "-T", str(path)]).strip().split("[")[0]
        if not source:
            return None
        node = Path("/sys/class/block") / Path(source).resolve().name
        if not node.exists():
            return None
    node = node.resolve()
    if (node / "partition").exists():
        node = node.parent
    return node if (node / "stat").exists() else None


def parse_disk_stat(text: str) -> DiskSample | None:
    """Parse one line of ``/sys/block/<disk>/stat``."""
    fields = [int(v) for v in text.split() if v.isdigit()]
    if len(fields) < 11:
        return None
    return DiskSample(
        writes=fields[4],
        written_bytes=fields[6] * SECTOR_BYTES,
        write_ms=fields[7],
        # Flush counters exist since Linux 5.5.
        flushes=fields[15] if len(fields) > 16 else 0,
        flush_ms=fields[16] if len(fields) > 16 else 0,
    )


# ---------------------------------------------------------------------------
# Recorder segments
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    """A segment file of the Recorder."""

    start: float
    duration_s: int
    run: str
    seq: int
    size: int


@dataclass
class StreamReport:
    """What one stream of one microphone wrote during the run."""

    segments: int = 0
    missing: int = 0
    restarts: int = 0
    irregular: int = 0
    max_gap_s: float = 0.0
    bytes_written: int = 0
    gb_per_day: float = 0.0


def parse_segment(name: str, size: int) -> Segment | None:
    """Parse a segment's file name; ``None`` for any other file."""
    match = SEGMENT_RE.match(name)
    if match is None:
        return None
    start = datetime.strptime(match["stamp"], "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)
    return Segment(
        start=start.timestamp(),
        duration_s=int(match["duration"]),
        run=match["run"],
        seq=int(match["seq"]),
        size=size,
    )


def analyse_stream(segments: list[Segment], elapsed_s: float) -> StreamReport:
    """Count gaps between consecutive segments of one stream."""
    report = StreamReport(segments=len(segments))
    ordered = sorted(segments, key=lambda s: (s.start, s.seq))
    for previous, current in itertools.pairwise(ordered):
        gap = current.start - previous.start - previous.duration_s
        report.max_gap_s = max(report.max_gap_s, gap)
        if current.run != previous.run:
            report.restarts += 1
        elif current.seq != previous.seq + 1:
            report.missing += current.seq - previous.seq - 1
        elif abs(gap) > SEGMENT_TOLERANCE_S:
            report.irregular += 1
    report.bytes_written = sum(s.size for s in ordered)
    if elapsed_s > 0:
        report.gb_per_day = report.bytes_written / elapsed_s * 86400 / GB
    return report


def scan_streams(workspace: Path, since: float, elapsed_s: float) -> dict[str, StreamReport]:
    """Report every Recorder stream that wrote a segment since the given time."""
    streams: dict[str, list[Segment]] = {}
    for path in workspace.glob("recorder/*/data/*/*.wav"):
        try:
            stat = path.stat()
        except OSError:
            continue
        segment = parse_segment(path.name, stat.st_size)
        # A segment belongs to the run if it started after the run did.
        if segment is not None and segment.start >= since:
            key = f"{path.parents[2].name}/{path.parent.name}"
            streams.setdefault(key, []).append(segment)
    return {key: analyse_stream(found, elapsed_s) for key, found in sorted(streams.items())}


# ---------------------------------------------------------------------------
# Run and summary
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """Everything read at one point in time."""

    t: float
    host: HostSample
    disk: DiskSample | None
    containers: dict[str, ContainerSample] = field(default_factory=dict)


def take_sample(pattern: str, disk: Path | None) -> Sample:
    """Read host, storage and every matching container once."""
    return Sample(
        t=time.time(),
        host=sample_host(),
        disk=parse_disk_stat(read(disk / "stat")) if disk is not None else None,
        containers={c.name: sample_container(c) for c in find_containers(pattern)},
    )


def mean(values: list[float]) -> float:
    """Arithmetic mean; zero for an empty list."""
    return sum(values) / len(values) if values else 0.0


def summarise_containers(samples: list[Sample]) -> dict[str, dict[str, float | None]]:
    """Reduce each container's samples to mean and peak values."""
    summary: dict[str, dict[str, float | None]] = {}
    names = sorted({name for s in samples for name in s.containers})
    for name in names:
        present = [(s.t, s.containers[name]) for s in samples if name in s.containers]
        readings = [c for _, c in present]
        cpu: list[float] = []
        for (t0, c0), (t1, c1) in itertools.pairwise(present):
            # A lower counter means the container was replaced in between.
            if t1 > t0 and c1.cpu_usec >= c0.cpu_usec:
                cpu.append((c1.cpu_usec - c0.cpu_usec) / (t1 - t0) / 10_000)
        pss = [c.pss_mib for c in readings if c.pss_mib is not None]
        first, last = readings[0].written_bytes, readings[-1].written_bytes
        written = (last - first) / MIB if first is not None and last is not None else None
        summary[name] = {
            "anon_mib_mean": mean([c.anon_mib for c in readings]),
            "anon_mib_max": max(c.anon_mib for c in readings),
            "file_mib_mean": mean([c.file_mib for c in readings]),
            "pss_mib_mean": mean(pss) if len(pss) == len(readings) else None,
            "cpu_percent_mean": mean(cpu),
            "cpu_percent_max": max(cpu, default=0.0),
            "written_mib": written if written is None or written >= 0 else None,
            "samples": float(len(readings)),
        }
    return summary


def summarise_host(samples: list[Sample]) -> dict[str, Any]:
    """Reduce the host and storage samples of a run."""
    first, last = samples[0], samples[-1]
    elapsed = max(last.t - first.t, 1e-9)
    total = last.host.cpu_total - first.host.cpu_total
    temps = [s.host.temp_c for s in samples if s.host.temp_c is not None]
    summary: dict[str, Any] = {
        "elapsed_s": round(elapsed, 1),
        "cpu_percent_of_all_cores": (
            (last.host.cpu_busy - first.host.cpu_busy) / total * 100 if total > 0 else 0.0
        ),
        "load1_mean": mean([s.host.load1 for s in samples]),
        "mem_available_mib_min": min(s.host.mem_available_mib for s in samples),
        "temp_c_max": max(temps, default=None),
        "throttled_values": sorted({s.host.throttled for s in samples if s.host.throttled}),
    }
    if first.disk is not None and last.disk is not None:
        writes = last.disk.writes - first.disk.writes
        flushes = last.disk.flushes - first.disk.flushes
        written = last.disk.written_bytes - first.disk.written_bytes
        summary["disk"] = {
            "written_mib": written / MIB,
            "written_gb_per_day": written / elapsed * 86400 / GB,
            "writes_per_s": writes / elapsed,
            "ms_per_write": (last.disk.write_ms - first.disk.write_ms) / writes if writes else 0.0,
            "flushes_per_s": flushes / elapsed,
            "ms_per_flush": (
                (last.disk.flush_ms - first.disk.flush_ms) / flushes if flushes else 0.0
            ),
        }
    return summary


def station_info(workspace: Path | None, disk: Path | None) -> dict[str, Any]:
    """Describe the machine the measurement ran on."""
    meminfo = parse_key_values(read(Path("/proc/meminfo")))
    return {
        "model": read(Path("/proc/device-tree/model")).strip("\x00\n") or platform.machine(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "cpus": os.cpu_count(),
        "mem_total_mib": round(meminfo.get("MemTotal", 0) / 1024),
        "podman": run(["podman", "--version"]).strip(),
        "workspace": str(workspace) if workspace else None,
        "disk": disk.name if disk else None,
    }


def fmt(value: float | None, digits: int = 0) -> str:
    """Format a number for the table; a dash when it is unknown."""
    return "-" if value is None else f"{value:.{digits}f}"


def print_summary(result: dict[str, Any]) -> None:
    """Print the summary table of a finished run."""
    info, host = result["station"], result["host"]
    print(f"\nStation: {info['model']} · {info['mem_total_mib']} MiB RAM · {info['kernel']}")
    print(f"Run: {result['label']} · {host['elapsed_s']} s · {result['sample_count']} samples\n")

    rows: list[list[str]] = [
        ["container", "anon MiB", "peak", "cache MiB", "PSS MiB", "CPU %", "peak", "MiB out"]
    ]
    for name, c in result["containers"].items():
        rows.append(
            [
                str(name),
                fmt(c["anon_mib_mean"]),
                fmt(c["anon_mib_max"]),
                fmt(c["file_mib_mean"]),
                fmt(c["pss_mib_mean"]),
                fmt(c["cpu_percent_mean"], 1),
                fmt(c["cpu_percent_max"], 1),
                fmt(c["written_mib"]),
            ]
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        numbers = [value.rjust(width) for value, width in zip(row[1:], widths[1:], strict=True)]
        print("  ".join([row[0].ljust(widths[0]), *numbers]))
    total = sum(c["anon_mib_mean"] or 0.0 for c in result["containers"].values())
    print(f"\nPrivate memory of all containers: {total:.0f} MiB (CPU % is of one core)")

    print(
        f"Host: {host['cpu_percent_of_all_cores']:.1f} % of all cores"
        f" · load {host['load1_mean']:.2f}"
        f" · least available memory {host['mem_available_mib_min']:.0f} MiB"
        f" · peak {fmt(host['temp_c_max'], 1)} °C"
        f" · throttled {', '.join(host['throttled_values']) or '-'}"
    )
    disk = host.get("disk")
    if disk:
        print(
            f"Storage ({info['disk']}): {disk['written_mib']:.0f} MiB written"
            f" = {disk['written_gb_per_day']:.1f} GB/day"
            f" · {disk['writes_per_s']:.1f} writes/s at {disk['ms_per_write']:.1f} ms"
            f" · {disk['flushes_per_s']:.2f} flushes/s at {disk['ms_per_flush']:.1f} ms"
        )
    for key, s in result["streams"].items():
        print(
            f"Stream {key}: {s['segments']} segments · {s['missing']} missing"
            f" · {s['restarts']} restarts · {s['irregular']} irregular"
            f" · largest gap {s['max_gap_s']:.1f} s · {s['gb_per_day']:.1f} GB/day"
        )


def workspace_from_env_file(env_file: Path) -> Path | None:
    """Read ``SILVASONIC_WORKSPACE_PATH`` from a ``.env`` file."""
    for line in read(env_file).splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "SILVASONIC_WORKSPACE_PATH" and value.strip():
            return Path(value.strip().strip("\"'")).expanduser()
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--duration", type=float, default=1800.0, help="seconds to measure")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between samples")
    parser.add_argument("--label", default="run", help="name of this run, used in the file name")
    parser.add_argument(
        "--containers", default="^silvasonic", help="regular expression on container names"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="workspace root (default: SILVASONIC_WORKSPACE_PATH from ./.env)",
    )
    parser.add_argument("--out", type=Path, default=None, help="JSON file to write")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Measure for the requested duration, then print and save the result."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    workspace: Path | None = args.workspace or workspace_from_env_file(Path(".env"))
    disk = find_disk(workspace if workspace and workspace.exists() else Path.cwd())

    stop = False

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    started = time.time()
    deadline = time.monotonic() + args.duration
    samples: list[Sample] = []
    print(f"Measuring for {args.duration:.0f} s, one sample every {args.interval:.0f} s ...")
    while True:
        tick = time.monotonic()
        samples.append(take_sample(args.containers, disk))
        if stop or tick >= deadline:
            break
        # Sleep in short steps so a signal ends the run promptly.
        wake = min(tick + args.interval, deadline)
        while not stop and time.monotonic() < wake:
            time.sleep(min(0.5, max(wake - time.monotonic(), 0.0)))

    if not any(s.containers for s in samples):
        print(f"No running container matches {args.containers!r}.", file=sys.stderr)
    elapsed = samples[-1].t - samples[0].t
    streams = scan_streams(workspace, started, elapsed) if workspace else {}
    result: dict[str, Any] = {
        "label": args.label,
        "started_at": datetime.fromtimestamp(started, UTC).isoformat(timespec="seconds"),
        "station": station_info(workspace, disk),
        "sample_count": len(samples),
        "host": summarise_host(samples),
        "containers": summarise_containers(samples),
        "streams": {key: asdict(report) for key, report in streams.items()},
        "samples": [asdict(s) for s in samples],
    }
    print_summary(result)

    stamp = datetime.fromtimestamp(started, UTC).strftime("%Y%m%dT%H%M%SZ")
    out: Path = args.out or Path(f"measure_{args.label}_{stamp}.json")
    out.write_text(json.dumps(result, indent=1))
    print(f"\nAll samples: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
