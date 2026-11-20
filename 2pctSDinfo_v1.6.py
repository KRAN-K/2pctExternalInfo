# NEED PYTHON? Download the Windows installer here (copy and paste into your browser): https://www.python.org/downloads/windows/
# On the first installer screen tick "Add python.exe to PATH", click Install Now, then double-click this file (2pctSDinfo).
r"""
2%SDinfo  v1.6  -  Micro SD / SD card / USB drive checker, imager and recovery tool (Windows).

GUI:   python 2pctSDinfo_v1.6.py
CLI:   python 2pctSDinfo_v1.6.py --cli E:\ --mode quick|full [--size MB] [--report out.txt]

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
# App identity and version history  (add a new entry at the TOP of CHANGELOG for each release)
# ----------------------------------------------------------------------------
APP_NAME = "2%SDinfo"
APP_VERSION = "1.6"
APP_TAG = "v" + APP_VERSION
APP_TITLE = f"{APP_NAME} {APP_TAG}"
APP_TAGLINE = "SD card & USB drive checker, disk imager and deleted-file recovery"
APP_REPO = "https://github.com/KRAN-K/2pctExternalInfo"
CHANGELOG = [
    ("1.6", "2026-11-19", [
        "Themes renamed: Dark is now Black (true black), Dark Gray is now Gray and much lighter",
        "New theme: Violet Haze (purple)",
        "Your saved theme carries over from the old names",
    ]),
    ("1.5", "2026-11-19", [
        "Partitions tab (AOMEI-style): colored disk map, partition list, format, create, delete, resize, label, drive letter",
        "Initialize (MBR/GPT), Clean disk and Wipe disk (zero fill)",
        "Built-in FAT32 formatter for cards above 32 GB, which Windows refuses to format as FAT32",
        "Eject button and right-click menu in the devices panel",
        "Operations only run on removable / USB / SD disks; system and internal disks are protected",
        "Python download link at the top of the file for anyone who opens it in a text editor",
    ]),
    ("1.4", "2026-11-19", [
        "Theme dropdown replaces the dark-mode checkbox: Light, Dark, Dark Gray, Crimson Eclipse (black and red), Deep Ocean (navy and cyan)",
        "Chosen theme is remembered between launches",
    ]),
    ("1.3", "2026-11-19", [
        "Renamed to 2%SDinfo; version shown in the title, reports and file name",
        "About tab with version history and system details",
        "Dark mode (remembered between launches)",
        "Live devices panel on the right; click a device to select it in every tab",
        "Console window hides itself when the .py is double-clicked; .bat launcher removed",
    ]),
    ("1.2", "2026-11-19", [
        "Disk Imager tab: read card to image, write image to card, verify, MD5/SHA-1/SHA-256 hash",
        "Safety locks: removable/USB/SD only, system disk refused, typed confirmation, size check",
        "Automatic administrator prompt on start",
    ]),
    ("1.1", "2026-11-19", [
        "Recover deleted files tab: read-only signature recovery for photos, documents, video and more",
        "Skip-existing filter, disk-image-first option, output must be on another drive",
    ]),
    ("1.0", "2026-11-19", [
        "Card info, integrity / fake-capacity test, speed test and 0-100 stability score",
        "GUI and command-line modes, saved reports",
    ]),
]
# Extra sections for the About tab. Add (title, [lines]) tuples here to show more information later.
ABOUT_EXTRA = [
    ("Good to know", [
        "SD and microSD cards have no S.M.A.R.T. data; USB readers usually hide the CID/CSD registers.",
        "Quick test cannot prove full capacity; only the Full test can.",
        "To recover deleted files, stop using the card and do not run the test.",
        "Imager writes only to removable / USB / SD disks. Your system disk is always refused.",
    ]),
]


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
  $out.IsSystem=$d.IsSystem; $out.IsBoot=$d.IsBoot
  $out.Letters=@(Get-Partition -DiskNumber $d.Number | Where-Object { $_.DriveLetter } | ForEach-Object { "$($_.DriveLetter)" })
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
            self.is_dev = src.startswith("\\\\.\\")
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


def image_card(src, dest, log=print, progress=None, stop=None, whole_disk=False):
    """Make a sector-by-sector copy of the card (bad areas are zero-filled).
    whole_disk=True copies the entire physical disk (all partitions, like a Raspberry Pi image)."""
    stop = stop or threading.Event()
    progress = progress or (lambda f, s: None)
    letters = [src[:1].upper()] if IS_WIN and len(src) >= 2 and src[1] == ":" else []
    if whole_disk and IS_WIN and letters:
        d = resolve_disk(letters[0])
        letters = d["letters"]
        src = d["path"]
        log(f"Reading whole disk {d['number']} ({fmt_size(d['size'])}), volumes: {', '.join(letters)}")
    if IS_WIN and os.path.splitdrive(os.path.abspath(dest))[0][:1].upper() in letters:
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
# DISK IMAGER  (read / write / verify / hash raw images, like Win32 Disk Imager)
# ----------------------------------------------------------------------------
SAFE_BUS = ("USB", "SD", "MMC")


def hash_file(path, progress=None, stop=None):
    """MD5, SHA-1 and SHA-256 of a file in one pass."""
    hs = {"MD5": hashlib.md5(), "SHA1": hashlib.sha1(), "SHA256": hashlib.sha256()}
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as f:
        while True:
            if stop is not None and stop.is_set():
                raise Stopped()
            b = f.read(4 * MB)
            if not b:
                break
            for h in hs.values():
                h.update(b)
            done += len(b)
            if progress:
                progress(done / max(1, total), "Hashing")
    return {k: v.hexdigest() for k, v in hs.items()}


def resolve_disk(letter):
    """Windows: drive letter -> physical disk details with safety verdict."""
    letter = letter.strip().rstrip("\\/:").upper()
    if not (IS_WIN and len(letter) == 1 and letter.isalpha()):
        raise ValueError("Pick a drive letter such as E:")
    w = get_card_info(letter + ":\\").get("wmi") or {}
    if w.get("DiskNumber") is None:
        raise RuntimeError("Could not identify the physical disk behind " + letter + ":")
    letters = w.get("Letters") or []
    if isinstance(letters, str):
        letters = [letters]
    d = {
        "number": int(w["DiskNumber"]),
        "path": "\\\\.\\PhysicalDrive%d" % int(w["DiskNumber"]),
        "letters": [x.upper() for x in letters] or [letter],
        "bus": str(w.get("BusType", "")),
        "size": w.get("DiskSize"),
        "model": w.get("Model") or w.get("FriendlyName") or "",
        "system": bool(w.get("IsSystem")) or bool(w.get("IsBoot")),
    }
    d["safe"] = d["bus"].upper() in SAFE_BUS and not d["system"]
    return d


class LockedDisk:
    """Windows: lock + dismount every volume on a disk so raw writes are allowed."""

    def __init__(self, letters):
        self.letters = letters
        self.fds = []

    def __enter__(self):
        if not IS_WIN:
            return self
        import ctypes
        import msvcrt
        for L in self.letters:
            try:
                fd = os.open("\\\\.\\%s:" % L, os.O_RDWR | os.O_BINARY)
            except OSError as e:
                raise RuntimeError(f"Cannot open {L}: for locking ({e}). Run as administrator.")
            self.fds.append(fd)
            h = msvcrt.get_osfhandle(fd)
            ret = ctypes.c_ulong(0)
            k = ctypes.windll.kernel32
            if not k.DeviceIoControl(h, 0x00090018, None, 0, None, 0, ctypes.byref(ret), None):
                raise RuntimeError(f"Could not lock {L}: - close Explorer windows and programs using it.")
            k.DeviceIoControl(h, 0x00090020, None, 0, None, 0, ctypes.byref(ret), None)  # dismount
        return self

    def __exit__(self, *a):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass


def _refresh_partitions(f):
    if not IS_WIN:
        return
    try:
        import ctypes
        import msvcrt
        ret = ctypes.c_ulong(0)
        ctypes.windll.kernel32.DeviceIoControl(msvcrt.get_osfhandle(f.fileno()), 0x70140,
                                               None, 0, None, 0, ctypes.byref(ret), None)
    except Exception:
        pass


def write_image(img, target, letters=(), verify=True, log=print, progress=None, stop=None):
    """Write a raw image file onto target (\\\\.\\PhysicalDriveN, or a file for testing)."""
    stop = stop or threading.Event()
    progress = progress or (lambda f, s: None)
    size = os.path.getsize(img)
    if size == 0:
        raise ValueError("Image file is empty.")
    rd = RawReader(target)
    dev_size = rd.size
    rd.close()
    if size > dev_size:
        raise ValueError(f"Image ({fmt_size(size)}) is larger than the target ({fmt_size(dev_size)}). Nothing written.")
    log(f"Writing {fmt_size(size)} to {target} ...")
    src_hash = hashlib.sha256()
    t0 = time.time()
    locked = LockedDisk(list(letters)) if (IS_WIN and letters) else None
    if locked:
        locked.__enter__()
    try:
        with open(img, "rb") as fi, open(target, "r+b", buffering=0) as fo:
            done = 0
            while done < size:
                if stop.is_set():
                    raise Stopped()
                b = fi.read(min(4 * MB, size - done))
                if not b:
                    break
                src_hash.update(b)
                pad = (-len(b)) % ALIGN
                fo.write(b + b"\0" * pad)
                done += len(b)
                progress(done / size * (0.5 if verify else 1.0), "Writing")
            try:
                fo.flush()
                os.fsync(fo.fileno())
            except OSError:
                pass
            _refresh_partitions(fo)
    finally:
        if locked:
            locked.__exit__()
    mbps = size / 1e6 / max(0.001, time.time() - t0)
    log(f"Write finished: {fmt_size(size)} at {mbps:.1f} MB/s.")
    if verify:
        ok = verify_image(img, target, log=log,
                          progress=lambda f, s: progress(0.5 + f * 0.5, "Verifying"), stop=stop)
        return ok
    return True


def verify_image(img, target, log=print, progress=None, stop=None):
    """Compare an image file with the start of target. Returns True when identical."""
    stop = stop or threading.Event()
    size = os.path.getsize(img)
    rd = RawReader(target)
    bad_at = None
    try:
        with open(img, "rb") as fi:
            done = 0
            while done < size:
                if stop.is_set():
                    raise Stopped()
                n = min(4 * MB, size - done)
                a = fi.read(n)
                b = rd.read_at(done, n)
                if a != b:
                    for i in range(0, len(a), 512):
                        if a[i:i + 512] != b[i:i + 512]:
                            bad_at = done + i
                            break
                    break
                done += n
                if progress:
                    progress(done / size, "Verifying")
    finally:
        rd.close()
    if bad_at is None:
        log("VERIFY OK: the card matches the image exactly.")
        return True
    log(f"VERIFY FAILED: first difference at byte {bad_at} (sector {bad_at // 512}). "
        "The card may be faulty or fake - run the Test tab.")
    return False


PS_DEVICES = r"""
$ErrorActionPreference='SilentlyContinue'
$res=@()
foreach($d in (Get-Disk)){
  $vols=@()
  foreach($p in (Get-Partition -DiskNumber $d.Number | Where-Object { $_.DriveLetter })){
    $v=Get-Volume -DriveLetter $p.DriveLetter
    $vols+=[pscustomobject]@{Letter="$($p.DriveLetter)";Label=$v.FileSystemLabel;FS=$v.FileSystem;Size=$v.Size;Free=$v.SizeRemaining}
  }
  $res+=[pscustomobject]@{Number=$d.Number;Name=$d.FriendlyName;Bus="$($d.BusType)";Size=$d.Size;Style="$($d.PartitionStyle)";Health="$($d.HealthStatus)";System=[bool]($d.IsSystem -or $d.IsBoot);Volumes=$vols}
}
ConvertTo-Json -InputObject $res -Depth 4 -Compress
"""


def list_devices():
    """All physical disks with their volumes (Windows). Test hook: SDCC_FAKE_DEVICES=<json>."""
    fake = os.environ.get("SDCC_FAKE_DEVICES")
    if fake:
        return json.loads(fake)
    if not IS_WIN:
        return []
    raw = subprocess.run(["powershell", "-NoProfile", "-Command", PS_DEVICES], capture_output=True,
                         text=True, timeout=90, creationflags=hidden_flags()).stdout
    data = json.loads(raw) if raw.strip() else []
    if isinstance(data, dict):
        data = [data]
    for d in data:
        v = d.get("Volumes") or []
        d["Volumes"] = [v] if isinstance(v, dict) else v
    return data


def hide_own_console():
    """Double-clicking a .py opens a console window; hide it if it belongs only to us."""
    if not IS_WIN:
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        hwnd = k.GetConsoleWindow()
        if hwnd and k.GetConsoleProcessList((ctypes.c_uint * 4)(), 4) <= 1:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".2pctsdinfo.json")


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass


THEMES = {
    "Light": None,
    "Black": {"bg": "#000000", "fg": "#e8e8e8", "field": "#0e0e0e", "btn": "#1a1a1a", "btn_hi": "#2b2b2b",
              "accent": "#3b82c4", "warn": "#ff7b72", "ok": "#5fd47f", "dim": "#8a8a8a", "border": "#333333"},
    "Gray": {"bg": "#5b5b5b", "fg": "#ffffff", "field": "#6a6a6a", "btn": "#777777", "btn_hi": "#888888",
             "accent": "#3f6f9f", "warn": "#ffc2bb", "ok": "#c4f5c4", "dim": "#d6d6d6", "border": "#8f8f8f"},
    "Crimson Eclipse": {"bg": "#0a0a0a", "fg": "#f2e9e9", "field": "#160c0c", "btn": "#2a0d0d", "btn_hi": "#4d1313",
                        "accent": "#d0021b", "warn": "#ff4d4d", "ok": "#ffd166", "dim": "#a77a7a", "border": "#5c1616"},
    "Deep Ocean": {"bg": "#0b1e2d", "fg": "#dff3ff", "field": "#102a3d", "btn": "#16405a", "btn_hi": "#1f5a7d",
                   "accent": "#00a8cc", "warn": "#ff8fa3", "ok": "#7be0b0", "dim": "#7fa8c0", "border": "#1e4a66"},
    "Violet Haze": {"bg": "#1a1230", "fg": "#f0e9ff", "field": "#241a42", "btn": "#3a2a6b", "btn_hi": "#4e3a8c",
                    "accent": "#9b5de5", "warn": "#ff7aa8", "ok": "#8ef0c0", "dim": "#a99bd0", "border": "#4a3a80"},
}
LEGACY_THEMES = {"Dark": "Black", "Dark Gray": "Gray"}      # names used by v1.3 - v1.5


# ----------------------------------------------------------------------------
# PARTITION MANAGER  (format / create / delete / resize / label / letter / initialize / clean / wipe / eject)
# ----------------------------------------------------------------------------
GiB = 1024 ** 3
FAT32_WINDOWS_MAX = 32 * GiB          # Windows refuses to format FAT32 volumes larger than this
LABEL_MAX = {"FAT32": 11, "EXFAT": 15, "NTFS": 32}


def run_ps(script, timeout=900, sta=False):
    """Run PowerShell, raise RuntimeError with the real message on failure."""
    wrapped = ("$ErrorActionPreference='Stop'; try { " + script +
               " } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }")
    cmd = ["powershell", "-NoProfile", "-NonInteractive"] + (["-STA"] if sta else []) + ["-Command", wrapped]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=hidden_flags())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "PowerShell command failed").strip())
    return (r.stdout or "").strip()


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def clean_label(label, fs):
    fs = fs.upper()
    label = (label or "").strip()
    if fs in ("FAT32", "FAT"):
        label = "".join(ch for ch in label.upper() if ch not in '"*+,./:;<=>?[\\]|')
    else:
        label = "".join(ch for ch in label if ch not in '"*/:<>?\\|')
    return label[:LABEL_MAX.get(fs, 32)]


PS_PARTS = r"""
$n={N}
$d=Get-Disk -Number $n
$out=@()
foreach($p in (Get-Partition -DiskNumber $n)){
  $v=$null; if($p.DriveLetter){ $v=Get-Volume -DriveLetter $p.DriveLetter }
  $out+=[pscustomobject]@{Number=$p.PartitionNumber;Offset=$p.Offset;Size=$p.Size;Letter="$($p.DriveLetter)";Type="$($p.Type)";Active=[bool]$p.IsActive;Label=$v.FileSystemLabel;FS=$v.FileSystem;Free=$v.SizeRemaining}
}
$res=[pscustomobject]@{Number=$n;Style="$($d.PartitionStyle)";Size=$d.Size;Offline=[bool]$d.IsOffline;ReadOnly=[bool]$d.IsReadOnly;Sector=$d.LogicalSectorSize;Partitions=$out}
ConvertTo-Json -InputObject $res -Depth 4 -Compress
"""


def list_partitions(number):
    """Partition table of one disk plus the unallocated gaps ('segments')."""
    fake = os.environ.get("SDCC_FAKE_PARTS")
    if fake:
        info = json.loads(fake)[str(number)]
    else:
        info = json.loads(run_ps(PS_PARTS.replace("{N}", str(int(number))), timeout=120))
    parts = info.get("Partitions") or []
    if isinstance(parts, dict):
        parts = [parts]
    parts = sorted(parts, key=lambda p: p.get("Offset") or 0)
    info["Partitions"] = parts
    info["Sector"] = info.get("Sector") or 512
    size = info.get("Size") or 0
    segs, pos = [], 1024 * 1024 if parts else 0
    tail = size - (1024 * 1024 if str(info.get("Style")).upper() == "GPT" else 0)
    for p in parts:
        off, ln = p.get("Offset") or 0, p.get("Size") or 0
        if off - pos >= 4 * 1024 * 1024:
            segs.append({"kind": "free", "offset": pos, "size": off - pos})
        segs.append({"kind": "part", "offset": off, "size": ln, "part": p})
        pos = max(pos, off + ln)
    if not parts and size:
        segs.append({"kind": "free", "offset": 1024 * 1024 if size > 2 * 1024 * 1024 else 0, "size": size - 1024 * 1024})
    elif tail - pos >= 4 * 1024 * 1024:
        segs.append({"kind": "free", "offset": pos, "size": tail - pos})
    info["Segments"] = segs
    return info


# ---- our own FAT32 formatter (Windows refuses FAT32 above 32 GB) ---------------
def fat32_geometry(total_sectors, bps=512, spc=None):
    size = total_sectors * bps
    if spc is None:
        spc = 1 if size <= 260 * MB else 8 if size <= 8 * GiB else 16 if size <= 16 * GiB else 32 if size <= 32 * GiB else 64
    rsvd, nfats = 32, 2
    while True:
        tmp1 = total_sectors - rsvd
        tmp2 = (256 * spc + nfats) // 2
        fatsz = (tmp1 + tmp2 - 1) // tmp2
        clusters = (total_sectors - rsvd - nfats * fatsz) // spc
        if clusters < 65525 and spc > 1:
            spc //= 2                                   # too few clusters for FAT32: use smaller clusters
            continue
        break
    if clusters < 65525:
        raise ValueError("Volume too small for FAT32 (needs at least ~33 MB).")
    if clusters > 0x0FFFFFF5:
        raise ValueError("Volume too large for these cluster settings; choose a bigger cluster size.")
    return {"spc": spc, "rsvd": rsvd, "nfats": nfats, "fatsz": fatsz, "clusters": clusters, "bps": bps}


def format_fat32(target, size_bytes, label="", cluster_bytes=None, hidden_sectors=0, bps=512,
                 log=print, progress=None, stop=None):
    """Quick-format `target` (volume handle path or a file) as FAT32. Offsets are partition-relative."""
    progress = progress or (lambda f, s: None)
    total = size_bytes // bps
    spc = (cluster_bytes // bps) if cluster_bytes else None
    g = fat32_geometry(total, bps, spc)
    spc, rsvd, nfats, fatsz = g["spc"], g["rsvd"], g["nfats"], g["fatsz"]
    lab = (clean_label(label, "FAT32") or "NO NAME").ljust(11)[:11].encode("ascii", "replace")
    vol_id = random.getrandbits(32)

    bs = bytearray(bps)
    bs[0:3] = b"\xEB\x58\x90"
    bs[3:11] = b"MSWIN4.1"
    struct.pack_into("<HBHBHHBHHHII", bs, 11, bps, spc, rsvd, nfats, 0, 0, 0xF8, 0, 63, 255, hidden_sectors & 0xFFFFFFFF, total)
    struct.pack_into("<IHHIHH", bs, 36, fatsz, 0, 0, 2, 1, 6)
    bs[64] = 0x80
    bs[66] = 0x29
    struct.pack_into("<I", bs, 67, vol_id)
    bs[71:82] = lab
    bs[82:90] = b"FAT32   "
    bs[510:512] = b"\x55\xAA"

    fsinfo = bytearray(bps)
    struct.pack_into("<I", fsinfo, 0, 0x41615252)
    struct.pack_into("<I", fsinfo, 484, 0x61417272)
    struct.pack_into("<II", fsinfo, 488, g["clusters"] - 1, 3)
    fsinfo[510:512] = b"\x55\xAA"
    sec2 = bytearray(bps)
    sec2[510:512] = b"\x55\xAA"

    fat0 = bytearray(bps)
    struct.pack_into("<III", fat0, 0, 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFFF)
    root = bytearray(spc * bps)
    if label.strip():
        root[0:11] = lab
        root[11] = 0x08

    zero_sectors = rsvd + nfats * fatsz + spc
    with open(target, "r+b", buffering=0) as f:
        z = bytes(4 * MB)
        left, pos = zero_sectors * bps, 0
        while left > 0:
            if stop is not None and stop.is_set():
                raise Stopped()
            n = min(len(z), left)
            n -= n % bps or 0
            n = max(n, bps)
            f.seek(pos)
            f.write(z[:n])
            pos += n
            left -= n
            progress(min(1.0, pos / (zero_sectors * bps)), "Formatting")
        for sec, data in ((0, bs), (1, fsinfo), (2, sec2), (6, bs), (7, fsinfo), (8, sec2),
                          (rsvd, fat0), (rsvd + fatsz, fat0), (rsvd + nfats * fatsz, root)):
            f.seek(sec * bps)
            f.write(bytes(data))
        try:
            f.flush()
            os.fsync(f.fileno())
        except OSError:
            pass
    log(f"FAT32 written: {fmt_size(size_bytes)}, cluster {fmt_size(spc * bps)}, "
        f"{g['clusters']} clusters, FAT {fmt_size(fatsz * bps)} x{nfats}.")
    return g


def wipe_disk(path, letters=(), log=print, progress=None, stop=None):
    """Overwrite an entire physical disk with zeros (all data and partition tables)."""
    stop = stop or threading.Event()
    progress = progress or (lambda f, s: None)
    rd = RawReader(path)
    size = rd.size
    rd.close()
    locked = LockedDisk(list(letters)) if (IS_WIN and letters) else None
    if locked:
        locked.__enter__()
    t0 = time.time()
    try:
        with open(path, "r+b", buffering=0) as f:
            z = bytes(4 * MB)
            pos = 0
            while pos < size:
                if stop.is_set():
                    raise Stopped()
                n = min(len(z), size - pos)
                f.seek(pos)
                f.write(z[:n])
                pos += n
                progress(pos / size, "Wiping")
            _refresh_partitions(f)
    finally:
        if locked:
            locked.__exit__()
    log(f"Zero-filled {fmt_size(size)} in {time.time() - t0:.0f} s.")


def assign_letter(disk, part):
    return run_ps(
        "Add-PartitionAccessPath -DiskNumber %d -PartitionNumber %d -AssignDriveLetter; "
        "(Get-Partition -DiskNumber %d -PartitionNumber %d).DriveLetter" % (disk, part, disk, part)).strip()[:1]


def op_format(disk, part, fs, label, cluster=None, quick=True, log=print, progress=None, stop=None):
    """Format partition `part` (dict from list_partitions) with FAT32 / exFAT / NTFS."""
    fs = fs.upper()
    label = clean_label(label, fs)
    letter = (part.get("Letter") or "").strip() or assign_letter(disk, part["Number"])
    if not letter:
        raise RuntimeError("Could not give the partition a drive letter.")
    size = part.get("Size") or 0
    if fs == "FAT32" and size > FAT32_WINDOWS_MAX:
        log(f"{fmt_size(size)} is above Windows' 32 GB FAT32 limit: using the built-in FAT32 formatter.")
        with LockedDisk([letter]):
            format_fat32("\\\\.\\%s:" % letter, size, label, cluster, (part.get("Offset") or 0) // 512,
                         log=log, progress=progress, stop=stop)
        try:
            run_ps("Set-Partition -DiskNumber %d -PartitionNumber %d -MbrType FAT32" % (disk, part["Number"]))
        except RuntimeError:
            pass                                       # GPT disks have no MBR type; harmless
    else:
        cmd = "Format-Volume -DriveLetter %s -FileSystem %s -NewFileSystemLabel %s -Force" % (letter, fs, ps_quote(label))
        if cluster:
            cmd += " -AllocationUnitSize %d" % cluster
        if not quick:
            cmd += " -Full"
        log("Formatting with Windows (%s, %s)..." % (fs, "full" if not quick else "quick"))
        run_ps(cmd)
    return letter


def op_delete(disk, part):
    run_ps("Remove-Partition -DiskNumber %d -PartitionNumber %d -Confirm:$false" % (disk, part["Number"]))


def op_create(disk, offset, size, fs, label, cluster=None, quick=True, log=print, progress=None, stop=None):
    out = run_ps("$p=New-Partition -DiskNumber %d -Offset %d -Size %d -AssignDriveLetter; "
                 "Start-Sleep -Seconds 2; \"$($p.PartitionNumber) $($p.DriveLetter)\"" % (disk, offset, size))
    num, _, letter = out.partition(" ")
    part = {"Number": int(num), "Letter": letter.strip(), "Size": size, "Offset": offset}
    log(f"Partition {num} created ({fmt_size(size)}). Formatting as {fs}...")
    return op_format(disk, part, fs, label, cluster, quick, log, progress, stop)


def op_resize(disk, part, new_size):
    run_ps("Resize-Partition -DiskNumber %d -PartitionNumber %d -Size %d" % (disk, part["Number"], new_size))


def supported_size(disk, part):
    out = run_ps("$s=Get-PartitionSupportedSize -DiskNumber %d -PartitionNumber %d; \"$($s.SizeMin) $($s.SizeMax)\"" % (disk, part["Number"]))
    a, b = out.split()
    return int(a), int(b)


def op_label(letter, label, fs):
    run_ps("Set-Volume -DriveLetter %s -NewFileSystemLabel %s" % (letter, ps_quote(clean_label(label, fs or "NTFS"))))


def op_letter(disk, part, new_letter):
    run_ps("Set-Partition -DiskNumber %d -PartitionNumber %d -NewDriveLetter %s" % (disk, part["Number"], new_letter))


def op_initialize(disk, style):
    run_ps("Initialize-Disk -Number %d -PartitionStyle %s" % (disk, style))


def op_clean(disk):
    run_ps("Clear-Disk -Number %d -RemoveData -RemoveOEM -Confirm:$false" % disk)


def eject_disk(number, letters, log=print):
    """Safely remove a removable disk: shell eject for each volume, then fall back to taking it offline."""
    letters = [l.upper() for l in letters]
    for L in letters:
        try:
            run_ps("$it=(New-Object -ComObject Shell.Application).Namespace(17).ParseName('%s:'); "
                   "if(-not $it){ throw 'Drive %s: not found' }; $it.InvokeVerb('Eject')" % (L, L), sta=True, timeout=60)
        except RuntimeError as e:
            log(f"  shell eject of {L}: failed ({e})")
    for _ in range(14):
        time.sleep(0.5)
        left = [L for L in letters if os.path.exists(L + ":\\")]
        if not left:
            log("Ejected. It is now safe to unplug the device.")
            return True
    log("Shell eject did not release the drive; taking the disk offline instead...")
    try:
        run_ps("Set-Disk -Number %d -IsOffline $true" % number)
        log("Disk is offline. It is now safe to unplug the device.")
        return True
    except RuntimeError as e:
        raise RuntimeError("Could not eject: something is still using the drive. Close Explorer windows, "
                           "backup tools and anything reading it, then try again. (%s)" % e)


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
            f.write(f"{APP_TITLE} report - {datetime.now():%Y-%m-%d %H:%M}\n\n")
            f.write("\n".join(out + rl) + "\n")
        print(f"Report saved to {args.report}")


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("1300x780")
    root.minsize(980, 600)
    main = ttk.PanedWindow(root, orient="horizontal")
    main.pack(fill="both", expand=True)
    left = ttk.Frame(main)
    right = ttk.Frame(main, width=380)
    main.add(left, weight=3)
    main.add(right, weight=1)
    nb = ttk.Notebook(left)
    nb.pack(fill="both", expand=True)
    tab = ttk.Frame(nb)
    rtab = ttk.Frame(nb)
    itab = ttk.Frame(nb)
    ptab = ttk.Frame(nb)
    atab = ttk.Frame(nb)
    nb.add(tab, text="  Test & Info  ")
    nb.add(rtab, text="  Recover deleted files  ")
    nb.add(itab, text="  Disk Imager  ")
    nb.add(ptab, text="  Partitions  ")
    nb.add(atab, text="  About  ")
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

    ttk.Button(top, text="Refresh", command=lambda: refresh()).grid(row=0, column=2)
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

    btns = ttk.Frame(tab, padding=8)
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
            messagebox.showwarning(APP_NAME, "Select a drive first.")
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
            messagebox.showwarning(APP_NAME, "Select a drive first.")
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
            messagebox.showinfo(APP_NAME, "Nothing to save yet.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".txt",
                                         initialfile=f"2pctSDinfo_{APP_TAG}_Report_{datetime.now():%Y%m%d_%H%M}.txt")
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f"{APP_TITLE} report - {datetime.now():%Y-%m-%d %H:%M}\n\n{state['report']}\n")

    ttk.Button(btns, text="Card info only", command=show_info).pack(side="left")
    start_btn = ttk.Button(btns, text="Start test", command=start)
    start_btn.pack(side="left", padx=6)
    stop_btn = ttk.Button(btns, text="Stop", command=stop_evt.set, state="disabled")
    stop_btn.pack(side="left")
    ttk.Button(btns, text="Save report...", command=save).pack(side="left", padx=6)


    # ---------------- Recovery tab ----------------
    warn = tk.Label(rtab, justify="left", fg="#b00020", wraplength=760, anchor="w",
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
    for i_, g in enumerate(GROUPS):
        ttk.Checkbutton(gf, text=labels_g[g], variable=gv[g]).grid(row=i_ // 2, column=i_ % 2, sticky="w", padx=4, pady=1)
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


    # ---------------- Disk Imager tab ----------------
    iwarn = tk.Label(itab, justify="left", fg="#b00020", wraplength=760, anchor="w",
                     text="WRITE ERASES THE WHOLE CARD. Only removable / USB / SD disks are allowed; your system "
                          "drive is blocked. Needs 'Yes' on the administrator prompt. Close Explorer windows on the card first.")
    iwarn.pack(fill="x", padx=8, pady=6)
    imf = ttk.Frame(itab, padding=8)
    imf.pack(fill="x")
    ttk.Label(imf, text="Image file:").grid(row=0, column=0, sticky="w")
    imgvar = tk.StringVar()
    ttk.Entry(imf, textvariable=imgvar, width=58).grid(row=0, column=1, padx=6, pady=2)

    def pick_open():
        f = filedialog.askopenfilename(title="Image to write / verify / hash",
                                       filetypes=[("Disk images", "*.img *.iso *.bin *.dd"), ("All files", "*.*")])
        if f:
            imgvar.set(f)

    def pick_save():
        f = filedialog.asksaveasfilename(title="Save image as", defaultextension=".img",
                                         initialfile="card_backup.img")
        if f:
            imgvar.set(f)

    ttk.Button(imf, text="Open...", command=pick_open).grid(row=0, column=2)
    ttk.Button(imf, text="Save as...", command=pick_save).grid(row=0, column=3, padx=4)
    ttk.Label(imf, text="Device:").grid(row=1, column=0, sticky="w")
    icombo = ttk.Combobox(imf, values=[d[1] for d in drives], width=55, state="readonly")
    if drives:
        icombo.current(0)
    icombo.grid(row=1, column=1, padx=6, pady=2)

    ttk.Button(imf, text="Refresh", command=lambda: refresh()).grid(row=1, column=2)
    whole_var = tk.BooleanVar(value=True)
    verify_var = tk.BooleanVar(value=True)
    of = ttk.Frame(itab, padding=(8, 0))
    of.pack(fill="x")
    ttk.Checkbutton(of, text="Read whole disk (all partitions, e.g. a Raspberry Pi card)", variable=whole_var).pack(side="left")
    ttk.Checkbutton(of, text="Verify after write", variable=verify_var).pack(side="left", padx=12)
    ib = ttk.Frame(itab, padding=8)
    ib.pack(fill="x")
    ipb = ttk.Progressbar(itab, maximum=100)
    ipb.pack(fill="x", padx=8)
    istatus = ttk.Label(itab, text="Idle")
    istatus.pack(anchor="w", padx=8)
    itxt = tk.Text(itab, font=("Consolas", 10), wrap="none")
    itxt.pack(fill="both", expand=True, padx=8, pady=8)
    iq = queue.Queue()
    istop = threading.Event()
    istate = {"running": False}

    def idev():
        sel = icombo.get().strip()
        for d in drives:
            if d[1] == sel:
                return d[0]
        return None

    def ilog(m):
        itxt.insert("end", m + "\n")
        itxt.see("end")

    def ibusy(b):
        istate["running"] = b
        for w_ in (ibtn_read, ibtn_write, ibtn_verify, ibtn_hash):
            w_.config(state="disabled" if b else "normal")
        istop_btn.config(state="normal" if b else "disabled")

    def istart(kind):
        if istate["running"]:
            return
        img = imgvar.get().strip()
        dev = idev()
        if kind in ("write", "verify", "hash") and not os.path.isfile(img):
            messagebox.showwarning("Disk Imager", "Choose an existing image file first.")
            return
        if kind in ("read", "write", "verify") and not dev:
            messagebox.showwarning("Disk Imager", "Select a device first.")
            return
        if kind == "read" and not img:
            messagebox.showwarning("Disk Imager", "Choose where to save the image (Save as...).")
            return
        info = None
        if kind in ("write", "verify"):
            try:
                info = resolve_disk(dev[:1])
            except Exception as e:
                messagebox.showerror("Disk Imager", str(e))
                return
        if kind == "write":
            if not info["safe"]:
                messagebox.showerror("Disk Imager", f"Refusing: disk {info['number']} is not a removable/USB/SD "
                                     f"disk (bus: {info['bus']}, system disk: {info['system']}).")
                return
            if os.path.getsize(img) > (info["size"] or 0):
                messagebox.showerror("Disk Imager", "The image is larger than the card. Nothing was written.")
                return
            ans = simpledialog.askstring(
                "Confirm WRITE",
                f"ALL DATA on disk {info['number']} will be destroyed:\n"
                f"  {info['model']}  {fmt_size(info['size'])}  volumes {', '.join(info['letters'])}\n\n"
                f"Type the drive letter ({dev[0]}) to confirm:")
            if not ans or ans.strip().upper().rstrip(":") != dev[0].upper():
                return
        itxt.delete("1.0", "end")
        istop.clear()
        ibusy(True)

        def work():
            lg = lambda m: iq.put(("log", m))
            pg = lambda f, s_: iq.put(("prog", (f, s_)))
            try:
                if kind == "read":
                    image_card(dev, img, lg, pg, istop, whole_disk=whole_var.get())
                elif kind == "write":
                    r = write_image(img, info["path"], info["letters"], verify_var.get(), lg, pg, istop)
                    lg("DONE: image written." + ("" if verify_var.get() else " (not verified)") if r else
                       "Finished with errors.")
                elif kind == "verify":
                    verify_image(img, info["path"], lg, pg, istop)
                else:
                    lg("Hashing " + img)
                    for k, v in hash_file(img, pg, istop).items():
                        lg(f"{k:7s}: {v}")
            except Stopped:
                lg("Stopped by user.")
            except Exception as e:
                lg(f"ERROR: {e}")
            iq.put(("done", None))

        threading.Thread(target=work, daemon=True).start()

    def ipoll():
        try:
            while True:
                k, v = iq.get_nowait()
                if k == "log":
                    ilog(v)
                elif k == "prog":
                    ipb["value"] = v[0] * 100
                    istatus.config(text=f"{v[1]}... {v[0] * 100:.0f}%")
                else:
                    ibusy(False)
                    istatus.config(text="Finished")
        except queue.Empty:
            pass
        root.after(150, ipoll)

    ibtn_read = ttk.Button(ib, text="Read card to image", command=lambda: istart("read"))
    ibtn_read.pack(side="left")
    ibtn_write = ttk.Button(ib, text="Write image to card", command=lambda: istart("write"))
    ibtn_write.pack(side="left", padx=6)
    ibtn_verify = ttk.Button(ib, text="Verify", command=lambda: istart("verify"))
    ibtn_verify.pack(side="left")
    ibtn_hash = ttk.Button(ib, text="Hash image", command=lambda: istart("hash"))
    ibtn_hash.pack(side="left", padx=6)
    istop_btn = ttk.Button(ib, text="Stop", command=istop.set, state="disabled")
    istop_btn.pack(side="left")
    ipoll()


    # ---------------- About tab ----------------
    ah = ttk.Frame(atab, padding=(12, 12, 12, 0))
    ah.pack(fill="x")
    ttk.Label(ah, text=APP_NAME, font=("Segoe UI", 22, "bold")).pack(side="left")
    ttk.Label(ah, text="  " + APP_TAG, font=("Segoe UI", 16)).pack(side="left", pady=(8, 0))
    ttk.Label(atab, text=APP_TAGLINE, padding=(12, 0)).pack(anchor="w")

    def sysinfo():
        import platform
        rows = [
            ("Version", f"{APP_TAG}  (released {CHANGELOG[0][1]})"),
            ("Python", f"{platform.python_version()}  ({platform.architecture()[0]})"),
            ("Tk", str(tk.TkVersion)),
            ("Windows" if IS_WIN else "System", platform.platform()),
            ("Administrator", "yes" if is_admin() else "no (recovery and imager need it)"),
            ("Script", os.path.abspath(__file__)),
            ("Settings file", SETTINGS_FILE),
            ("Project", APP_REPO),
        ]
        return rows

    af = ttk.Frame(atab, padding=(12, 10))
    af.pack(fill="x")
    for r_, (k_, v_) in enumerate(sysinfo()):
        ttk.Label(af, text=k_ + ":", font=("Segoe UI", 9, "bold")).grid(row=r_, column=0, sticky="nw", padx=(0, 10), pady=1)
        ttk.Label(af, text=v_, wraplength=620, justify="left").grid(row=r_, column=1, sticky="w", pady=1)

    def copy_diag():
        lines = [f"{APP_TITLE}"] + [f"{k}: {v}" for k, v in sysinfo()]
        root.clipboard_clear()
        root.clipboard_append("\n".join(lines))
        astatus.config(text="Diagnostics copied to the clipboard.")

    def open_repo():
        import webbrowser
        webbrowser.open(APP_REPO)

    abtn = ttk.Frame(atab, padding=(12, 0))
    abtn.pack(fill="x")
    ttk.Button(abtn, text="Copy diagnostics", command=copy_diag).pack(side="left")
    ttk.Button(abtn, text="Open project page", command=open_repo).pack(side="left", padx=6)
    astatus = ttk.Label(abtn, text="")
    astatus.pack(side="left", padx=8)

    abox = ttk.Frame(atab)
    abox.pack(fill="both", expand=True, padx=12, pady=10)
    asb = ttk.Scrollbar(abox, orient="vertical")
    asb.pack(side="right", fill="y")
    atxt = tk.Text(abox, font=("Segoe UI", 10), wrap="word", height=10, relief="flat", cursor="arrow",
                   yscrollcommand=asb.set)
    atxt.pack(side="left", fill="both", expand=True)
    asb.config(command=atxt.yview)
    atxt.tag_configure("h", font=("Segoe UI", 12, "bold"), spacing1=8, spacing3=2)
    atxt.tag_configure("v", font=("Segoe UI", 10, "bold"), spacing1=6)
    atxt.insert("end", "Version history\n", "h")
    for ver, date, items in CHANGELOG:
        atxt.insert("end", f"v{ver}   {date}\n", "v")
        for it in items:
            atxt.insert("end", f"   • {it}\n")
    atxt.insert("end", "Recovery supports\n", "h")
    atxt.insert("end", "   " + ", ".join(k.upper() for k, *_ in TYPES) + "  (DOCX/XLSX/PPTX/APK detected inside ZIP, "
                "HEIC/MOV/3GP/M4A inside MP4)\n")
    for title_, lines_ in ABOUT_EXTRA:
        atxt.insert("end", title_ + "\n", "h")
        for ln_ in lines_:
            atxt.insert("end", f"   • {ln_}\n")
    atxt.config(state="disabled")

    # ---------------- Partitions tab (AOMEI-style) ----------------
    pstate = {"disk": None, "info": None, "sel": None, "busy": False}
    devcache = {"list": []}
    pq = queue.Queue()
    pstop = threading.Event()
    pal_cur = {"p": {}}

    ptop = ttk.Frame(ptab, padding=(8, 8, 8, 0))
    ptop.pack(fill="x")
    ttk.Label(ptop, text="Disk:").pack(side="left")
    pdisk = ttk.Combobox(ptop, state="readonly", width=50)
    pdisk.pack(side="left", padx=6)
    pinfo = ttk.Label(ptop, text="")
    pinfo.pack(side="left", padx=8)
    pbody = ttk.Frame(ptab)
    pbody.pack(fill="both", expand=True)
    side = ttk.Frame(pbody, padding=8)
    side.pack(side="left", fill="y")
    pmain = ttk.Frame(pbody, padding=(0, 8, 8, 8))
    pmain.pack(side="left", fill="both", expand=True)
    pcanvas = tk.Canvas(pmain, height=86, highlightthickness=0)
    pcanvas.pack(fill="x")
    ptree = ttk.Treeview(pmain, columns=("label", "fs", "cap", "free", "type", "start"), height=7, selectmode="browse")
    for c_, t_, w_ in (("#0", "Partition", 110), ("label", "Label", 110), ("fs", "File system", 80),
                       ("cap", "Capacity", 85), ("free", "Free", 85), ("type", "Type", 100), ("start", "Start", 85)):
        ptree.heading(c_, text=t_)
        ptree.column(c_, width=w_, stretch=(c_ == "#0"))
    ptree.pack(fill="x", pady=(8, 0))
    pprog = ttk.Progressbar(pmain, maximum=100)
    pprog.pack(fill="x", pady=(8, 0))
    pstatus = ttk.Label(pmain, text="Select a disk. Operations apply only to removable / USB / SD disks.")
    pstatus.pack(anchor="w")
    ptxt = tk.Text(pmain, font=("Consolas", 10), wrap="word", height=8)
    ptxt.pack(fill="both", expand=True, pady=(4, 0))

    def plog(m):
        ptxt.insert("end", m + "\n")
        ptxt.see("end")

    def disk_entry(n):
        for d in devcache["list"]:
            if d.get("Number") == n:
                return d
        return None

    def disk_safe(n):
        d = disk_entry(n)
        return bool(d) and str(d.get("Bus", "")).upper() in SAFE_BUS and not d.get("System")

    def disk_letters(n):
        d = disk_entry(n) or {}
        return [v.get("Letter") for v in (d.get("Volumes") or []) if v.get("Letter")]

    def sel_seg():
        i = pstate["sel"]
        segs = (pstate["info"] or {}).get("Segments") or []
        return segs[i] if i is not None and 0 <= i < len(segs) else None

    # --- map drawing
    def fs_color(fs, p):
        return {"FAT32": p.get("accent", "#3b82c4"), "EXFAT": "#7b61c4", "NTFS": "#2e8b8b",
                "FAT": "#c47b3b"}.get((fs or "").upper(), p.get("dim", "#888888"))

    def redraw_map(_e=None):
        c = pcanvas
        c.delete("all")
        p = pal_cur["p"] or pal_light
        c.configure(bg=p["bg"])
        info = pstate["info"]
        W = max(200, c.winfo_width())
        if not info or not info.get("Segments"):
            c.create_text(W // 2, 43, text="No disk loaded", fill=p.get("dim", "#888"))
            return
        total = max(1, info.get("Size") or 1)
        x = 4
        usable = W - 8
        MINW = 96
        widths = [max(MINW, usable * sg["size"] / total) for sg in info["Segments"]]
        over = sum(widths) - usable
        if over > 0:                                      # shrink the big blocks, keep small ones readable
            room = sum(w - MINW for w in widths)
            if room > 0:
                widths = [w - (w - MINW) / room * over if w > MINW else w for w in widths]
        for i, sg in enumerate(info["Segments"]):
            w_ = int(widths[i])
            if sg["kind"] == "free":
                fill, line = p["field"], p.get("border", "#555")
                title, sub = ("Unallocated" if w_ >= 120 else "Free"), fmt_size(sg["size"])
            else:
                pt = sg["part"]
                fill, line = fs_color(pt.get("FS"), p), p.get("border", "#555")
                title = (pt.get("Letter") + ":  " if pt.get("Letter") else "") + (pt.get("Label") or "")
                sub = "%s  %s" % (pt.get("FS") or "RAW", fmt_size(sg["size"]))
            sel = pstate["sel"] == i
            c.create_rectangle(x, 6, x + w_ - 3, 80, fill=fill, outline=p["accent"] if sel else line, width=3 if sel else 1)
            if sel:
                c.create_rectangle(x + 2, 8, x + w_ - 5, 78, outline=p["fg"], width=1, dash=(3, 3))
            fg = "#ffffff" if sg["kind"] == "part" else p["fg"]
            c.create_text(x + 8, 24, text=title.strip() or "Partition %s" % sg["part"].get("Number", ""), anchor="w", fill=fg,
                          font=("Segoe UI", 10, "bold"), width=max(30, w_ - 20))
            c.create_text(x + 8, 50, text=sub, anchor="w", fill=fg, font=("Segoe UI", 9), width=max(30, w_ - 20))
            sg["_x"] = (x, x + w_ - 3)
            x += w_

    def map_click(e):
        info = pstate["info"]
        if not info:
            return
        for i, sg in enumerate(info["Segments"]):
            a, b = sg.get("_x", (0, 0))
            if a <= e.x <= b:
                pstate["sel"] = i
                ptree.selection_set("s%d" % i)
                redraw_map()
                update_buttons()
                return

    pcanvas.bind("<Configure>", redraw_map)
    pcanvas.bind("<Button-1>", map_click)

    def tree_pick(_e=None):
        s_ = ptree.selection()
        if s_ and s_[0].startswith("s"):
            pstate["sel"] = int(s_[0][1:])
            redraw_map()
            update_buttons()

    ptree.bind("<<TreeviewSelect>>", tree_pick)

    def render():
        info = pstate["info"]
        ptree.delete(*ptree.get_children())
        if not info:
            redraw_map()
            return
        for i, sg in enumerate(info["Segments"]):
            if sg["kind"] == "free":
                ptree.insert("", "end", iid="s%d" % i, text="Unallocated", values=("", "", fmt_size(sg["size"]), "", "", fmt_size(sg["offset"])))
            else:
                pt = sg["part"]
                ptree.insert("", "end", iid="s%d" % i,
                             text="%s%s" % ((pt.get("Letter") + ":  ") if pt.get("Letter") else "", "Partition %s" % pt.get("Number")),
                             values=(pt.get("Label") or "", pt.get("FS") or "RAW", fmt_size(sg["size"]),
                                     fmt_size(pt.get("Free")) if pt.get("Free") is not None else "", pt.get("Type") or "",
                                     fmt_size(sg["offset"])))
        n = info.get("Number")
        safe = disk_safe(n)
        pinfo.config(text="%s  |  %s  |  %s  |  %s" % (fmt_size(info.get("Size")), info.get("Style"),
                                                      "Offline" if info.get("Offline") else "Online",
                                                      "SAFE TO MODIFY" if safe else "PROTECTED"))
        pstate["sel"] = None
        redraw_map()
        update_buttons()

    # --- loading
    def fill_disk_combo():
        vals = []
        for d in devcache["list"]:
            tag = "removable" if (str(d.get("Bus", "")).upper() in SAFE_BUS and not d.get("System")) else "protected"
            vals.append("Disk %s  %s  %s  %.1f GB  [%s]" % (d.get("Number"), d.get("Name") or "", d.get("Bus", ""),
                                                           (d.get("Size") or 0) / 1e9, tag))
        pdisk["values"] = vals
        cur = pstate["disk"]
        match = next((v for v in vals if cur is not None and v.startswith("Disk %s " % cur)), None)
        if match:
            pdisk.set(match)
            return
        if cur is not None:                               # the disk went away
            pstate["disk"], pstate["info"] = None, None
            pdisk.set("")
            render()
        if vals and not pstate["busy"]:
            i = next((k for k, v in enumerate(vals) if "[removable]" in v), 0)
            pdisk.current(i)
            pstate["disk"] = devcache["list"][i].get("Number")
            load_disk()

    def load_disk(_e=None):
        v = pdisk.get()
        if v.startswith("Disk "):
            pstate["disk"] = int(v.split()[1])
        n = pstate["disk"]
        if n is None:
            return
        pstatus.config(text="Reading partition table...")

        def work():
            try:
                pq.put(("loaded", list_partitions(n)))
            except Exception as e:
                pq.put(("log", "Could not read disk %s: %s" % (n, e)))
                pq.put(("loaded", None))

        threading.Thread(target=work, daemon=True).start()

    pdisk.bind("<<ComboboxSelected>>", load_disk)

    # --- dialogs
    def form(title, fields, ok_text="OK"):
        dlg = tk.Toplevel(root)
        dlg.title(title)
        dlg.transient(root)
        dlg.resizable(False, False)
        dlg.configure(bg=pal_cur["p"].get("bg", pal_light["bg"]))
        frm = ttk.Frame(dlg, padding=14)
        frm.pack()
        vars_ = {}
        for r_, f in enumerate(fields):
            kind = f[0]
            if kind == "note":
                ttk.Label(frm, text=f[1], wraplength=380, justify="left").grid(row=r_, column=0, columnspan=2, sticky="w", pady=(0, 6))
                continue
            key, label = f[1], f[2]
            if kind == "check":
                v = tk.BooleanVar(value=f[3])
                ttk.Checkbutton(frm, text=label, variable=v).grid(row=r_, column=0, columnspan=2, sticky="w", pady=3)
            else:
                ttk.Label(frm, text=label).grid(row=r_, column=0, sticky="w", pady=3, padx=(0, 10))
                if kind == "entry":
                    v = tk.StringVar(value=f[3])
                    ttk.Entry(frm, textvariable=v, width=27).grid(row=r_, column=1, sticky="w")
                else:
                    v = tk.StringVar(value=f[4])
                    ttk.Combobox(frm, textvariable=v, values=f[3], state="readonly", width=25).grid(row=r_, column=1, sticky="w")
            vars_[key] = v
        out = {}

        def ok():
            out.update({k: v.get() for k, v in vars_.items()})
            out["_ok"] = True
            dlg.destroy()

        bb = ttk.Frame(frm)
        bb.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bb, text=ok_text, command=ok).pack(side="left", padx=4)
        ttk.Button(bb, text="Cancel", command=dlg.destroy).pack(side="left")
        dlg.update_idletasks()
        dlg.geometry("+%d+%d" % (root.winfo_rootx() + 140, root.winfo_rooty() + 120))
        dlg.grab_set()
        root.wait_window(dlg)
        return out if out.get("_ok") else None

    def confirm_typed(what, expected):
        a = simpledialog.askstring(APP_NAME, "%s\n\nType  %s  to confirm:" % (what, expected), parent=root)
        return bool(a) and a.strip().upper().rstrip(":") == str(expected).upper()

    # --- running operations
    def run_op(title, fn):
        if pstate["busy"]:
            return
        pstate["busy"] = True
        pstop.clear()
        pprog["value"] = 0
        update_buttons()
        plog("=== %s ===" % title)

        def work():
            lg = lambda m: pq.put(("log", m))
            pg = lambda f, s_: pq.put(("prog", (f, s_)))
            try:
                res = fn(lg, pg)
                pq.put(("log", "DONE: %s" % (res or title)))
            except Stopped:
                pq.put(("log", "Stopped by user."))
            except Exception as e:
                pq.put(("log", "ERROR: %s" % e))
            pq.put(("done", None))

        threading.Thread(target=work, daemon=True).start()

    def ppoll():
        try:
            while True:
                k, v = pq.get_nowait()
                if k == "log":
                    plog(v)
                elif k == "prog":
                    pprog["value"] = v[0] * 100
                    pstatus.config(text="%s... %.0f%%" % (v[1], v[0] * 100))
                elif k == "loaded":
                    pstate["info"] = v
                    pstatus.config(text="Ready.")
                    render()
                elif k == "done":
                    pstate["busy"] = False
                    pprog["value"] = 0
                    pstatus.config(text="Finished.")
                    update_buttons()
                    load_disk()
                    dev_wake.set()
        except queue.Empty:
            pass
        root.after(150, ppoll)

    def cur_part():
        sg = sel_seg()
        return sg["part"] if sg and sg["kind"] == "part" else None

    def need_safe():
        n = pstate["disk"]
        if n is None or not disk_safe(n):
            messagebox.showerror(APP_NAME, "This disk is protected (system or internal). Only removable, USB and SD disks can be changed.")
            return None
        return n

    # --- commands
    def cmd_format():
        n, pt = need_safe(), cur_part()
        if n is None or not pt:
            return
        cur_fs = (pt.get("FS") or "").upper()
        big = (pt.get("Size") or 0) > FAT32_WINDOWS_MAX
        r = form("Format partition", [
            ("note", "Format erases ALL data on %s partition %s (%s). %s" % (
                (pt.get("Letter") + ":") if pt.get("Letter") else "", pt.get("Number"), fmt_size(pt.get("Size")),
                "FAT32 above 32 GB uses the built-in formatter (Windows refuses it)." if big else "")),
            ("combo", "fs", "File system:", ["FAT32", "exFAT", "NTFS"], {"FAT32": "FAT32", "EXFAT": "exFAT", "NTFS": "NTFS"}.get(cur_fs, "exFAT" if big else "FAT32")),
            ("entry", "label", "Label:", pt.get("Label") or ""),
            ("combo", "cluster", "Cluster size:", ["Default", "512", "1024", "2048", "4096", "8192", "16384", "32768", "65536"], "Default"),
            ("check", "quick", "Quick format", True)], "Format")
        if not r:
            return
        who = pt.get("Letter") or str(pt.get("Number"))
        if not confirm_typed("ALL DATA on partition %s will be destroyed." % who, who):
            return
        cl = None if r["cluster"] == "Default" else int(r["cluster"])
        run_op("Format %s as %s" % (who, r["fs"]),
               lambda lg, pg: "formatted %s:" % op_format(n, pt, r["fs"], r["label"], cl, r["quick"], lg, pg, pstop))

    def cmd_delete():
        n, pt = need_safe(), cur_part()
        if n is None or not pt:
            return
        who = pt.get("Letter") or str(pt.get("Number"))
        if not confirm_typed("Partition %s (%s) and ALL its data will be deleted." % (who, fmt_size(pt.get("Size"))), who):
            return
        run_op("Delete partition %s" % who, lambda lg, pg: op_delete(n, pt) or "partition deleted")

    def cmd_create():
        n, sg = need_safe(), sel_seg()
        if n is None or not sg or sg["kind"] != "free":
            return
        mx = sg["size"] // (1024 * 1024)
        r = form("Create partition", [
            ("note", "Unallocated space: %s" % fmt_size(sg["size"])),
            ("entry", "mb", "Size (MB):", str(mx - 2)),
            ("combo", "fs", "File system:", ["FAT32", "exFAT", "NTFS"], "exFAT" if sg["size"] > FAT32_WINDOWS_MAX else "FAT32"),
            ("entry", "label", "Label:", ""),
            ("combo", "cluster", "Cluster size:", ["Default", "4096", "8192", "16384", "32768", "65536"], "Default")], "Create")
        if not r:
            return
        try:
            size = int(float(r["mb"]) * 1024 * 1024)
        except ValueError:
            return messagebox.showerror(APP_NAME, "Size must be a number of megabytes.")
        if size < 33 * 1024 * 1024 or size > sg["size"]:
            return messagebox.showerror(APP_NAME, "Size must be between 33 MB and %d MB." % mx)
        cl = None if r["cluster"] == "Default" else int(r["cluster"])
        run_op("Create %s partition" % r["fs"],
               lambda lg, pg: "created %s:" % op_create(n, sg["offset"], size, r["fs"], r["label"], cl, True, lg, pg, pstop))

    def cmd_resize():
        n, pt = need_safe(), cur_part()
        if n is None or not pt:
            return
        if (pt.get("FS") or "").upper() != "NTFS":
            return messagebox.showinfo(APP_NAME, "Windows can only resize NTFS partitions.\n\nFor FAT32 / exFAT: back up, delete the partition, "
                                       "then create a new one with the size you want.")
        try:
            mn, mx = supported_size(n, pt)
        except Exception as e:
            return messagebox.showerror(APP_NAME, "Cannot resize: %s" % e)
        r = form("Resize partition", [("note", "Allowed size: %d MB to %d MB" % (mn // 1048576 + 1, mx // 1048576)),
                                      ("entry", "mb", "New size (MB):", str(mx // 1048576))], "Resize")
        if not r:
            return
        try:
            size = int(float(r["mb"]) * 1048576)
        except ValueError:
            return
        if size < mn or size > mx:
            return messagebox.showerror(APP_NAME, "Outside the allowed range.")
        run_op("Resize partition", lambda lg, pg: op_resize(n, pt, size) or "resized")

    def cmd_label():
        n, pt = need_safe(), cur_part()
        if n is None or not pt:
            return
        if not pt.get("Letter"):
            return messagebox.showinfo(APP_NAME, "This partition has no drive letter. Use Change Drive Letter first.")
        r = form("Change label", [("entry", "label", "New label:", pt.get("Label") or "")], "Apply")
        if r:
            run_op("Change label", lambda lg, pg: op_label(pt["Letter"], r["label"], pt.get("FS")) or "label changed")

    def cmd_letter():
        n, pt = need_safe(), cur_part()
        if n is None or not pt:
            return
        used = {l for d in devcache["list"] for l in [v.get("Letter") for v in (d.get("Volumes") or [])] if l}
        free = [c for c in "DEFGHIJKLMNOPQRSTUVWXYZ" if c not in used]
        r = form("Change drive letter", [("combo", "letter", "New letter:", free, free[0] if free else "")], "Apply")
        if r and r["letter"]:
            run_op("Change drive letter", lambda lg, pg: op_letter(n, pt, r["letter"]) or "letter changed")

    def cmd_init():
        n = need_safe()
        if n is None:
            return
        if (pstate["info"] or {}).get("Partitions"):
            return messagebox.showinfo(APP_NAME, "The disk still has partitions. Use Clean Disk first.")
        r = form("Initialize disk", [("note", "Choose the partition style. MBR suits SD cards, cameras and Raspberry Pi; GPT suits disks over 2 TB."),
                                     ("combo", "style", "Style:", ["MBR", "GPT"], "MBR")], "Initialize")
        if r:
            run_op("Initialize disk %d as %s" % (n, r["style"]), lambda lg, pg: op_initialize(n, r["style"]) or "initialized")

    def cmd_clean():
        n = need_safe()
        if n is None:
            return
        if not confirm_typed("ALL partitions and data on disk %d will be removed." % n, n):
            return
        run_op("Clean disk %d" % n, lambda lg, pg: op_clean(n) or "disk cleaned")

    def cmd_wipe():
        n = need_safe()
        if n is None:
            return
        if not confirm_typed("Disk %d will be completely overwritten with zeros. This is slow and cannot be undone." % n, n):
            return
        letters = disk_letters(n)
        run_op("Wipe disk %d" % n, lambda lg, pg: wipe_disk("\\\\.\\PhysicalDrive%d" % n, letters, lg, pg, pstop) or "disk wiped")

    def cmd_eject():
        eject_selected(pstate["disk"])

    # --- sidebar
    sbtn = {}

    def sect(text):
        ttk.Label(side, text=text, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 2))

    def sb(name, text, cmd):
        b_ = ttk.Button(side, text=text, command=cmd, width=24)
        b_.pack(fill="x", pady=1)
        sbtn[name] = b_

    sect("Partition operations")
    sb("format", "Format Partition...", cmd_format)
    sb("delete", "Delete Partition...", cmd_delete)
    sb("create", "Create Partition...", cmd_create)
    sb("resize", "Resize Partition...", cmd_resize)
    sb("label", "Change Label...", cmd_label)
    sb("letter", "Change Drive Letter...", cmd_letter)
    sect("Disk operations")
    sb("init", "Initialize Disk (MBR/GPT)...", cmd_init)
    sb("clean", "Clean Disk...", cmd_clean)
    sb("wipe", "Wipe Disk (zero fill)...", cmd_wipe)
    sb("eject", "Eject Disk", cmd_eject)
    sect("")
    sb("refresh", "Refresh", lambda: (dev_wake.set(), load_disk()))
    ttk.Button(side, text="Stop", command=pstop.set, width=24).pack(fill="x", pady=(8, 1))

    def update_buttons():
        busy = pstate["busy"]
        info = pstate["info"] or {}
        n = pstate["disk"]
        safe = n is not None and disk_safe(n)
        sg = sel_seg()
        pt = sg["part"] if sg and sg["kind"] == "part" else None
        has_parts = bool(info.get("Partitions"))
        raw = str(info.get("Style", "")).upper() in ("RAW", "") and not has_parts

        def en(name, cond):
            sbtn[name].config(state="normal" if (cond and not busy) else "disabled")

        en("format", safe and pt is not None)
        en("delete", safe and pt is not None)
        en("create", safe and sg is not None and sg["kind"] == "free" and not raw)
        en("resize", safe and pt is not None and (pt.get("FS") or "").upper() == "NTFS")
        en("label", safe and pt is not None and bool(pt.get("Letter")))
        en("letter", safe and pt is not None)
        en("init", safe and not has_parts)
        en("clean", safe and has_parts)
        en("wipe", safe)
        en("eject", safe)
        en("refresh", True)

    ppoll()

    # ---------------- Devices panel (right) + themes ----------------
    settings = load_settings()
    theme0 = settings.get("theme") or ("Black" if settings.get("dark") else "Light")
    theme0 = LEGACY_THEMES.get(theme0, theme0)
    theme_var = tk.StringVar(value=theme0 if theme0 in THEMES else "Light")
    style = ttk.Style()
    orig_theme = style.theme_use()
    text_widgets = [txt, rtxt, itxt, atxt, ptxt]
    warn_labels = [warn, iwarn]
    pal_light = {"bg": style.lookup("TFrame", "background") or "#f0f0f0", "fg": "#000000", "field": "#ffffff",
                 "warn": "#b00020", "ok": "#1b7f3b", "dim": "#666666", "accent": "#3b82c4", "border": "#a0a0a0"}

    def apply_theme():
        p = THEMES.get(theme_var.get())
        if p:
            style.theme_use("clam")
            style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                            bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                            troughcolor=p["field"], selectbackground=p["accent"], selectforeground="#ffffff",
                            insertcolor=p["fg"])
            style.configure("TButton", background=p["btn"], foreground=p["fg"], padding=4)
            style.map("TButton", background=[("active", p["btn_hi"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["dim"])])
            style.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
            style.configure("TNotebook.Tab", background=p["btn"], foreground=p["fg"], padding=(10, 4))
            style.map("TNotebook.Tab", background=[("selected", p["accent"]), ("active", p["btn_hi"])],
                      foreground=[("selected", "#ffffff")])
            style.map("TCheckbutton", background=[("active", p["bg"])], indicatorcolor=[("selected", p["accent"]), ("!selected", p["field"])])
            style.map("TRadiobutton", background=[("active", p["bg"])], indicatorcolor=[("selected", p["accent"]), ("!selected", p["field"])])
            style.configure("TCombobox", arrowcolor=p["fg"], background=p["btn"])
            style.map("TCombobox", fieldbackground=[("readonly", p["field"])], foreground=[("readonly", p["fg"])],
                      selectbackground=[("readonly", p["field"])], selectforeground=[("readonly", p["fg"])])
            style.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"])
            style.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["field"])
            style.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"], rowheight=22)
            style.configure("Treeview.Heading", background=p["btn"], foreground=p["fg"])
            style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", "#ffffff")])
            style.configure("TPanedwindow", background=p["bg"])
            pal = p
        else:
            style.theme_use(orig_theme)
            style.configure("Treeview", rowheight=22)
            pal = pal_light
        root.configure(bg=pal["bg"])
        pal_cur["p"] = pal
        redraw_map()
        try:
            tmenu.configure(bg=pal["field"], fg=pal["fg"], activebackground=pal["accent"], activeforeground="#ffffff")
        except tk.TclError:
            pass
        for t in text_widgets:
            t.configure(bg=pal["field"], fg=pal["fg"], insertbackground=pal["fg"],
                        selectbackground=pal["accent"], selectforeground="#ffffff",
                        highlightthickness=1, highlightbackground=pal["border"], highlightcolor=pal["accent"])
        for lb in warn_labels:
            lb.configure(bg=pal["bg"], fg=pal["warn"])
        dev_hint.configure(bg=pal["bg"], fg=pal["dim"])
        tree.tag_configure("usb", foreground=pal["ok"])
        tree.tag_configure("sys", foreground=pal["warn"])
        tree.tag_configure("fix", foreground=pal["fg"])
        for c in (combo, rcombo, icombo, tcombo):               # drop-down list colours
            try:
                c.tk.eval("set pd [ttk::combobox::PopdownWindow %s]; $pd.f.l configure -background %s "
                          "-foreground %s -selectbackground %s" % (c, pal["field"], pal["fg"], pal["accent"]))
            except tk.TclError:
                pass
        settings["theme"] = theme_var.get()
        settings.pop("dark", None)
        save_settings(settings)

    # --- devices tree
    hdr = ttk.Frame(right, padding=(8, 8, 8, 0))
    hdr.pack(fill="x")
    ttk.Label(hdr, text="Available devices", font=("Segoe UI", 11, "bold")).pack(side="left")
    tcombo = ttk.Combobox(hdr, textvariable=theme_var, values=list(THEMES), state="readonly", width=15)
    tcombo.pack(side="right")
    tcombo.bind("<<ComboboxSelected>>", lambda e: (apply_theme(), tcombo.selection_clear()))
    ttk.Label(hdr, text="Theme:").pack(side="right", padx=(0, 4))
    tree = ttk.Treeview(right, columns=("info", "size"), height=16, selectmode="browse")
    tree.heading("#0", text="Device")
    tree.heading("info", text="Bus / FS")
    tree.heading("size", text="Free / Size")
    tree.column("#0", width=185, stretch=True)
    tree.column("info", width=60, stretch=False)
    tree.column("size", width=125, stretch=False)
    tree.pack(fill="both", expand=True, padx=8, pady=6)
    dev_hint = tk.Label(right, justify="left", wraplength=320, anchor="w",
                        text="Click a device to select it in every tab. Right-click for Eject.\n"
                             "Red = system disk (protected). Other colors = removable / USB / SD.")
    dev_hint.pack(fill="x", padx=8)
    dev_btns = ttk.Frame(right, padding=8)
    dev_btns.pack(fill="x")
    dq = queue.Queue()
    dev_stop = threading.Event()
    dev_wake = threading.Event()
    dev_state = {"sig": None}

    def fill_tree(devs):
        tree.delete(*tree.get_children())
        if not devs:
            tree.insert("", "end", text="(no devices found - Windows only)" if not IS_WIN else "(no devices found)")
            return
        for d in devs:
            usb = str(d.get("Bus", "")).upper() in SAFE_BUS and not d.get("System")
            tag = "sys" if d.get("System") else ("usb" if usb else "fix")
            top_id = tree.insert("", "end", iid="d%s" % d.get("Number"), open=True, tags=(tag,),
                                 text="Disk %s  %s" % (d.get("Number"), d.get("Name") or ""),
                                 values=(d.get("Bus", ""), "%.1f GB" % ((d.get("Size") or 0) / 1e9)))
            for v in d.get("Volumes") or []:
                tree.insert(top_id, "end", iid="v%s" % v.get("Letter"), tags=(tag,),
                            text="%s:  %s" % (v.get("Letter"), v.get("Label") or "(no label)"),
                            values=(v.get("FS") or "", "%.1f / %.1f GB" % ((v.get("Free") or 0) / 1e9, (v.get("Size") or 0) / 1e9)))

    def apply_drives(new):
        nonlocal drives
        old = {d[1]: d[0] for d in drives}
        sel = {c: old.get(c.get()) for c in (combo, rcombo, icombo)}
        drives = new
        vals = [d[1] for d in drives]
        for c in (combo, rcombo, icombo):
            c["values"] = vals
            path = sel[c]
            idx = next((i for i, d in enumerate(drives) if d[0] == path), None)
            if idx is not None:
                c.current(idx)
            elif c.get() in old or not c.get():
                if drives:
                    c.current(0)

    def device_poll():
        try:
            while True:
                kind_, msg_ = eq.get_nowait()
                dev_msg.config(text=msg_)
                if kind_ == "err":
                    messagebox.showerror(APP_NAME, msg_)
                elif kind_ == "ok":
                    dev_wake.set()
        except queue.Empty:
            pass
        try:
            while True:
                devs, drv = dq.get_nowait()
                sig = json.dumps([devs, [d[:2] for d in drv]], sort_keys=True, default=str)
                if sig != dev_state["sig"]:
                    dev_state["sig"] = sig
                    sel_item = tree.selection()
                    devcache["list"] = devs
                    fill_tree(devs)
                    fill_disk_combo()
                    apply_drives(drv)
                    if sel_item and tree.exists(sel_item[0]):
                        tree.selection_set(sel_item[0])
        except queue.Empty:
            pass
        root.after(400, device_poll)

    def device_worker():
        while not dev_stop.is_set():
            try:
                dq.put((list_devices(), list_drives()))
            except Exception:
                pass
            dev_wake.wait(8)
            dev_wake.clear()

    def pick_letter(letter):
        for i, d in enumerate(drives):
            if d[0][:1].upper() == letter.upper():
                for c in (combo, rcombo, icombo):
                    c.current(i)
                custom["path"] = None
                return

    def on_tree_select(_e=None):
        s = tree.selection()
        if not s:
            return
        iid = s[0]
        follow_disk(tree_disk())
        if iid.startswith("v"):
            pick_letter(iid[1:])
        else:
            kids = tree.get_children(iid)
            if kids:
                pick_letter(kids[0][1:])

    tree.bind("<<TreeviewSelect>>", on_tree_select)
    ttk.Button(dev_btns, text="Refresh now", command=dev_wake.set).pack(side="left")
    ttk.Button(dev_btns, text="Eject", command=lambda: eject_selected()).pack(side="left", padx=6)
    dev_msg = ttk.Label(right, text="", wraplength=340, justify="left")
    dev_msg.pack(fill="x", padx=8)
    eq = queue.Queue()

    def tree_disk():
        s_ = tree.selection()
        if not s_:
            return None
        iid = s_[0]
        if iid.startswith("v"):
            iid = tree.parent(iid)
        return int(iid[1:]) if iid.startswith("d") and iid[1:].isdigit() else None

    def eject_selected(n=None):
        n = tree_disk() if n is None else n
        if n is None:
            return messagebox.showinfo(APP_NAME, "Click a device in the list first.")
        d = disk_entry(n)
        if not d or not disk_safe(n):
            return messagebox.showerror(APP_NAME, "Only removable, USB and SD disks can be ejected. System and internal disks are protected.")
        letters = disk_letters(n)
        if not messagebox.askyesno(APP_NAME, "Eject disk %d (%s, %.1f GB)?\nVolumes: %s\n\nMake sure nothing is copying to it." % (
                n, d.get("Name") or "", (d.get("Size") or 0) / 1e9, ", ".join(l + ":" for l in letters) or "none")):
            return
        dev_msg.config(text="Ejecting disk %d..." % n)

        def work():
            try:
                eject_disk(n, letters, lambda m: eq.put(("msg", m)))
                eq.put(("ok", "Disk %d ejected - safe to unplug." % n))
            except Exception as e:
                eq.put(("err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    tmenu = tk.Menu(root, tearoff=0)
    tmenu.add_command(label="Eject", command=lambda: eject_selected())
    tmenu.add_command(label="Manage partitions...", command=lambda: (nb.select(ptab), follow_disk(tree_disk(), True)))

    def tree_menu(e):
        row = tree.identify_row(e.y)
        if row:
            tree.selection_set(row)
            tmenu.tk_popup(e.x_root, e.y_root)

    tree.bind("<Button-3>", tree_menu)

    def follow_disk(n, force=False):
        if n is None or pstate["busy"] or (n == pstate["disk"] and not force):
            return
        for v in pdisk["values"]:
            if v.startswith("Disk %s " % n):
                pdisk.set(v)
                load_disk()
                return
    refresh = lambda: dev_wake.set()          # Refresh buttons on the tabs use the same worker
    threading.Thread(target=device_worker, daemon=True).start()
    device_poll()
    apply_theme()

    def place_sash():
        try:
            main.sashpos(0, max(560, root.winfo_width() - 400))
        except tk.TclError:
            pass

    root.after(150, place_sash)

    def on_close():
        stop_evt.set()
        rstop.set()
        istop.set()
        dev_stop.set()
        dev_wake.set()
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
    ap = argparse.ArgumentParser(description=APP_TITLE + " - " + APP_TAGLINE)
    ap.add_argument("--cli", metavar="PATH", help="run without GUI on this drive/folder, e.g. E:\\")
    ap.add_argument("--mode", choices=["quick", "full"], default="quick")
    ap.add_argument("--size", type=int, default=512, help="MB for quick mode")
    ap.add_argument("--report", help="write report to this file (CLI)")
    ap.add_argument("--recover", metavar="SRC", help="recover deleted files from this card/image, e.g. E:\\ or card.img")
    ap.add_argument("--out", help="output folder for --recover (must be on a different drive)")
    ap.add_argument("--types", default="", help="comma list of groups: Photos,Documents,Video,Audio_Video,Other")
    ap.add_argument("--keep-existing", action="store_true", help="also recover files that still exist")
    ap.add_argument("--image", nargs=2, metavar=("SRC", "DEST"), help="make a sector image of the card first")
    ap.add_argument("--whole-disk", action="store_true", help="with --image: copy the whole physical disk")
    ap.add_argument("--write-image", nargs=2, metavar=("IMG", "DRIVE"), help="write IMG to the card at DRIVE (ERASES IT)")
    ap.add_argument("--verify", nargs=2, metavar=("IMG", "DRIVE"), help="compare IMG with the card")
    ap.add_argument("--hash", metavar="FILE", help="print MD5 / SHA-1 / SHA-256 of a file")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation for --write-image")
    ap.add_argument("--no-verify", action="store_true", help="skip verification after --write-image")
    ap.add_argument("--eject", metavar="DRIVE", help="safely eject the removable disk behind this drive letter")
    ap.add_argument("--format", metavar="DRIVE", help="format the partition at DRIVE (ERASES IT); use with --fs/--label")
    ap.add_argument("--fs", choices=["FAT32", "exFAT", "NTFS"], default="exFAT", help="file system for --format")
    ap.add_argument("--label", default="", help="volume label for --format")
    ap.add_argument("--cluster", type=int, default=0, help="cluster size in bytes for --format (0 = default)")
    ap.add_argument("--full", action="store_true", help="full (not quick) format with --format")
    ap.add_argument("--version", action="version", version=APP_TITLE)
    ap.add_argument("--no-admin", action="store_true", help="do not ask for administrator rights")
    a = ap.parse_args()
    needs_admin = (not a.cli or a.image or a.recover or a.write_image or a.verify or a.eject or a.format) and not a.hash
    if IS_WIN and needs_admin and not a.no_admin and not is_admin():
        if relaunch_as_admin():
            return                               # elevated copy is running
    if not (a.cli or a.image or a.recover or a.write_image or a.verify or a.hash or a.eject or a.format):
        hide_own_console()
    if a.hash:
        for k, v in hash_file(a.hash).items():
            print(f"{k:7s}: {v}")
    elif a.eject:
        d = resolve_disk(a.eject)
        if not d["safe"]:
            sys.exit(f"Refusing: disk {d['number']} is not a removable/USB/SD disk.")
        eject_disk(d["number"], d["letters"])
    elif a.format:
        d = resolve_disk(a.format)
        if not d["safe"]:
            sys.exit(f"Refusing: disk {d['number']} is not a removable/USB/SD disk (bus {d['bus']}, system {d['system']}).")
        L = a.format.strip().rstrip("\\/:").upper()
        part = next((p for p in list_partitions(d["number"])["Partitions"] if (p.get("Letter") or "").upper() == L), None)
        if not part:
            sys.exit("Could not find that partition.")
        print(f"About to ERASE {L}: ({fmt_size(part['Size'])}) and format it as {a.fs}.")
        if not a.yes and input("Type YES to continue: ").strip() != "YES":
            sys.exit("Cancelled.")
        op_format(d["number"], part, a.fs, a.label, a.cluster or None, not a.full)
        print("Formatted.")
    elif a.write_image:
        img, drv = a.write_image
        d = resolve_disk(drv)
        if not d["safe"]:
            sys.exit(f"Refusing: disk {d['number']} is not a removable/USB/SD disk (bus {d['bus']}, system {d['system']}).")
        print(f"About to ERASE disk {d['number']}: {d['model']} {fmt_size(d['size'])}, volumes {', '.join(d['letters'])}")
        if not a.yes and input("Type YES to continue: ").strip() != "YES":
            sys.exit("Cancelled.")
        ok = write_image(img, d["path"], d["letters"], not a.no_verify)
        sys.exit(0 if ok else 1)
    elif a.verify:
        tgt = a.verify[1]
        if len(tgt.rstrip("\\/:")) == 1:                 # drive letter -> physical disk
            tgt = resolve_disk(tgt)["path"]
        sys.exit(0 if verify_image(a.verify[0], tgt) else 1)
    elif a.image:
        image_card(a.image[0], a.image[1], whole_disk=a.whole_disk)
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
