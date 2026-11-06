"""A Windows Job Object around the child: a memory limit; the process tree dies with it."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from typing import Any

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def assign(process: subprocess.Popen[bytes], memory_bytes: int | None) -> Any:
    """Put the process in a new job with the limits. Returns the job handle (or None on failure)."""
    if sys.platform != "win32":
        raise RuntimeError("Job Objects exist only on Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = _ExtendedLimits()
    flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if memory_bytes:
        flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
        limits.ProcessMemoryLimit = memory_bytes
    limits.BasicLimitInformation.LimitFlags = flags
    if not kernel.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        kernel.CloseHandle(job)
        return None
    handle = kernel.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, process.pid)
    if not handle or not kernel.AssignProcessToJobObject(job, handle):
        kernel.CloseHandle(job)
        return None
    kernel.CloseHandle(handle)
    return job


def close(job: Any) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Job Objects exist only on Windows")
    kernel = ctypes.WinDLL("kernel32")
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle(job)
