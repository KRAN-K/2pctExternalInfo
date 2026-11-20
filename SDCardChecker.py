#!/usr/bin/env python3
r"""
SD Card Checker  -  Micro SD / SD card health, authenticity and stability tester (Windows).

GUI:   python SDCardChecker.py
CLI:   python SDCardChecker.py --cli E:\ --mode quick|full [--size MB] [--report out.txt]

What it does
  1. CARD INFO      label, filesystem, size, free space, serial, reader/bus type, model,
                    firmware, health status, sector / cluster sizes, partition style.
  2. INTEGRITY      H2testw-style: fills the card with unique pseudo-random blocks, reads
                    everything back and compares. Detects fake capacity (wrap-around),
                    bad blocks and silent corruption.
  3. SPEED          sequential write / read MB/s, random 4K write / read IOPS,
                    write stall detection (cards that freeze mid-write).
  4. STABILITY      0-100 score + verdict combining errors, stalls and speed consistency.

Only free space is tested. Existing files are never touched; all test files
(SDCHK_*.bin) are deleted when the test ends (even if it fails or you press Stop).
Only the standard library is needed (Python 3.9+).
"""
import argparse
import json
import os
import queue
import random
import statistics
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime

BLOCK = 1024 * 1024            # 1 MiB test block
FILE_BLOCKS = 256              # 256 MiB per test file
PREFIX = "SDCHK_"
IS_WIN = sys.platform.startswith("win")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def fmt_size(n):
    if n is None:
        return "n/a"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def marketing_size(n):
    """Cards are sold in decimal GB. Return e.g. '32 GB' style string."""
    return f"{n / 1e9:.1f} GB (decimal, as printed on the card)"


def make_block(index, seed):
    """Deterministic 1 MiB block; first 16 bytes carry its own index + seed."""
    rng = random.Random((seed << 32) ^ index)
    body = rng.randbytes(BLOCK - 16)
    return struct.pack("<QQ", index, seed) + body


def hidden_flags():
    return subprocess.CREATE_NO_WINDOW if IS_WIN else 0


# ----------------------------------------------------------------------------
# card info
# ----------------------------------------------------------------------------
PS_INFO = r"""
$ErrorActionPreference='SilentlyContinue'
$dl='{DL}'
$out=@{}
$ld=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${dl}:'"
$out.Label=$ld.VolumeName; $out.FileSystem=$ld.FileSystem; $out.Size=$ld.Size; $out.Free=$ld.FreeSpace
$out.VolumeSerial=$ld.VolumeSerialNumber; $out.DriveType=$ld.DriveType
$vol=Get-CimInstance Win32_Volume -Filter "DriveLetter='${dl}:'"
$out.ClusterSize=$vol.BlockSize
$out.Compressed=$ld.Compressed
$part=Get-Partition -DriveLetter $dl
if($part){
  $d=Get-Disk -Number $part.DiskNumber
  $out.DiskNumber=$d.Number; $out.FriendlyName=$d.FriendlyName; $out.Model=$d.Model
  $out.DiskSerial=$d.SerialNumber; $out.BusType="$($d.BusType)"; $out.PartitionStyle="$($d.PartitionStyle)"
  $out.Health="$($d.HealthStatus)"; $out.Operational="$($d.OperationalStatus)"
  $out.DiskSize=$d.Size; $out.LogicalSector=$d.LogicalSectorSize; $out.PhysicalSector=$d.PhysicalSectorSize
  $out.Firmware=$d.FirmwareVersion; $out.IsReadOnly=$d.IsReadOnly; $out.PartitionOffset=$part.Offset
  $out.PartitionCount=(Get-Partition -DiskNumber $d.Number | Measure-Object).Count
  $pd=Get-PhysicalDisk | Where-Object { $_.DeviceId -eq "$($d.Number)" }
  if($pd){ $out.MediaType="$($pd.MediaType)"; $out.Manufacturer=$pd.Manufacturer; $out.SpindleSpeed=$pd.SpindleSpeed }
  $wd=Get-CimInstance Win32_DiskDrive | Where-Object { $_.Index -eq $d.Number }
  if($wd){ $out.PnpId=$wd.PNPDeviceID; $out.Interface=$wd.InterfaceType; $out.Capabilities=($wd.CapabilityDescriptions -join ', ') }
}
$out | ConvertTo-Json -Compress
"""


def list_drives():
    """Return list of (letter, description) for drives; removable first."""
    drives = []
    if IS_WIN:
        try:
            cmd = ["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_LogicalDisk | Select DeviceID,DriveType,VolumeName,Size | ConvertTo-Json -Compress"]
            raw = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                 creationflags=hidden_flags()).stdout
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            for d in data:
                if d.get("DriveType") in (2, 3) and d.get("Size"):
                    tag = "REMOVABLE" if d["DriveType"] == 2 else "fixed"
                    drives.append((d["DeviceID"] + "\\", f'{d["DeviceID"]}  {d.get("VolumeName") or ""}  '
                                   f'{fmt_size(d["Size"])}  [{tag}]', d["DriveType"]))
        except Exception:
            pass
        if not drives:
            import string
            for c in string.ascii_uppercase:
                if os.path.exists(f"{c}:\\"):
                    drives.append((f"{c}:\\", f"{c}:", 3))
        drives.sort(key=lambda x: (x[2] != 2, x[0]))
    return drives


def get_card_info(path):
    import shutil
    total, used, free = shutil.disk_usage(path)
    info = {"Path": path, "Total (usable)": total, "Free": free, "Used": used}
    if IS_WIN and len(path) >= 2 and path[1] == ":":
        try:
            script = PS_INFO.replace("{DL}", path[0].upper())
            raw = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=60,
                                 creationflags=hidden_flags()).stdout
            info["wmi"] = json.loads(raw)
        except Exception as e:
            info["wmi_error"] = str(e)
    return info


