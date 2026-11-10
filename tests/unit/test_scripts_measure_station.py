"""Unit tests for scripts/measure_station.py — the parts that need no station."""

from __future__ import annotations

from pathlib import Path

import pytest
from measure_station import (
    ContainerSample,
    HostSample,
    Sample,
    Segment,
    analyse_stream,
    parse_disk_stat,
    parse_key_values,
    parse_segment,
    scan_streams,
    summarise_containers,
    workspace_from_env_file,
)

RUN_START = 1_800_000_000.0  # 2027-01-15T08:00:00Z


def _segment(
    index: int, *, run: str = "run1", seq: int | None = None, shift: float = 0.0
) -> Segment:
    return Segment(
        start=RUN_START + index * 10 + shift,
        duration_s=10,
        run=run,
        seq=index if seq is None else seq,
        size=1_000_000,
    )


def _container(cpu_usec: int, anon_mib: float = 60.0, written: int | None = 0) -> ContainerSample:
    return ContainerSample(
        anon_mib=anon_mib, file_mib=1.0, pss_mib=None, cpu_usec=cpu_usec, written_bytes=written
    )


def _sample(t: float, **containers: ContainerSample) -> Sample:
    host = HostSample(
        load1=0.0, mem_available_mib=1000.0, cpu_busy=0, cpu_total=0, temp_c=None, throttled=None
    )
    return Sample(t=t, host=host, disk=None, containers=dict(containers))


@pytest.mark.unit
class TestReaders:
    """The kernel's text formats are parsed as the kernel writes them."""

    def test_key_values_with_and_without_colon(self) -> None:
        """memory.stat has no colon, meminfo and smaps_rollup have one and a unit."""
        assert parse_key_values("anon 1024\nfile 2048\n") == {"anon": 1024, "file": 2048}
        assert parse_key_values("Pss:          512 kB\nRss: 900 kB") == {"Pss": 512, "Rss": 900}

    def test_disk_stat_with_flush_counters(self) -> None:
        """Sectors become bytes; fields 16 and 17 are the flush counters."""
        stat = parse_disk_stat("1 0 8 5  40 3 2048 300  0 400 305  0 0 0 0  7 90")
        assert stat is not None
        assert (stat.writes, stat.written_bytes, stat.write_ms) == (40, 2048 * 512, 300)
        assert (stat.flushes, stat.flush_ms) == (7, 90)

    def test_disk_stat_of_an_old_kernel_has_no_flush_counters(self) -> None:
        """Before Linux 5.5 the line ends after the discard fields."""
        stat = parse_disk_stat("1 0 8 5  40 3 2048 300  0 400 305  0 0 0 0")
        assert stat is not None
        assert (stat.flushes, stat.flush_ms) == (0, 0)

    def test_workspace_path_from_env_file(self, tmp_path: Path) -> None:
        """The workspace is read from the station's .env."""
        env = tmp_path / ".env"
        env.write_text("FOO=1\nSILVASONIC_WORKSPACE_PATH=/srv/silvasonic/\n")
        assert workspace_from_env_file(env) == Path("/srv/silvasonic")
        assert workspace_from_env_file(tmp_path / "missing") is None


@pytest.mark.unit
class TestSegments:
    """Gaps in a stream are found from the Recorder's own file names."""

    def test_file_name_of_the_recorder(self) -> None:
        """Start, duration, run and sequence come from the name."""
        segment = parse_segment("2027-01-15T08-00-00Z_10s_a1b2_c3_00000042.wav", 960_044)
        assert segment == Segment(
            start=RUN_START, duration_s=10, run="a1b2_c3", seq=42, size=960_044
        )

    def test_unsynced_marker_and_foreign_files(self) -> None:
        """A segment named with an unsynchronised clock still counts; other files do not."""
        assert parse_segment("2027-01-15T08-00-00Z_10s_r_00000001_unsynced.wav", 1) is not None
        assert parse_segment("notes.wav", 1) is None

    def test_continuous_stream_has_no_gap(self) -> None:
        """Consecutive segments ten seconds apart are regular."""
        report = analyse_stream([_segment(i) for i in range(6)], elapsed_s=60)
        assert (report.segments, report.missing, report.restarts, report.irregular) == (6, 0, 0, 0)
        assert report.max_gap_s == 0
        assert report.gb_per_day == pytest.approx(6_000_000 / 60 * 86400 / 1e9)

    def test_missing_segment_restart_and_late_segment(self) -> None:
        """A skipped sequence number, a new run and a late start are told apart."""
        segments = [
            _segment(0),
            _segment(2),  # sequence 1 is missing
            _segment(4, run="run2", seq=0),  # the Recorder restarted
            _segment(5, run="run2", seq=1, shift=3.0),  # three seconds late
        ]
        report = analyse_stream(segments, elapsed_s=60)
        assert (report.missing, report.restarts, report.irregular) == (1, 1, 1)
        assert report.max_gap_s == 10

    def test_only_segments_of_the_run_are_counted(self, tmp_path: Path) -> None:
        """Segments that started before the measurement belong to no report."""
        stream = tmp_path / "recorder" / "ultramic-034f" / "data" / "raw"
        stream.mkdir(parents=True)
        (stream / "2027-01-15T07-59-50Z_10s_r_00000001.wav").write_bytes(b"x" * 10)
        (stream / "2027-01-15T08-00-00Z_10s_r_00000002.wav").write_bytes(b"x" * 10)
        (stream / "2027-01-15T08-00-10Z_10s_r_00000003.wav").write_bytes(b"x" * 10)

        reports = scan_streams(tmp_path, since=RUN_START, elapsed_s=20)

        assert list(reports) == ["ultramic-034f/raw"]
        assert reports["ultramic-034f/raw"].segments == 2
        assert reports["ultramic-034f/raw"].bytes_written == 20


@pytest.mark.unit
class TestContainerSummary:
    """Counters become rates; a replaced container does not produce a negative one."""

    def test_cpu_is_a_share_of_one_core(self) -> None:
        """Half a second of CPU time in one second is 50 %."""
        samples = [
            _sample(0.0, recorder=_container(0)),
            _sample(1.0, recorder=_container(500_000)),
            _sample(2.0, recorder=_container(600_000)),
        ]
        summary = summarise_containers(samples)["recorder"]
        assert summary["cpu_percent_max"] == pytest.approx(50.0)
        assert summary["cpu_percent_mean"] == pytest.approx(30.0)

    def test_restarted_container_is_skipped_for_that_interval(self) -> None:
        """A counter that went down is a new container, not negative CPU time."""
        samples = [
            _sample(0.0, recorder=_container(900_000, written=5_000_000)),
            _sample(1.0, recorder=_container(100_000, written=1_000_000)),
            _sample(2.0, recorder=_container(200_000, written=2_000_000)),
        ]
        summary = summarise_containers(samples)["recorder"]
        assert summary["cpu_percent_mean"] == pytest.approx(10.0)
        assert summary["written_mib"] is None

    def test_memory_mean_and_peak(self) -> None:
        """Private memory is reported as mean and peak over the run."""
        samples = [
            _sample(0.0, birdnet=_container(0, anon_mib=200.0)),
            _sample(1.0, birdnet=_container(1, anon_mib=400.0)),
        ]
        summary = summarise_containers(samples)["birdnet"]
        assert summary["anon_mib_mean"] == pytest.approx(300.0)
        assert summary["anon_mib_max"] == pytest.approx(400.0)
        assert summary["pss_mib_mean"] is None
