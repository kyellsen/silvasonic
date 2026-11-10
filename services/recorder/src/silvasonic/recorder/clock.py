"""System clock synchronisation state (Issue 002).

A device without a battery-backed RTC boots with a stale clock and records
under it until NTP takes hold.  Segment timestamps are wall-clock times, so
the Recorder reports whether the kernel considers the clock synchronised.

The check mirrors systemd's ``timedatectl`` ("System clock synchronized"):
``adjtimex(2)`` in read-only mode, synchronised when the kernel's maximum
error estimate is below 16 s.  The kernel grows that estimate while no time
daemon disciplines the clock and caps it at 16 s.
"""

from __future__ import annotations

import ctypes
import ctypes.util

_MAXERROR_SYNCED_LIMIT_US = 16_000_000


class _Timex(ctypes.Structure):
    """Leading fields of ``struct timex``; the tail is reserved space."""

    _fields_ = [
        ("modes", ctypes.c_uint),
        ("offset", ctypes.c_long),
        ("freq", ctypes.c_long),
        ("maxerror", ctypes.c_long),
        ("esterror", ctypes.c_long),
        ("status", ctypes.c_int),
        # The kernel writes the whole struct (208 bytes on 64-bit Linux).
        ("_reserved", ctypes.c_char * 256),
    ]


def clock_synchronized() -> bool | None:
    """Return whether the system clock is synchronised to a time source.

    Returns:
        ``True`` or ``False``, or ``None`` if the state cannot be read
        (no ``adjtimex`` on this platform, or the call was refused).
    """
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        adjtimex = libc.adjtimex
    except (OSError, AttributeError):
        return None

    timex = _Timex()  # modes = 0: read only, no privilege required
    if adjtimex(ctypes.byref(timex)) < 0:
        return None
    return bool(timex.maxerror < _MAXERROR_SYNCED_LIMIT_US)