def info_lines(info):
    L = []
    w = info.get("wmi", {})
    L.append("=== CARD INFORMATION ===")
    L.append(f"Drive path        : {info['Path']}")
    if w.get("Label") is not None:
        L.append(f"Volume label      : {w.get('Label') or '(none)'}")
    L.append(f"Filesystem        : {w.get('FileSystem', 'n/a')}")
    L.append(f"Usable size       : {fmt_size(info['Total (usable)'])}   ({marketing_size(info['Total (usable)'])})")
    L.append(f"Used / Free       : {fmt_size(info['Used'])} / {fmt_size(info['Free'])}")
    if w:
        L.append(f"Volume serial     : {w.get('VolumeSerial', 'n/a')}")
        L.append(f"Cluster size      : {fmt_size(w.get('ClusterSize'))}")
        L.append("--- Device ---")
        L.append(f"Name              : {w.get('FriendlyName', 'n/a')}")
        L.append(f"Model             : {w.get('Model', 'n/a')}")
        L.append(f"Manufacturer      : {w.get('Manufacturer') or 'n/a'}")
        L.append(f"Device serial     : {(w.get('DiskSerial') or 'n/a').strip() if isinstance(w.get('DiskSerial'), str) else 'n/a'}")
        L.append(f"Firmware          : {w.get('Firmware') or 'n/a'}")
        L.append(f"Bus / interface   : {w.get('BusType', 'n/a')} / {w.get('Interface', 'n/a')}")
        L.append(f"Media type        : {w.get('MediaType', 'n/a')}")
        L.append(f"Raw disk size     : {fmt_size(w.get('DiskSize'))}")
        L.append(f"Sector size       : logical {w.get('LogicalSector', 'n/a')} / physical {w.get('PhysicalSector', 'n/a')}")
        L.append(f"Partition style   : {w.get('PartitionStyle', 'n/a')}  ({w.get('PartitionCount', '?')} partition(s))")
        L.append(f"Partition offset  : {fmt_size(w.get('PartitionOffset'))}")
        L.append(f"Health / state    : {w.get('Health', 'n/a')} / {w.get('Operational', 'n/a')}")
        L.append(f"Write-protected   : {w.get('IsReadOnly', 'n/a')}")
        L.append(f"PnP id            : {w.get('PnpId', 'n/a')}")
        L.append("Note: SD/microSD cards do not expose S.M.A.R.T., and the CID/CSD registers")
        L.append("      (manufacturer, date, true speed class) are hidden by most USB readers.")
    else:
        L.append("(Detailed hardware info needs Windows + PowerShell.)")
    return L


# ----------------------------------------------------------------------------
# tests
# ----------------------------------------------------------------------------
class Stopped(Exception):
    pass


class Tester:
    def __init__(self, path, mode="quick", size_mb=None, log=print, progress=None, stop=None):
        self.path = path
        self.mode = mode
        self.size_mb = size_mb
        self.log = log
        self.progress = progress or (lambda p, t: None)
        self.stop = stop or threading.Event()
        self.files = []
        self.res = {}

    # -- util
    def _check_stop(self):
        if self.stop.is_set():
            raise Stopped()

    def _path(self, i):
        return os.path.join(self.path, f"{PREFIX}{i:04d}.bin")

    def cleanup(self):
        for p in list(self.files):
            try:
                os.remove(p)
            except OSError:
                pass
        # leftovers from a crashed earlier run
        try:
            for n in os.listdir(self.path):
                if n.startswith(PREFIX) and n.endswith(".bin"):
                    try:
                        os.remove(os.path.join(self.path, n))
                    except OSError:
                        pass
        except OSError:
            pass
        self.files = []

    # -- integrity + sequential speed
    def integrity(self):
        import shutil
        free = shutil.disk_usage(self.path).free
        safety = 8 * BLOCK
        if self.mode == "full":
            target_blocks = max(1, (free - safety) // BLOCK)
        else:
            mb = self.size_mb or 512
            target_blocks = max(1, min(mb, (free - safety) // BLOCK))
        seed = random.randrange(1, 2 ** 31)
        self.res["blocks_planned"] = int(target_blocks)
        self.log(f"Integrity test: writing {fmt_size(target_blocks * BLOCK)} "
                 f"({self.mode}) of unique data...")

        write_times = []
        write_err = None
        written = 0
        t0 = time.time()
        idx = 0
        file_no = 0
        try:
            while idx < target_blocks:
                self._check_stop()
                p = self._path(file_no)
                self.files.append(p)
                n = min(FILE_BLOCKS, target_blocks - idx)
                with open(p, "wb", buffering=0) as f:
                    for _ in range(n):
                        self._check_stop()
                        data = make_block(idx, seed)
                        s = time.perf_counter()
                        f.write(data)
                        write_times.append(time.perf_counter() - s)
                        idx += 1
                        written += BLOCK
                        if idx % 8 == 0:
                            self.progress(idx / target_blocks * 0.5, "Writing")
                    s = time.perf_counter()
                    os.fsync(f.fileno())
                    write_times[-1] += time.perf_counter() - s
                file_no += 1
        except Stopped:
            raise
        except OSError as e:
            write_err = str(e)
            self.log(f"!! Write error after {fmt_size(written)}: {e}")
        wdur = time.time() - t0
        self.res["write_error"] = write_err
        self.res["bytes_written"] = written
        self.res["write_times"] = write_times
        self.res["write_MBps"] = (written / 1e6) / wdur if wdur > 0 and written else 0.0

        # verify
        self.log("Reading everything back and comparing...")
        bad = 0
        first_bad = None
        wrap_hits = 0
        read_times = []
        r0 = time.time()
        total_blocks = written // BLOCK
        idx = 0
        for fi, p in enumerate(self.files):
            self._check_stop()
            try:
                with open(p, "rb", buffering=0) as f:
                    while True:
                        self._check_stop()
                        s = time.perf_counter()
                        data = f.read(BLOCK)
                        read_times.append(time.perf_counter() - s)
                        if not data:
                            break
                        if len(data) == BLOCK and data == make_block(idx, seed):
                            pass
                        else:
                            bad += 1
                            if first_bad is None:
                                first_bad = idx
                            if len(data) >= 16:
                                found_idx, found_seed = struct.unpack("<QQ", data[:16])
                                if found_seed == seed and found_idx != idx:
                                    wrap_hits += 1
                        idx += 1
                        if idx % 8 == 0:
                            self.progress(0.5 + idx / max(1, total_blocks) * 0.5, "Verifying")
            except OSError as e:
                bad += 1
                self.log(f"!! Read error in {os.path.basename(p)}: {e}")
        rdur = time.time() - r0
        self.res["bad_blocks"] = bad
        self.res["first_bad_block"] = first_bad
        self.res["wrap_hits"] = wrap_hits
        self.res["read_MBps"] = (written / 1e6) / rdur if rdur > 0 and written else 0.0
        self.res["read_times"] = read_times
        if bad == 0 and not write_err:
            self.log(f"OK: {fmt_size(written)} written and verified, 0 errors.")
        else:
            self.log(f"!! {bad} bad block(s) of {total_blocks}. "
                     + (f"First bad block at ~{fmt_size(first_bad * BLOCK)}. " if first_bad is not None else "")
                     + ("Wrap-around pattern found = FAKE CAPACITY likely." if wrap_hits else ""))

    # -- random 4K
    def random_io(self):
        self._check_stop()
        p = os.path.join(self.path, f"{PREFIX}rand.bin")
        self.files.append(p)
        size = 32 * BLOCK
        self.log("Random 4K test...")
        try:
            with open(p, "wb") as f:
                f.write(os.urandom(size))
                f.flush()
                os.fsync(f.fileno())
            rng = random.Random(1234)
            offs = [rng.randrange(0, size // 4096) * 4096 for _ in range(300)]
            buf = os.urandom(4096)
            fd = os.open(p, os.O_RDWR | getattr(os, "O_BINARY", 0))
            t = time.perf_counter()
            for o in offs:
                self._check_stop()
                os.lseek(fd, o, os.SEEK_SET)
                os.write(fd, buf)
                os.fsync(fd)
            wd = time.perf_counter() - t
            os.close(fd)
            fd = os.open(p, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            offs2 = [rng.randrange(0, size // 4096) * 4096 for _ in range(1000)]
            t = time.perf_counter()
            for o in offs2:
                os.lseek(fd, o, os.SEEK_SET)
                os.read(fd, 4096)
            rd = time.perf_counter() - t
            os.close(fd)
            self.res["rand_write_iops"] = len(offs) / wd
            self.res["rand_read_iops"] = len(offs2) / rd
            self.log(f"Random 4K: write {self.res['rand_write_iops']:.0f} IOPS, "
                     f"read {self.res['rand_read_iops']:.0f} IOPS")
        except Stopped:
            raise
        except OSError as e:
            self.log(f"!! Random I/O error: {e}")
            self.res["rand_error"] = str(e)

    # -- analysis
    def analyse(self):
        r = self.res
        wt = r.get("write_times") or []
        notes = []
        score = 100.0
        stalls = 0
        cv = 0.0
        if len(wt) >= 8:
            med = statistics.median(wt)
            stalls = sum(1 for x in wt if x > max(med * 8, 0.5))
            # throughput variability measured on 16-block windows
            win = [sum(wt[i:i + 16]) for i in range(0, len(wt) - 15, 16)]
            if len(win) >= 3 and statistics.mean(win) > 0:
                cv = statistics.pstdev(win) / statistics.mean(win)
            r["slowest_block_s"] = max(wt)
            r["min_window_MBps"] = 16 / max(win) if win else None
            r["max_window_MBps"] = 16 / min(win) if win else None
        r["stalls"] = stalls
        r["speed_cv"] = cv

        if r.get("write_error"):
            score = min(score, 20)
            notes.append("Write failed before the planned amount was written (card full / protected / failing).")
        bad = r.get("bad_blocks", 0)
        if bad:
            score = 0
            if r.get("wrap_hits"):
                notes.append("Data from earlier addresses reappears at later ones: classic FAKE CAPACITY card.")
                if r.get("first_bad_block") is not None:
                    notes.append(f"Real usable capacity is probably about {fmt_size(r['first_bad_block'] * BLOCK)} "
                                 f"(+ already-used space).")
            else:
                notes.append("Data read back differs from what was written: corrupted / failing flash.")
        if stalls:
            penalty = min(35, stalls * 5)
            score -= penalty
            notes.append(f"{stalls} write stall(s) (single 1 MB writes >0.5 s). Typical of worn or low-quality cards.")
        if cv > 0.5:
            score -= 15
            notes.append("Write speed fluctuates strongly between windows (inconsistent / throttling).")
        elif cv > 0.25:
            score -= 7
            notes.append("Write speed is somewhat uneven.")
        w, rd = r.get("write_MBps", 0), r.get("read_MBps", 0)
        if w and w < 3:
            score -= 20
            notes.append("Sequential write under 3 MB/s: extremely slow (below Class 4).")
        elif w and w < 10:
            score -= 8
            notes.append("Sequential write under 10 MB/s: below Class 10 / U1.")
        if r.get("rand_write_iops") is not None and r["rand_write_iops"] < 20:
            score -= 8
            notes.append("Very low random-write IOPS: poor for Android/Pi system use (A1 needs ~500 write IOPS).")
        if r.get("rand_error"):
            score -= 10
        score = max(0, min(100, round(score)))
        r["score"] = score
        if bad and r.get("wrap_hits"):
            verdict = "FAKE CAPACITY - DO NOT TRUST"
        elif bad:
            verdict = "FAILING - DATA CORRUPTION"
        elif score >= 90:
            verdict = "EXCELLENT - stable"
        elif score >= 75:
            verdict = "GOOD - stable"
        elif score >= 55:
            verdict = "FAIR - usable for non-critical data"
        else:
            verdict = "POOR - unreliable"
        r["verdict"] = verdict
        r["notes"] = notes
        # speed class guess from sequential write
        if w:
            cls = ("U3 / V30 class" if w >= 30 else "U1 / V10 / Class 10" if w >= 10
                   else "Class 6" if w >= 6 else "Class 4" if w >= 4 else "Class 2 or below")
            r["speed_class_guess"] = f"{cls} (measured {w:.1f} MB/s sequential write)"

    def run(self):
        try:
            self.cleanup()
            self.integrity()
            self.random_io()
            self.progress(1.0, "Done")
        finally:
            self.cleanup()
        self.analyse()
        return self.res


def result_lines(r):
    L = ["", "=== TEST RESULTS ==="]
    L.append(f"Data written/verified : {fmt_size(r.get('bytes_written', 0))}")
    L.append(f"Bad blocks            : {r.get('bad_blocks', 0)}"
             + (f"  (first at ~{fmt_size(r['first_bad_block'] * BLOCK)})" if r.get('first_bad_block') is not None else ""))
    L.append(f"Sequential write      : {r.get('write_MBps', 0):.1f} MB/s")
    L.append(f"Sequential read       : {r.get('read_MBps', 0):.1f} MB/s")
    if r.get("rand_write_iops") is not None:
        L.append(f"Random 4K write       : {r['rand_write_iops']:.0f} IOPS")
        L.append(f"Random 4K read        : {r['rand_read_iops']:.0f} IOPS (may be cache assisted)")
    if r.get("min_window_MBps"):
        L.append(f"Write speed range     : {r['min_window_MBps']:.1f} - {r['max_window_MBps']:.1f} MB/s over 16 MB windows")
    L.append(f"Write stalls          : {r.get('stalls', 0)}   (slowest 1MB write {r.get('slowest_block_s', 0):.2f} s)")
    L.append(f"Speed variability     : {r.get('speed_cv', 0) * 100:.0f}%")
    if r.get("speed_class_guess"):
        L.append(f"Speed class estimate  : {r['speed_class_guess']}")
    L.append("")
    L.append(f"STABILITY SCORE       : {r['score']} / 100")
    L.append(f"VERDICT               : {r['verdict']}")
    for n in r.get("notes", []):
        L.append(f"  - {n}")
    return L


# ----------------------------------------------------------------------------
# DELETED FILE RECOVERY  (read-only signature carving)
# ----------------------------------------------------------------------------
import hashlib
import re

ALIGN = 4096
CHUNK = 8 * 1024 * 1024
MB = 1024 * 1024


class RawReader:
    """Read-only, sector-aligned access to a raw volume (E:) or a disk image file."""

    def __init__(self, src):
        self.is_dev = False
        if IS_WIN and len(src) >= 2 and src[1] == ":" and len(src.rstrip("\\/")) == 2:
            self.path = "\\\\.\\" + src[:2]
            self.is_dev = True
        else:
            self.path = src
        try:
            self.f = open(self.path, "rb", buffering=0)
        except PermissionError:
            raise PermissionError("Access denied. Right-click Command Prompt / PowerShell, choose "
                                  "'Run as administrator', then start the program again.")
        self.size = self._size()
        self._co, self._cd = -1, b""

    def _size(self):
        if self.is_dev and IS_WIN:
            try:
                import ctypes
                import msvcrt
                buf = ctypes.create_string_buffer(8)
                ret = ctypes.c_ulong(0)
                h = msvcrt.get_osfhandle(self.f.fileno())
                ok = ctypes.windll.kernel32.DeviceIoControl(h, 0x7405C, None, 0, buf, 8,
                                                            ctypes.byref(ret), None)
                if ok:
                    return int.from_bytes(buf.raw, "little")
            except Exception:
                pass
        self.f.seek(0, 2)
        n = self.f.tell()
        self.f.seek(0)
        return n

    def read_at(self, off, n):
        if off < 0 or n <= 0:
            return b""
        a = off // ALIGN * ALIGN
        end = -(-(off + n) // ALIGN) * ALIGN
        self.f.seek(a)
        data = self.f.read(end - a)
        return data[off - a: off - a + n]

    def get(self, off, n):
        """Cached small reads for format walkers."""
        if self._co >= 0 and off >= self._co and off + n <= self._co + len(self._cd):
            return self._cd[off - self._co: off - self._co + n]
        want = max(n, 4 * MB)
        self._cd = self.read_at(off, want)
        self._co = off
        return self._cd[:n]

    def close(self):
        self.f.close()


def u16be(b): return int.from_bytes(b, "big")
def u32be(b): return int.from_bytes(b, "big")
def u16le(b): return int.from_bytes(b, "little")
def u32le(b): return int.from_bytes(b, "little")
def u64le(b): return int.from_bytes(b, "little")


# ---- format walkers: return exact file length or None ----------------------
_JPG_NEXT = re.compile(rb"\xff[\x01-\xcf\xd8-\xfe]")


def walk_jpeg(rd, s, limit):
    pos = s + 2
    while pos - s < limit:
        b = rd.get(pos, 4)
        if len(b) < 2 or b[0] != 0xFF:
            return None
        m = b[1]
        if m == 0xFF:
            pos += 1
            continue
        if m == 0xD9:
            return pos + 2 - s
        if m == 0x01 or 0xD0 <= m <= 0xD7:
            pos += 2
            continue
        if len(b) < 4:
            return None
        seglen = u16be(b[2:4])
        if seglen < 2:
            return None
        pos += 2 + seglen
        if m == 0xDA:                       # scan data: skip entropy-coded bytes
            while pos - s < limit:
                blk = rd.read_at(pos, 256 * 1024)
                if not blk:
                    return None
                mt = _JPG_NEXT.search(blk)
                if mt:
                    pos += mt.start()
                    break
                pos += len(blk) - 1
            else:
                return None
    return None


def walk_png(rd, s, limit):
    pos = s + 8
    while pos - s < limit:
        h = rd.get(pos, 8)
        if len(h) < 8:
            return None
        ln, typ = u32be(h[:4]), h[4:8]
        if not typ.isalpha():
            return None
        pos += 12 + ln
        if typ == b"IEND":
            return pos - s
    return None


def _subblocks(rd, pos):
    while True:
        b = rd.get(pos, 1)
        if not b:
            return None
        pos += 1 + b[0]
        if b[0] == 0:
            return pos


def walk_gif(rd, s, limit):
    h = rd.get(s, 13)
    if len(h) < 13:
        return None
    pos = s + 13
    if h[10] & 0x80:
        pos += 3 * (2 ** ((h[10] & 7) + 1))
    while pos - s < limit:
        b = rd.get(pos, 1)
        if not b:
            return None
        if b[0] == 0x3B:
            return pos + 1 - s
        if b[0] == 0x21:
            pos = _subblocks(rd, pos + 2)
        elif b[0] == 0x2C:
            d = rd.get(pos, 10)
            if len(d) < 10:
                return None
            pos += 10
            if d[9] & 0x80:
                pos += 3 * (2 ** ((d[9] & 7) + 1))
            pos = _subblocks(rd, pos + 1)
        else:
            return None
        if pos is None:
            return None
    return None


def walk_bmp(rd, s, limit):
    h = rd.get(s, 18)
    if len(h) < 18:
        return None
    size = u32le(h[2:6])
    if h[6:10] != b"\0\0\0\0" or u32le(h[14:18]) not in (12, 40, 52, 56, 64, 108, 124):
        return None
    return size if 1024 <= size <= limit else None


def walk_riff(rd, s, limit):
    h = rd.get(s, 12)
    if len(h) < 12 or h[8:12] not in (b"WAVE", b"AVI "):
        return None
    size = u32le(h[4:8]) + 8
    return size if 1024 <= size <= limit else None


def walk_7z(rd, s, limit):
    h = rd.get(s, 32)
    if len(h) < 32:
        return None
    size = 32 + u64le(h[12:20]) + u64le(h[20:28])
    return size if 64 <= size <= limit else None


def walk_sqlite(rd, s, limit):
    h = rd.get(s, 100)
    if len(h) < 100:
        return None
    ps = u16be(h[16:18])
    ps = 65536 if ps == 1 else ps
    pages = u32be(h[28:32])
    if ps < 512 or ps & (ps - 1) or pages == 0:
        return None
    size = ps * pages
    return size if size <= limit else None


def walk_zip(rd, s, limit):
    pos = s
    while pos - s < limit:
        blk = rd.read_at(pos, 4 * MB)
        if not blk:
            return None
        i = blk.find(b"PK\x05\x06")
        while i != -1:
            e = blk[i:i + 22]
            if len(e) == 22:
                cd_size, cd_off = u32le(e[12:16]), u32le(e[16:20])
                if cd_off + cd_size == pos + i - s:        # central directory ends exactly here
                    return pos + i - s + 22 + u16le(e[20:22])
            i = blk.find(b"PK\x05\x06", i + 1)
        pos += max(1, len(blk) - 3)
    return None


_PDF_LIN = re.compile(rb"/L\s+(\d+)")


def walk_pdf(rd, s, limit):
    head = rd.get(s, 2048)
    if b"/Linearized" in head:
        m = _PDF_LIN.search(head)
        if m and 1024 < int(m.group(1)) <= limit:
            return int(m.group(1))
    pos, last = s, None
    while pos - s < limit:
        blk = rd.read_at(pos, 2 * MB)
        if not blk:
            break
        i = blk.find(b"%%EOF")
        if i == -1:
            if last is not None:
                break
            pos += max(1, len(blk) - 5)
            continue
        last = pos + i + 5
        nxt = blk.find(b"%PDF-", i)
        j = blk.find(b"%%EOF", i + 5)
        if j == -1 or (nxt != -1 and nxt < j):
            break
        while j != -1 and (nxt == -1 or j < nxt):
            last = pos + j + 5
            j = blk.find(b"%%EOF", j + 5)
        break
    if last is None:
        return None
    tail = rd.get(last, 2)
    if tail[:2] == b"\r\n":
        last += 2
    elif tail[:1] in (b"\n", b"\r"):
        last += 1
    return last - s


_MP4_ATOMS = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"meta", b"pnot",
              b"junk", b"moof", b"mfra", b"sidx", b"styp", b"pdin", b"udta"}


def walk_mp4(rd, s, limit):
    pos, seen_ftyp, seen_data = s, False, False
    while pos - s < limit:
        h = rd.get(pos, 16)
        if len(h) < 8:
            break
        size, typ = u32be(h[:4]), h[4:8]
        if typ not in _MP4_ATOMS:
            break
        if size == 1:
            if len(h) < 16:
                break
            size = int.from_bytes(h[8:16], "big")
        if size < 8:
            break
        if typ == b"ftyp":
            seen_ftyp = True
        if typ in (b"moov", b"mdat", b"moof"):
            seen_data = True
        pos += size
    length = pos - s
    return length if seen_ftyp and seen_data and 4096 <= length <= limit else None


# ---- type table --------------------------------------------------------------
# key, group, signature, bytes before signature, walker, max size, min size
TYPES = [
    ("jpg", "Photos", b"\xff\xd8\xff", 0, walk_jpeg, 100 * MB, 2048),
    ("png", "Photos", b"\x89PNG\r\n\x1a\n", 0, walk_png, 100 * MB, 512),
    ("gif", "Photos", b"GIF8", 0, walk_gif, 100 * MB, 512),
    ("bmp", "Photos", b"BM", 0, walk_bmp, 200 * MB, 1024),
    ("pdf", "Documents", b"%PDF-", 0, walk_pdf, 300 * MB, 1024),
    ("zip", "Documents", b"PK\x03\x04", 0, walk_zip, 2048 * MB, 100),
    ("mp4", "Video", b"ftyp", 4, walk_mp4, 8192 * MB, 4096),
    ("wav", "Audio_Video", b"RIFF", 0, walk_riff, 2048 * MB, 1024),
    ("7z", "Other", b"7z\xbc\xaf\x27\x1c", 0, walk_7z, 2048 * MB, 64),
    ("db", "Other", b"SQLite format 3\x00", 0, walk_sqlite, 1024 * MB, 512),
]
GROUPS = {"Photos": ["jpg", "png", "gif", "bmp"], "Documents": ["pdf", "zip"],
          "Video": ["mp4"], "Audio_Video": ["wav"], "Other": ["7z", "db"]}


def pick_ext(rd, s, length, key):
    if key == "zip":
        sample = rd.read_at(s, 4096) + rd.read_at(s + max(0, length - 65536), min(length, 65536))
        for needle, ext in ((b"word/", "docx"), (b"xl/", "xlsx"), (b"ppt/", "pptx"),
                            (b"AndroidManifest.xml", "apk"), (b"application/vnd.oasis.opendocument.text", "odt"),
                            (b"application/vnd.oasis.opendocument.spreadsheet", "ods")):
            if needle in sample:
                return ext
        return "zip"
    if key == "mp4":
        brand = rd.get(s + 8, 4)
        if brand == b"qt  ":
            return "mov"
        if brand[:3] == b"3gp":
            return "3gp"
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "heic"
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        return "mp4"
    if key == "wav":
        return "wav" if rd.get(s + 8, 4) == b"WAVE" else "avi"
    return key


def quick_check(key, head):
    if key == "jpg":
        return len(head) > 3 and head[3] in (0xE0, 0xE1, 0xE2, 0xE8, 0xDB, 0xEE, 0xED, 0xFE, 0xC0)
    if key == "gif":
        return head[:6] in (b"GIF87a", b"GIF89a")
    if key == "bmp":
        return head[6:10] == b"\0\0\0\0"
    return True


def build_existing_hashes(root, log, stop):
    """SHA-256 of every file that still exists, so they are not 'recovered' again."""
    seen = set()
    log("Indexing files that still exist on the card (so they are skipped)...")
    for dp, dn, fn in os.walk(root):
        for n in fn:
            if stop.is_set():
                return seen
            p = os.path.join(dp, n)
            try:
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for b in iter(lambda: f.read(MB), b""):
                        h.update(b)
                seen.add((os.path.getsize(p), h.hexdigest()))
            except OSError:
                pass
    log(f"  {len(seen)} existing file(s) indexed.")
    return seen


def same_volume(src, out):
    if IS_WIN:
        return os.path.splitdrive(os.path.abspath(out))[0].upper() == src[:2].upper() and len(src) >= 2 and src[1] == ":"
    return False


def recover_files(src, outdir, groups=None, skip_existing=True, log=print, progress=None, stop=None):
    """Carve deleted files from src (drive like 'E:\\' or an image file) into outdir."""
    stop = stop or threading.Event()
    progress = progress or (lambda f, s: None)
    if same_volume(src, outdir):
        raise ValueError("Output folder must be on a DIFFERENT drive than the card, "
                         "otherwise recovered data would overwrite the deleted files.")
    os.makedirs(outdir, exist_ok=True)
    wanted = set()
    for g in (groups or GROUPS.keys()):
        wanted.update(GROUPS[g])
    types = [t for t in TYPES if t[0] in wanted]

    existing = set()
    is_drive = IS_WIN and len(src) >= 2 and src[1] == ":" and len(src.rstrip("\\/")) == 2
    if skip_existing and is_drive:
        existing = build_existing_hashes(src[:2] + "\\", log, stop)

    rd = RawReader(src)
    log(f"Scanning {fmt_size(rd.size)} read-only. Recovered files go to: {outdir}")
    found, skipped_existing, rejected = [], 0, 0
    skip_until = 0
    n = 0
    t0 = time.time()
    try:
        base = 0
        while base < rd.size:
            if stop.is_set():
                log("Stopped by user.")
                break
            data = rd.read_at(base, CHUNK)
            if not data:
                base += CHUNK
                continue
            hits = []
            for key, grp, sig, pre, walker, mx, mn in types:
                i = data.find(sig)
                while i != -1:
                    off = base + i - pre
                    if i - pre >= 0 and off % 512 == 0 and quick_check(key, data[i - pre:i - pre + 64]):
                        hits.append((off, key, grp, walker, mx, mn))
                    i = data.find(sig, i + 1)
            hits.sort()
            for off, key, grp, walker, mx, mn in hits:
                if off < skip_until or stop.is_set():
                    continue
                limit = min(rd.size - off, mx)
                try:
                    length = walker(rd, off, limit)
                except Exception:
                    length = None
                if not length or length < mn or length > limit:
                    rejected += 1
                    continue
                ext = pick_ext(rd, off, length, key)
                d = os.path.join(outdir, grp)
                os.makedirs(d, exist_ok=True)
                n += 1
                name = f"rec_{n:05d}_at{off // MB}MB.{ext}"
                path = os.path.join(d, name)
                h = hashlib.sha256()
                with open(path, "wb") as fo:
                    p = 0
                    while p < length:
                        part = rd.read_at(off + p, min(4 * MB, length - p))
                        if not part:
                            break
                        fo.write(part)
                        h.update(part)
                        p += len(part)
                if (length, h.hexdigest()) in existing:
                    os.remove(path)
                    skipped_existing += 1
                    n -= 1
                else:
                    found.append((name, grp, ext, off, length))
                    log(f"  recovered {grp}/{name}  ({fmt_size(length)})")
                skip_until = off + length
            base += CHUNK
            progress(min(1.0, base / rd.size), f"Scanning  ({len(found)} found)")
    finally:
        rd.close()
    csv = os.path.join(outdir, "recovery_report.csv")
    with open(csv, "w", encoding="utf-8") as f:
        f.write("file,group,type,offset_bytes,size_bytes\n")
        for r in found:
            f.write(",".join(str(x) for x in r) + "\n")
    log(f"Done in {time.time() - t0:.0f} s: {len(found)} file(s) recovered, "
        f"{skipped_existing} skipped (still on card), {rejected} damaged/partial candidates ignored.")
    log(f"List saved to {csv}")
    progress(1.0, "Done")
    return found


def image_card(src, dest, log=print, progress=None, stop=None):
    """Make a sector-by-sector copy of the card (bad areas are zero-filled)."""
    stop = stop or threading.Event()
    progress = progress or (lambda f, s: None)
    if same_volume(src, dest):
        raise ValueError("Save the image on a different drive than the card.")
    rd = RawReader(src)
    bad = 0
    try:
        with open(dest, "wb") as fo:
            off = 0
            while off < rd.size and not stop.is_set():
                n = min(4 * MB, rd.size - off)
                try:
                    data = rd.read_at(off, n)
                except OSError:
                    data = b""
                    for p in range(0, n, 64 * 1024):
                        m = min(64 * 1024, n - p)
                        try:
                            data += rd.read_at(off + p, m)
                        except OSError:
                            data += b"\0" * m
                            bad += 1
                if len(data) < n:
                    data += b"\0" * (n - len(data))
                fo.write(data)
                off += n
                progress(off / rd.size, "Imaging")
    finally:
        rd.close()
    log(f"Image written to {dest}" + (f" ({bad} unreadable 64 KB area(s) zero-filled)" if bad else ""))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def run_cli(args):
    info = get_card_info(args.cli)
    out = info_lines(info)
    print("\n".join(out))
    t = Tester(args.cli, args.mode, args.size, log=lambda m: print(m, flush=True),
               progress=lambda p, s: print(f"\r{s}: {p * 100:3.0f}%", end="", flush=True) if False else None)
    res = t.run()
    rl = result_lines(res)
    print("\n".join(rl))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(f"SD Card Checker report - {datetime.now():%Y-%m-%d %H:%M}\n\n")
            f.write("\n".join(out + rl) + "\n")
        print(f"Report saved to {args.report}")


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("SD Card Checker")
    root.geometry("880x760")
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    tab = ttk.Frame(nb)
    rtab = ttk.Frame(nb)
    nb.add(tab, text="  Test & Info  ")
    nb.add(rtab, text="  Recover deleted files  ")
    q = queue.Queue()
    stop_evt = threading.Event()
    state = {"report": "", "running": False}

    top = ttk.Frame(tab, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Card / drive:").grid(row=0, column=0, sticky="w")
    drives = list_drives()
    labels = [d[1] for d in drives]
    combo = ttk.Combobox(top, values=labels, width=48, state="readonly")
    if labels:
        combo.current(0)
    combo.grid(row=0, column=1, padx=6)

    def refresh():
        nonlocal drives
        drives = list_drives()
        combo["values"] = [d[1] for d in drives]
        if drives:
            combo.current(0)

    ttk.Button(top, text="Refresh", command=refresh).grid(row=0, column=2)
    ttk.Button(top, text="Browse folder...", command=lambda: browse()).grid(row=0, column=3, padx=4)
    custom = {"path": None}

    def browse():
        p = filedialog.askdirectory(title="Pick the card's root folder")
        if p:
            custom["path"] = p
            combo.set(p)

    mode = tk.StringVar(value="quick")
    opt = ttk.Frame(tab, padding=(8, 0))
    opt.pack(fill="x")
    ttk.Radiobutton(opt, text="Quick (512 MB, ~1-3 min)", variable=mode, value="quick").pack(side="left")
    ttk.Radiobutton(opt, text="Full (all free space - detects fake capacity, can take hours)",
                    variable=mode, value="full").pack(side="left", padx=12)

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")
    pb = ttk.Progressbar(tab, maximum=100)
    pb.pack(fill="x", padx=8)
    status = ttk.Label(tab, text="Idle")
    status.pack(anchor="w", padx=8)
    txt = tk.Text(tab, font=("Consolas", 10), wrap="none")
    txt.pack(fill="both", expand=True, padx=8, pady=8)

    def put(s):
        txt.insert("end", s + "\n")
        txt.see("end")

    def selected_path():
        sel = combo.get()
        if custom["path"] and sel == custom["path"]:
            return sel
        for d in drives:
            if d[1] == sel:
                return d[0]
        return None

    def show_info():
        p = selected_path()
        if not p:
            messagebox.showwarning("SD Card Checker", "Select a drive first.")
            return
        txt.delete("1.0", "end")
        status.config(text="Reading card info...")
        root.update_idletasks()
        lines = info_lines(get_card_info(p))
        state["report"] = "\n".join(lines)
        for l in lines:
            put(l)
        status.config(text="Idle")

    def start():
        p = selected_path()
        if not p:
            messagebox.showwarning("SD Card Checker", "Select a drive first.")
            return
        if state["running"]:
            return
        if not messagebox.askyesno(
                "Before you test",
                "The test writes to the card's FREE space, which is exactly where deleted files "
                "still live. If you want to recover deleted files, press No and use the "
                "'Recover deleted files' tab first.\n\nRun the test anyway?"):
            return
        if mode.get() == "full" and not messagebox.askyesno(
                "Full test", "The full test writes to ALL free space and can take a long time.\n"
                "Existing files are not touched. Continue?"):
            return
        txt.delete("1.0", "end")
        info_l = info_lines(get_card_info(p))
        for l in info_l:
            put(l)
        put("")
        stop_evt.clear()
        state["running"] = True
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")

        def worker():
            t = Tester(p, mode.get(), 512, log=lambda m: q.put(("log", m)),
                       progress=lambda f, s: q.put(("prog", (f, s))), stop=stop_evt)
            try:
                res = t.run()
                rl = result_lines(res)
                q.put(("done", (info_l, rl)))
            except Stopped:
                q.put(("log", "Stopped by user. Test files removed."))
                q.put(("done", None))
            except Exception as e:
                q.put(("log", f"Error: {e}"))
                q.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    put(val)
                elif kind == "prog":
                    pb["value"] = val[0] * 100
                    status.config(text=f"{val[1]}... {val[0] * 100:.0f}%")
                elif kind == "done":
                    state["running"] = False
                    start_btn.config(state="normal")
                    stop_btn.config(state="disabled")
                    status.config(text="Finished")
                    if val:
                        info_l, rl = val
                        for l in rl:
                            put(l)
                        state["report"] = "\n".join(info_l + rl)
        except queue.Empty:
            pass
        root.after(100, poll)

    def save():
        if not state["report"]:
            messagebox.showinfo("SD Card Checker", "Nothing to save yet.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".txt",
                                         initialfile=f"SDCard_Report_{datetime.now():%Y%m%d_%H%M}.txt")
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f"SD Card Checker report - {datetime.now():%Y-%m-%d %H:%M}\n\n{state['report']}\n")

    ttk.Button(btns, text="Card info only", command=show_info).pack(side="left")
    start_btn = ttk.Button(btns, text="Start test", command=start)
    start_btn.pack(side="left", padx=6)
    stop_btn = ttk.Button(btns, text="Stop", command=stop_evt.set, state="disabled")
    stop_btn.pack(side="left")
    ttk.Button(btns, text="Save report...", command=save).pack(side="left", padx=6)


    # ---------------- Recovery tab ----------------
    warn = tk.Label(rtab, justify="left", fg="#b00020", wraplength=820, anchor="w",
                    text="STOP USING THE CARD NOW. Every new file written to it can permanently overwrite "
                         "the deleted ones. Do NOT format it and do NOT run the Test tab. Recovery only reads "
                         "the card; save results on a DIFFERENT drive. Needs 'Run as administrator'.")
    warn.pack(fill="x", padx=8, pady=6)
    rf = ttk.Frame(rtab, padding=8)
    rf.pack(fill="x")
    ttk.Label(rf, text="Source (card or image):").grid(row=0, column=0, sticky="w")
    rcombo = ttk.Combobox(rf, values=[d[1] for d in drives], width=46)
    if drives:
        rcombo.current(0)
    rcombo.grid(row=0, column=1, padx=6, pady=2)

    def rbrowse_img():
        f = filedialog.askopenfilename(title="Pick a disk image", filetypes=[("Disk image", "*.img *.dd *.bin *.iso"), ("All", "*.*")])
        if f:
            rcombo.set(f)

    ttk.Button(rf, text="Use image file...", command=rbrowse_img).grid(row=0, column=2)
    ttk.Label(rf, text="Save recovered to:").grid(row=1, column=0, sticky="w")
    outvar = tk.StringVar(value=r"D:\Claude\Recovered" if IS_WIN else os.path.expanduser("~/Recovered"))
    ttk.Entry(rf, textvariable=outvar, width=49).grid(row=1, column=1, padx=6, pady=2)

    def rbrowse_out():
        d = filedialog.askdirectory(title="Folder on a DIFFERENT drive")
        if d:
            outvar.set(d)

    ttk.Button(rf, text="Browse...", command=rbrowse_out).grid(row=1, column=2)
    gv = {g: tk.BooleanVar(value=True) for g in GROUPS}
    gf = ttk.Frame(rtab, padding=(8, 0))
    gf.pack(fill="x")
    labels_g = {"Photos": "Photos (JPG, PNG, GIF, BMP)", "Documents": "Documents (PDF, DOCX/XLSX/PPTX, ZIP)",
                "Video": "Video (MP4, MOV, HEIC, 3GP)", "Audio_Video": "WAV / AVI", "Other": "7z, SQLite"}
    for g in GROUPS:
        ttk.Checkbutton(gf, text=labels_g[g], variable=gv[g]).pack(side="left", padx=4)
    skipvar = tk.BooleanVar(value=True)
    ttk.Checkbutton(rtab, text="Skip files that still exist on the card (recover only what was deleted)",
                    variable=skipvar).pack(anchor="w", padx=12, pady=4)
    rb = ttk.Frame(rtab, padding=8)
    rb.pack(fill="x")
    rpb = ttk.Progressbar(rtab, maximum=100)
    rpb.pack(fill="x", padx=8)
    rstatus = ttk.Label(rtab, text="Idle")
    rstatus.pack(anchor="w", padx=8)
    rtxt = tk.Text(rtab, font=("Consolas", 10), wrap="none")
    rtxt.pack(fill="both", expand=True, padx=8, pady=8)
    rq = queue.Queue()
    rstop = threading.Event()
    rstate = {"running": False}

    def rsrc():
        sel = rcombo.get().strip()
        for d in drives:
            if d[1] == sel:
                return d[0]
        return sel

    def rlog(m):
        rtxt.insert("end", m + "\n")
        rtxt.see("end")

    def rstart(kind):
        if rstate["running"]:
            return
        src = rsrc()
        if not src:
            messagebox.showwarning("Recovery", "Pick the card or an image file first.")
            return
        out = outvar.get().strip()
        if kind == "recover" and not out:
            messagebox.showwarning("Recovery", "Choose an output folder on a different drive.")
            return
        if kind == "image":
            out = filedialog.asksaveasfilename(title="Save disk image as", defaultextension=".img",
                                               initialfile="card_backup.img")
            if not out:
                return
        rtxt.delete("1.0", "end")
        rstop.clear()
        rstate["running"] = True
        for b_ in (rbtn_rec, rbtn_img):
            b_.config(state="disabled")
        rstop_btn.config(state="normal")
        groups = [g for g in GROUPS if gv[g].get()]

        def work():
            lg = lambda m: rq.put(("log", m))
            pg = lambda f, s_: rq.put(("prog", (f, s_)))
            try:
                if kind == "recover":
                    recover_files(src, out, groups, skipvar.get(), lg, pg, rstop)
                else:
                    image_card(src, out, lg, pg, rstop)
            except Exception as e:
                lg(f"ERROR: {e}")
            rq.put(("done", None))

        threading.Thread(target=work, daemon=True).start()

    def rpoll():
        try:
            while True:
                k, v = rq.get_nowait()
                if k == "log":
                    rlog(v)
                elif k == "prog":
                    rpb["value"] = v[0] * 100
                    rstatus.config(text=f"{v[1]}... {v[0] * 100:.0f}%")
                else:
                    rstate["running"] = False
                    for b_ in (rbtn_rec, rbtn_img):
                        b_.config(state="normal")
                    rstop_btn.config(state="disabled")
                    rstatus.config(text="Finished")
        except queue.Empty:
            pass
        root.after(150, rpoll)

    rbtn_rec = ttk.Button(rb, text="Scan and recover", command=lambda: rstart("recover"))
    rbtn_rec.pack(side="left")
    rbtn_img = ttk.Button(rb, text="Make disk image first (safest)", command=lambda: rstart("image"))
    rbtn_img.pack(side="left", padx=6)
    rstop_btn = ttk.Button(rb, text="Stop", command=rstop.set, state="disabled")
    rstop_btn.pack(side="left")
    rpoll()

    def on_close():
        stop_evt.set()
        rstop.set()
        root.after(300, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    poll()
    root.mainloop()


def is_admin():
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Re-start this script with a UAC prompt. Returns True if the new copy was started."""
    try:
        import ctypes
        exe = sys.executable
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            exe = w                              # no console window
        script = os.path.abspath(__file__)
        params = " ".join('"%s"' % a for a in [script] + sys.argv[1:])
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="SD Card Checker")
    ap.add_argument("--cli", metavar="PATH", help="run without GUI on this drive/folder, e.g. E:\\")
    ap.add_argument("--mode", choices=["quick", "full"], default="quick")
    ap.add_argument("--size", type=int, default=512, help="MB for quick mode")
    ap.add_argument("--report", help="write report to this file (CLI)")
    ap.add_argument("--recover", metavar="SRC", help="recover deleted files from this card/image, e.g. E:\\ or card.img")
    ap.add_argument("--out", help="output folder for --recover (must be on a different drive)")
    ap.add_argument("--types", default="", help="comma list of groups: Photos,Documents,Video,Audio_Video,Other")
    ap.add_argument("--keep-existing", action="store_true", help="also recover files that still exist")
    ap.add_argument("--image", nargs=2, metavar=("SRC", "DEST"), help="make a sector image of the card first")
    ap.add_argument("--no-admin", action="store_true", help="do not ask for administrator rights")
    a = ap.parse_args()
    needs_admin = not a.cli or a.image or a.recover
    if IS_WIN and needs_admin and not a.no_admin and not is_admin():
        if relaunch_as_admin():
            return                               # elevated copy is running
    if a.image:
        image_card(a.image[0], a.image[1])
    elif a.recover:
        if not a.out:
            ap.error("--recover needs --out FOLDER")
        grp = [g for g in a.types.split(",") if g in GROUPS] or None
        recover_files(a.recover, a.out, grp, not a.keep_existing)
    elif a.cli:
        run_cli(a)
    else:
        run_gui()


if __name__ == "__main__":
    main()
