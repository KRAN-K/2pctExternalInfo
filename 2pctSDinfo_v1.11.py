# NEED PYTHON? Download the Windows installer here (copy and paste into your browser): https://www.python.org/downloads/windows/
# On the first installer screen tick "Add python.exe to PATH", click Install Now, then double-click this file (2pctSDinfo).
r"""
2%SDinfo  v1.11  -  Micro SD / SD card / USB drive checker, imager and recovery tool (Windows).

GUI:   python 2pctSDinfo_v1.11.py
CLI:   python 2pctSDinfo_v1.11.py --cli E:\ --mode quick|full [--size MB] [--report out.txt]

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
APP_VERSION = "1.11"
APP_TAG = "v" + APP_VERSION
APP_TITLE = f"{APP_NAME} {APP_TAG}"
APP_TAGLINE = "SD card & USB drive checker, disk imager and deleted-file recovery"
APP_REPO = "https://github.com/KRAN-K/2pctExternalInfo"
CHANGELOG = [
    ("1.11", "2026-11-23", [
        "Partitions tab: 'Set Disk Offline' / 'Set Disk Online' buttons, like Disk Management - an offline disk disappears from Windows (and stays safe from other programs) until you bring it back",
        "Devices panel: offline disks are marked '(offline)'; right-click menu has Set offline / Set online",
        "While a disk is offline the destructive buttons (format, delete, clean, wipe...) are switched off",
    ]),
    ("1.10", "2026-11-23", [
        "Pi tab: SSH key box can now fill itself - 'Get from GitHub' downloads a user's public keys from github.com/<name>.keys, 'Use this PC's key' reads your existing key or makes a new one",
        "Pi tab: the SSH key box holds several keys (one per line)",
    ]),
    ("1.9.1", "2026-11-23", [
        "Fix: Partitions tab - the confirm box for Format / Delete showed nothing to type on partitions without a drive letter (such as a Raspberry Pi card's Linux partitions). It now asks for the partition number",
    ]),
    ("1.9", "2026-11-19", [
        "Pi tab: new 'Android-based systems' folder - every Android / LineageOS / AOSP / Bass OS image found in Raspberry Pi's own list, plus KonstaKANG (LineageOS, AOSP, Android TV) and emteria.OS",
        "Android images that are only offered on a project web page get an 'Open download page' button; save the .zip, then pick it with 'Use own image file'",
        "Fix: first-boot setup is no longer applied to images that do not support it (Android and other non-Raspberry-Pi-OS images)",
    ]),
    ("1.8", "2026-11-19", [
        "New 2%SDinfo icon: window icon, taskbar icon and About tab (icon files also in the assets folder)",
        "Pi tab: 'Update list now' button re-downloads Raspberry Pi's latest OS list on demand and shows when it was updated",
        "Pi tab: 'My own list' box - add your own OS list (web address or .json file in Imager format); it appears next to the official list as 'My list (custom)'",
    ]),
    ("1.7", "2026-11-19", [
        "New Pi tab, a Raspberry Pi Imager equivalent: the OS list is loaded live from Raspberry Pi's servers (filter by Pi model)",
        "Downloads the image, checks its SHA-256, unpacks it (.xz / .gz / .zip), writes it to the card and reads it back",
        "First-boot setup like Imager's Edit settings: hostname, user and password, Wi-Fi, time zone, keyboard, SSH (with key), SPI / I2C / serial / 1-Wire",
        "Setup is written as cloud-init files (user-data, network-config) or the older firstrun.sh, whichever the image uses",
        "'Apply setup only' button to add the setup to a card that is already written; 'Use own image file' for local images",
    ]),
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
  $res+=[pscustomobject]@{Number=$d.Number;Name=$d.FriendlyName;Offline=[bool]$d.IsOffline;Bus="$($d.BusType)";Size=$d.Size;Style="$($d.PartitionStyle)";Health="$($d.HealthStatus)";System=[bool]($d.IsSystem -or $d.IsBoot);Volumes=$vols}
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
$ErrorActionPreference='SilentlyContinue'
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
    for p in parts:                                  # Windows reports "no letter" as an invisible NUL character
        p["Letter"] = re.sub(r"[^A-Za-z]", "", str(p.get("Letter") or ""))[:1].upper()
    if info.get("Offline"):
        parts = []                                    # Windows cannot show the contents of an offline disk
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
    if info.get("Offline"):
        pass
    elif not parts and size:
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


def op_set_online(disk, online):
    """Disk Management's Online / Offline for one disk."""
    if online:
        run_ps("Set-Disk -Number %d -IsOffline $false" % disk)
        time.sleep(2)
        try:
            if run_ps("(Get-Disk -Number %d).IsReadOnly" % disk).strip().lower() == "true":
                return "online, but Windows marks it read-only (check the lock switch on the card / adapter)"
        except RuntimeError:
            pass
        return "disk %d is online" % disk
    run_ps("Set-Disk -Number %d -IsOffline $true" % disk)
    return "disk %d is offline - it is hidden from Windows until you set it online again" % disk


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
# PI TAB  (Raspberry Pi Imager equivalent: live OS list, download, write, first-boot setup)
# ----------------------------------------------------------------------------
PI_REPO_URL = "https://downloads.raspberrypi.org/os_list_imagingutility_v4.json"
PI_REPO_MIRRORS = ["https://downloads.raspberrypi.com/os_list_imagingutility_v4.json",
                   "https://mirror.iscas.ac.cn/raspberry-pi-os-images/os_list_imagingutility_v4.json"]
PI_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".2pctsdinfo_cache")
PI_LIST_CACHE = os.path.join(PI_CACHE_DIR, "os_list_v4.json")
CRYPT64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def pi_http_get(url, timeout=25):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": APP_NAME + "/" + APP_VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pi_read_json(src):
    """Read an Imager-format list from a web address or a local .json file."""
    src = src.strip().strip('"')
    if re.match(r"^https?://", src, re.I):
        return json.loads(pi_http_get(src).decode("utf-8-sig"))
    if src.lower().startswith("file://"):
        src = src[7:].lstrip("/") if IS_WIN else src[7:]
    with open(src, encoding="utf-8-sig") as f:
        return json.load(f)


def pi_load_repo(url=None, log=print, custom=None):
    """Fetch the official Imager repository JSON (falls back to mirrors, then to the saved copy)
    and add the user's own list (web address or file) as a 'My list (custom)' folder.
    Returns (data, source_text)."""
    url = url or os.environ.get("SDCC_PI_REPO")          # alternative repository (also used by tests)
    urls = [url] if url else [PI_REPO_URL] + PI_REPO_MIRRORS
    data, src, last = None, None, None
    for u in urls:
        try:
            raw = pi_http_get(u)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or "os_list" not in data:
                raise ValueError("not an Imager repository file")
            if not url:
                os.makedirs(PI_CACHE_DIR, exist_ok=True)
                with open(PI_LIST_CACHE, "wb") as f:
                    f.write(raw)
            src = u
            break
        except Exception as e:
            last = e
            log(f"Could not load {u}: {e}")
    if data is None:
        if not url and os.path.isfile(PI_LIST_CACHE):
            with open(PI_LIST_CACHE, encoding="utf-8") as f:
                data, src = json.load(f), "saved copy (offline)"
        else:
            raise RuntimeError(f"Could not load the Raspberry Pi OS list: {last}")
    try:
        nf, npg = pi_add_android(data)
        log("Android folder: %d images from the official list, %d project pages." % (nf, npg))
    except Exception as e:
        log("Could not build the Android folder: %s" % e)
    if custom and custom.strip():
        try:
            cd = pi_read_json(custom)
            items = cd.get("os_list") if isinstance(cd, dict) else cd
            if not isinstance(items, list):
                raise ValueError("no 'os_list' found in it")
            data["os_list"] = list(data["os_list"]) + [{"name": "My list (custom)", "description": custom.strip(),
                                                        "subitems": items}]
            log("Added your own list: %d entries." % len(items))
        except Exception as e:
            log("Could not read your own list (%s): %s" % (custom.strip(), e))
    return data, src


PI_ANDROID_RE = re.compile(r"android|lineage|aosp|emteria|bass ?os|bliss", re.I)

# Android builds that are only offered on a web page (file-host links change with every build, so no direct link).
PI_ANDROID_PAGES = [
    ("AOSP Android 17 - Raspberry Pi 5 / 500 / CM5 (KonstaKANG)", "Plain Android (AOSP). Newest build is listed on the page; 2 GB RAM or more.",
     "https://konstakang.com/devices/rpi5/AOSP17", ["pi5-64bit"]),
    ("AOSP Android 16 - Raspberry Pi 5 / 500 / CM5 (KonstaKANG)", "Plain Android (AOSP).",
     "https://konstakang.com/devices/rpi5/AOSP16", ["pi5-64bit"]),
    ("LineageOS 22.2 (Android 15) - Raspberry Pi 5 / 500 / CM5 (KonstaKANG)", "LineageOS build with Raspberry Pi settings; 2 GB RAM or more.",
     "https://konstakang.com/devices/rpi5/LineageOS22/", ["pi5-64bit"]),
    ("LineageOS 23.2 (Android 16) - Raspberry Pi 4 / 400 / CM4 (KonstaKANG)", "LineageOS build with Raspberry Pi settings.",
     "https://konstakang.com/devices/rpi4/LineageOS23", ["pi4-64bit"]),
    ("LineageOS 22.2 (Android 15) - Raspberry Pi 4 / 400 / CM4 (KonstaKANG)", "LineageOS build with Raspberry Pi settings.",
     "https://konstakang.com/devices/rpi4/LineageOS22", ["pi4-64bit"]),
    ("Android TV (LineageOS) - Raspberry Pi 4 and 5 (KonstaKANG)", "All Android TV builds, newest first; pick the one for your Pi.",
     "https://konstakang.com/tag/AndroidTV", ["pi5-64bit", "pi4-64bit"]),
    ("emteria.OS - Android for Raspberry Pi 4 / 5 (freemium)", "Commercial Android with a free trial; install guide with Raspberry Pi Imager.",
     "https://emteria.com/kb/install-android-raspberry-pi-5-imager", ["pi5-64bit", "pi4-64bit"]),
]


def pi_find_android(items, seen=None):
    """Every downloadable entry in the list whose name / description / link looks Android-based."""
    seen = set() if seen is None else seen
    out = []
    for n in items:
        if n.get("subitems"):
            out += pi_find_android(n["subitems"], seen)
        elif n.get("url") and n["url"] not in seen and n["url"] != "internal://format" \
                and PI_ANDROID_RE.search(" ".join((n.get("name", ""), n.get("description", ""), n["url"]))):
            seen.add(n["url"])
            out.append(n)
    return out


def pi_add_android(data):
    found = pi_find_android(data.get("os_list") or [])
    pages = [{"name": n, "description": d, "page": u, "devices": t, "init_format": "none"}
             for n, d, u, t in PI_ANDROID_PAGES]
    data["os_list"] = list(data["os_list"]) + [{
        "name": "Android-based systems (all)",
        "description": "Android, LineageOS, AOSP and Bass OS images from Raspberry Pi's list, plus project pages for KonstaKANG and emteria",
        "subitems": found + pages}]
    return len(found), len(pages)


def pi_device_choices(data):
    """[(name, tags)] from the repository's device list; first entry = no filter."""
    out = [("No filtering (show everything)", [])]
    for d in (data.get("imager") or {}).get("devices") or []:
        out.append((d.get("name", "?"), list(d.get("tags") or [])))
    return out


def pi_visible(node, tags):
    """Does this OS entry (or any entry inside a category) suit the selected Pi model?"""
    if node.get("url") == "internal://format":
        return False
    if node.get("subitems"):
        return any(pi_visible(c, tags) for c in node["subitems"])
    if node.get("subitems_url"):
        return True                      # looked at once opened
    devs = node.get("devices") or []
    return (not tags) or (not devs) or bool(set(devs) & set(tags))


_PI_SUB_CACHE = {}


def pi_children(node, tags, log=print):
    """Visible child entries of a category (fetches 'subitems_url' lists on demand)."""
    subs = node.get("subitems")
    if subs is None and node.get("subitems_url"):
        u = node["subitems_url"]
        if u not in _PI_SUB_CACHE:
            try:
                d = json.loads(pi_http_get(u).decode("utf-8"))
                _PI_SUB_CACHE[u] = d.get("os_list") or d.get("subitems") or []
            except Exception as e:
                log(f"Could not load sub-list {u}: {e}")
                _PI_SUB_CACHE[u] = []
        subs = _PI_SUB_CACHE[u]
    return [c for c in (subs or []) if pi_visible(c, tags)]


def pi_is_category(node):
    return bool(node.get("subitems") is not None or node.get("subitems_url"))


def pi_download(url, dest, expect_sha256=None, progress=None, stop=None, log=print):
    """Download url -> dest (resumes a .part file). Checks SHA-256 when given."""
    import urllib.request
    stop = stop or threading.Event()
    if os.path.isfile(dest) and (not expect_sha256 or hash_file(dest)["SHA256"] == expect_sha256.lower()):
        log("Already downloaded: " + os.path.basename(dest))
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    hdr = {"User-Agent": APP_NAME + "/" + APP_VERSION}
    if have:
        hdr["Range"] = "bytes=%d-" % have
    r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30)
    mode = "ab"
    if have and r.status != 206:
        have, mode = 0, "wb"
    total = int(r.headers.get("Content-Length") or 0) + have
    log("Downloading %s (%s)" % (url, fmt_size(total) if total else "size unknown"))
    t0 = time.time()
    done = have
    with open(part, mode) as f:
        while True:
            if stop.is_set():
                raise Stopped()
            b = r.read(1024 * 1024)
            if not b:
                break
            f.write(b)
            done += len(b)
            if progress and total:
                progress(done / total, "Downloading")
    r.close()
    if total and done < total:
        raise RuntimeError("Download ended early - run it again to resume.")
    if expect_sha256:
        if hash_file(part, progress=lambda f_, s_: progress and progress(f_, "Checking download"), stop=stop)["SHA256"] != expect_sha256.lower():
            os.remove(part)
            raise RuntimeError("Downloaded file failed its SHA-256 check (deleted). Try again.")
        log("Download checksum OK.")
    os.replace(part, dest)
    log("Download finished at %.1f MB/s." % (done / 1e6 / max(0.001, time.time() - t0)))
    return dest


def pi_extract(src, dest, expect_sha256=None, progress=None, stop=None, log=print):
    """Decompress .xz / .gz / .zip / .zst (or copy a raw image) into dest."""
    stop = stop or threading.Event()
    low = src.lower()
    tot = os.path.getsize(src)
    h = hashlib.sha256()
    written = 0
    consumed = [0]

    def sink(out, chunk):
        nonlocal written
        out.write(chunk)
        h.update(chunk)
        written += len(chunk)

    with open(dest, "wb") as out:
        if low.endswith(".xz"):
            import lzma
            d = lzma.LZMADecompressor()
            with open(src, "rb") as f:
                while True:
                    if stop.is_set():
                        raise Stopped()
                    b = f.read(2 * MB)
                    if not b:
                        break
                    consumed[0] += len(b)
                    while not d.eof:
                        sink(out, d.decompress(b, 8 * MB))
                        b = b""
                        if d.needs_input:
                            break
                    if progress:
                        progress(consumed[0] / max(1, tot), "Unpacking")
        elif low.endswith(".gz"):
            import gzip
            with gzip.open(src, "rb") as f:
                while True:
                    if stop.is_set():
                        raise Stopped()
                    b = f.read(4 * MB)
                    if not b:
                        break
                    sink(out, b)
                    if progress:
                        progress(min(0.99, f.fileobj.tell() / max(1, tot)), "Unpacking")
        elif low.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(src) as z:
                names = [n for n in z.namelist() if n.lower().endswith((".img", ".iso", ".bin"))] or z.namelist()
                info = z.getinfo(names[0])
                with z.open(info) as f:
                    while True:
                        if stop.is_set():
                            raise Stopped()
                        b = f.read(4 * MB)
                        if not b:
                            break
                        sink(out, b)
                        if progress:
                            progress(written / max(1, info.file_size), "Unpacking")
        elif low.endswith(".zst"):
            try:
                from compression import zstd as _z
            except ImportError:
                try:
                    import zstandard as _z2
                except ImportError:
                    raise RuntimeError("This image is .zst compressed. Needs Python 3.14+ or 'pip install zstandard'.")
                with open(src, "rb") as f:
                    for b in _z2.ZstdDecompressor().read_to_iter(f):
                        sink(out, b)
            else:
                with _z.open(src, "rb") as f:
                    while True:
                        b = f.read(4 * MB)
                        if not b:
                            break
                        sink(out, b)
        else:
            with open(src, "rb") as f:
                while True:
                    if stop.is_set():
                        raise Stopped()
                    b = f.read(4 * MB)
                    if not b:
                        break
                    sink(out, b)
                    if progress:
                        progress(written / max(1, tot), "Copying")
    if expect_sha256 and h.hexdigest() != expect_sha256.lower():
        os.remove(dest)
        raise RuntimeError("Unpacked image failed its SHA-256 check - the download is damaged. Delete the cached file and retry.")
    log("Unpacked image: %s%s" % (fmt_size(written), ", checksum OK" if expect_sha256 else ""))
    return written


def pi_prepare_image(node, log=print, progress=None, stop=None):
    """Make a raw .img ready to write from an OS entry (download + unpack) or a local file."""
    os.makedirs(PI_CACHE_DIR, exist_ok=True)
    local = node.get("local")
    if local:
        src = local
    else:
        url = node["url"]
        name = os.path.basename(url.split("?")[0]) or "image.img.xz"
        src = pi_download(url, os.path.join(PI_CACHE_DIR, name), node.get("image_download_sha256"), progress, stop, log)
    need = int(node.get("extract_size") or os.path.getsize(src) * 3)
    import shutil
    free = shutil.disk_usage(PI_CACHE_DIR).free
    if free < need + 256 * MB:
        raise RuntimeError("Not enough free space in %s: need about %s, have %s." % (PI_CACHE_DIR, fmt_size(need), fmt_size(free)))
    out = os.path.join(PI_CACHE_DIR, "_unpacked.img")
    pi_extract(src, out, node.get("extract_sha256"), progress, stop, log)
    return out


def sha512_crypt(password, salt=None, rounds=5000):
    """Linux '$6$' password hash (what cloud-init / chpasswd -e expect). Pure Python."""
    pw = password.encode("utf-8")
    if salt is None:
        rnd = random.SystemRandom()
        salt = "".join(rnd.choice(CRYPT64) for _ in range(16))
    sb = salt[:16].encode()
    H = hashlib.sha512
    b = H(pw + sb + pw).digest()
    ain = pw + sb + b * (len(pw) // 64) + b[:len(pw) % 64]
    n = len(pw)
    while n > 0:
        ain += b if n & 1 else pw
        n >>= 1
    a = H(ain).digest()
    dp = H(pw * len(pw)).digest()
    p = dp * (len(pw) // 64) + dp[:len(pw) % 64]
    ds = H(sb * (16 + a[0])).digest()
    s = ds * (len(sb) // 64) + ds[:len(sb) % 64]
    c = a
    for i in range(rounds):
        x = p if i & 1 else c
        if i % 3:
            x += s
        if i % 7:
            x += p
        x += c if i & 1 else p
        c = H(x).digest()
    order = [(0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4), (47, 5, 26), (6, 27, 48),
             (28, 49, 7), (50, 8, 29), (9, 30, 51), (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13),
             (56, 14, 35), (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19), (62, 20, 41)]
    out = ""
    for x1, x2, x3 in order:
        v = c[x1] << 16 | c[x2] << 8 | c[x3]
        for _ in range(4):
            out += CRYPT64[v & 63]
            v >>= 6
    v = c[63]
    for _ in range(2):
        out += CRYPT64[v & 63]
        v >>= 6
    return "$6$" + salt[:16] + "$" + out


def wifi_psk(ssid, passphrase):
    """WPA2 pre-shared key (64 hex chars) - lets the Wi-Fi password be stored un-readable."""
    return hashlib.pbkdf2_hmac("sha1", passphrase.encode(), ssid.encode(), 4096, 32).hex()


def _q(s):
    return json.dumps(str(s), ensure_ascii=False)       # JSON string == valid YAML double-quoted string


def pi_userdata(o, rpi=True):
    L = ["#cloud-config", "# written by " + APP_TITLE]
    if o.get("hostname"):
        L += ["hostname: " + _q(o["hostname"]), "manage_etc_hosts: true"]
    if o.get("timezone"):
        L.append("timezone: " + _q(o["timezone"]))
    if o.get("keymap"):
        L += ["keyboard:", "  model: pc105", "  layout: " + _q(o["keymap"])]
    keys = [k.strip() for k in (o.get("ssh_keys") or "").splitlines() if k.strip()]
    if o.get("username") and (o.get("password") or keys):
        L += ["users:", "  - name: " + _q(o["username"]),
              "    groups: users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,input,gpio,spi,i2c,render,sudo",
              "    shell: /bin/bash", "    lock_passwd: " + ("false" if o.get("password") else "true")]
        if o.get("password"):
            L.append("    passwd: " + _q(sha512_crypt(o["password"])))
        L.append("    sudo: ALL=(ALL) NOPASSWD:ALL")
        if keys:
            L.append("    ssh_authorized_keys:")
            L += ["      - " + _q(k) for k in keys]
    if o.get("ssh"):
        L.append("enable_ssh: true" if rpi else "ssh_pwauth: true")
        L.append("ssh_pwauth: " + ("true" if o.get("ssh_pw", True) else "false"))
    if rpi:
        r = [(k, o.get(k)) for k in ("spi", "i2c", "serial", "onewire") if o.get(k)]
        if r:
            L.append("rpi:")
            L += ["  %s: true" % k for k, _ in r]
    return "\n".join(L) + "\n"


def pi_networkconfig(o):
    if not o.get("wifi_ssid"):
        return None
    L = ["network:", "  version: 2", "  wifis:", "    renderer: NetworkManager", "    wlan0:", "      dhcp4: true",
         "      optional: true"]
    if o.get("wifi_country"):
        L.append("      regulatory-domain: " + _q(o["wifi_country"].upper()))
    L += ["      access-points:", "        " + _q(o["wifi_ssid"]) + ":"]
    if o.get("wifi_pass"):
        pw = o["wifi_pass"]
        L.append("          password: " + _q(wifi_psk(o["wifi_ssid"], pw) if 8 <= len(pw) <= 63 else pw))
    if o.get("wifi_hidden"):
        L.append("          hidden: true")
    return "\n".join(L) + "\n"


def pi_firstrun(o):
    """Legacy first-boot script (init_format 'systemd')."""
    def sq(s):
        return "'" + str(s).replace("'", "'\"'\"'") + "'"
    S = ["#!/bin/bash", "set +e", "IC=/usr/lib/raspberrypi-sys-mods/imager_custom"]
    if o.get("hostname"):
        S += ["CURRENT_HOSTNAME=`cat /etc/hostname | tr -d \" \\t\\n\\r\"`",
              "if [ -f $IC ]; then $IC set_hostname %s; else" % sq(o["hostname"]),
              "  echo %s >/etc/hostname" % sq(o["hostname"]),
              "  sed -i \"s/127.0.1.1.*$CURRENT_HOSTNAME/127.0.1.1\\t%s/g\" /etc/hosts" % o["hostname"], "fi"]
    if o.get("ssh"):
        if o.get("ssh_keys", "").strip():
            S += ["FIRSTUSER=`getent passwd 1000 | cut -d: -f1`", "FIRSTUSERHOME=`getent passwd 1000 | cut -d: -f6`"]
            S += ["if [ -f $IC ]; then $IC enable_ssh -k %s; else" % sq(o["ssh_keys"].strip().splitlines()[0]),
                  "  install -o \"$FIRSTUSER\" -m 700 -d \"$FIRSTUSERHOME/.ssh\"",
                  "  echo %s >> \"$FIRSTUSERHOME/.ssh/authorized_keys\"" % sq(o["ssh_keys"].strip().splitlines()[0]),
                  "  systemctl enable ssh", "fi"]
        else:
            S += ["if [ -f $IC ]; then $IC enable_ssh; else systemctl enable ssh; fi"]
    if o.get("username") and o.get("password"):
        S += ["FIRSTUSER=`getent passwd 1000 | cut -d: -f1`",
              "if [ -f /usr/lib/userconf-pi/userconf ]; then /usr/lib/userconf-pi/userconf %s %s; else" % (sq(o["username"]), sq(sha512_crypt(o["password"]))),
              "  echo \"$FIRSTUSER:\"%s | chpasswd -e" % sq(sha512_crypt(o["password"])),
              "  [ \"$FIRSTUSER\" != %s ] && usermod -l %s \"$FIRSTUSER\" && usermod -m -d /home/%s %s && groupmod -n %s \"$FIRSTUSER\"" % ((sq(o["username"]),) * 2 + (o["username"], sq(o["username"]), sq(o["username"]))),
              "fi"]
    if o.get("wifi_ssid"):
        S += ["if [ -f $IC ]; then $IC set_wlan %s %s %s; fi" % (
            sq(o["wifi_ssid"]), sq(wifi_psk(o["wifi_ssid"], o["wifi_pass"]) if o.get("wifi_pass") else ""), sq((o.get("wifi_country") or "US").upper()))]
    if o.get("keymap") or o.get("timezone"):
        if o.get("keymap"):
            S.append("[ -f $IC ] && $IC set_keymap %s" % sq(o["keymap"]))
        if o.get("timezone"):
            S.append("[ -f $IC ] && $IC set_timezone %s" % sq(o["timezone"]))
    S += ["rm -f /boot/firstrun.sh", "sed -i 's| systemd.run.*||g' /boot/cmdline.txt", "exit 0"]
    return "\n".join(S) + "\n"


PI_CMDLINE_ADD = " systemd.run=/boot/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target"


def pi_detect_format(boot_dir):
    if os.path.isfile(os.path.join(boot_dir, "user-data")):
        return "cloudinit-rpi"
    cp = os.path.join(boot_dir, "cmdline.txt")
    if os.path.isfile(cp):
        try:
            with open(cp, encoding="utf-8", errors="ignore") as f:
                if "raspberrypi-sys-mods" in f.read():          # Raspberry Pi OS style first-boot hook
                    return "systemd"
        except OSError:
            pass
    return None


def pi_write_boot_files(boot_dir, o, fmt=None, log=print):
    """Write the first-boot setup onto the card's boot partition (the FAT32 one)."""
    fmt = pi_detect_format(boot_dir) if fmt is None else fmt
    if fmt not in ("cloudinit", "cloudinit-rpi", "systemd"):
        log("This image has no first-boot setup support - skipped customisation.")
        return False

    def w(name, text):
        with open(os.path.join(boot_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        log("  wrote " + name)

    if fmt.startswith("cloudinit"):
        w("user-data", pi_userdata(o, rpi=(fmt == "cloudinit-rpi")))
        nc = pi_networkconfig(o)
        if nc:
            w("network-config", nc)
    else:
        w("firstrun.sh", pi_firstrun(o))
        cp = os.path.join(boot_dir, "cmdline.txt")
        with open(cp, encoding="utf-8") as f:
            cur = f.read().strip()
        cur = re.sub(r"\s+systemd\.(run|run_success_action|unit)=\S+", "", cur)
        with open(cp, "w", encoding="utf-8", newline="\n") as f:
            f.write(cur + PI_CMDLINE_ADD + "\n")
        log("  updated cmdline.txt")
    log("First-boot setup written (%s)." % fmt)
    return True


def pi_find_boot(disk_number, timeout=40, log=print):
    """Windows: wait for the freshly written card's FAT boot partition to get a drive letter."""
    t0 = time.time()
    tried_assign = False
    while time.time() - t0 < timeout:
        for d in list_devices():
            if int(d.get("Number", -1)) != int(disk_number):
                continue
            for v in d.get("Volumes") or []:
                if str(v.get("FS", "")).upper().startswith("FAT") and v.get("Letter"):
                    return v["Letter"] + ":\\"
        if not tried_assign and time.time() - t0 > 8:
            tried_assign = True
            try:
                assign_letter(int(disk_number), 1)
            except Exception as e:
                log("Could not mount the boot partition automatically: %s" % e)
        time.sleep(2)
    return None


def pi_fetch_keys(user, base="https://github.com"):
    """Public SSH keys of a GitHub (or GitLab-style) account: <base>/<user>.keys"""
    user = user.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", user):
        raise ValueError("That does not look like a GitHub user name.")
    try:
        txt = pi_http_get("%s/%s.keys" % (base, user), timeout=15).decode("utf-8", "ignore")
    except Exception as e:
        if "404" in str(e):
            raise RuntimeError("No GitHub user called '%s'." % user)
        raise RuntimeError("Could not reach GitHub: %s" % e)
    keys = [l.strip() for l in txt.splitlines() if re.match(r"^(ssh-|ecdsa-|sk-)", l.strip())]
    if not keys:
        raise RuntimeError("'%s' exists but has no public SSH keys on GitHub (add one at github.com/settings/keys)." % user)
    return keys


def pi_local_pubkey(generate=True, log=print):
    """This PC's public key (~/.ssh/id_ed25519.pub or id_rsa.pub); makes an ed25519 key if there is none."""
    d = os.path.join(os.path.expanduser("~"), ".ssh")
    for n in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        f = os.path.join(d, n)
        if os.path.isfile(f):
            with open(f, encoding="utf-8", errors="ignore") as fh:
                k = fh.read().strip()
            if k:
                return k, "existing key " + f
    if not generate:
        raise RuntimeError("No key found in " + d)
    import subprocess
    os.makedirs(d, exist_ok=True)
    priv = os.path.join(d, "id_ed25519")
    try:
        r = subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "2pctSDinfo", "-f", priv],
                           capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise RuntimeError("ssh-keygen was not found. On Windows turn on Settings > Apps > Optional features > OpenSSH Client.")
    if r.returncode != 0 or not os.path.isfile(priv + ".pub"):
        raise RuntimeError("ssh-keygen failed: " + (r.stderr or r.stdout).strip()[:200])
    with open(priv + ".pub", encoding="utf-8") as fh:
        return fh.read().strip(), "NEW key made at " + priv + " (keep that private file safe)"


PI_SETTING_KEYS = ("hostname", "username", "wifi_ssid", "wifi_country", "timezone", "keymap", "ssh", "ssh_pw",
                   "spi", "i2c", "serial", "onewire", "wifi_hidden", "ssh_keys")



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
    try:
        icon_img = tk.PhotoImage(data=ICON_PNG_B64)
        root.iconphoto(True, icon_img)
    except Exception:
        icon_img = None
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
    pitab = ttk.Frame(nb)
    atab = ttk.Frame(nb)
    nb.add(tab, text="  Test & Info  ")
    nb.add(rtab, text="  Recover deleted files  ")
    nb.add(itab, text="  Disk Imager  ")
    nb.add(ptab, text="  Partitions  ")
    nb.add(pitab, text="  Pi  ")
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
    if icon_img is not None:
        about_icon = icon_img.subsample(2, 2)
        ttk.Label(ah, image=about_icon).pack(side="left", padx=(0, 10))
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
        a = simpledialog.askstring(APP_NAME, "%s\n\nType  %s  to confirm:" % (what, str(expected).strip() or "?"), parent=root)
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

    def cmd_online(go_online=None):
        n = need_safe()
        if n is None:
            return
        off = bool((pstate["info"] or {}).get("Offline"))
        if go_online is None:
            go_online = off
        if go_online == (not off):
            return messagebox.showinfo(APP_NAME, "Disk %d is already %s." % (n, "online" if go_online else "offline"))
        if not go_online and not messagebox.askyesno(
                APP_NAME, "Take disk %d offline?\n\nIts drive letters disappear from Windows and nothing can read or write "
                          "it until you set it online again here.\n\nMake sure nothing is copying to it." % n):
            return
        run_op("Set disk %d %s" % (n, "online" if go_online else "offline"), lambda lg, pg: op_set_online(n, go_online))

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
    sb("online", "Set Disk Online", lambda: cmd_online(True))
    sb("offline", "Set Disk Offline...", lambda: cmd_online(False))
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
        is_off = bool(info.get("Offline"))
        safe_all = safe
        safe = safe and not is_off                     # no destructive operations on an offline disk
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
        en("online", safe_all and is_off)
        en("offline", safe_all and not is_off)
        en("eject", safe_all)
        en("refresh", True)

    ppoll()

    # ---------------- Pi tab (Raspberry Pi Imager equivalent) ----------------
    pi_saved = load_settings().get("pi", {})
    pistate = {"data": None, "running": False, "nodes": {}, "custom": None, "tags": [], "devs": []}
    piq = queue.Queue()
    pistop = threading.Event()
    piwarn = tk.Label(pitab, justify="left", anchor="w", wraplength=820,
                      text="WRITING ERASES THE WHOLE CARD. Only removable / USB / SD disks are allowed; your system drive is "
                           "blocked. The OS list comes live from Raspberry Pi's servers; images are downloaded, checked "
                           "against their SHA-256, written and read back.")
    piwarn.pack(fill="x", padx=8, pady=(6, 2))
    pt1 = ttk.Frame(pitab, padding=(8, 2))
    pt1.pack(fill="x")
    ttk.Label(pt1, text="Raspberry Pi model:").pack(side="left")
    picombo = ttk.Combobox(pt1, state="readonly", width=34, values=["Loading list..."])
    picombo.current(0)
    picombo.pack(side="left", padx=6)
    ttk.Button(pt1, text="Update list now", command=lambda: pi_load()).pack(side="left")
    pisrc = ttk.Label(pt1, text="")
    pisrc.pack(side="left", padx=8)
    pt1b = ttk.Frame(pitab, padding=(8, 0))
    pt1b.pack(fill="x")
    ttk.Label(pt1b, text="My own list (web address or .json file):").pack(side="left")
    p_repo = tk.StringVar(value=pi_saved.get("repo", ""))
    ttk.Entry(pt1b, textvariable=p_repo, width=44).pack(side="left", padx=6)

    def pi_pick_repo():
        f = filedialog.askopenfilename(title="Your own OS list (Imager format)",
                                       filetypes=[("JSON list", "*.json"), ("All files", "*.*")])
        if f:
            p_repo.set(f)
            pi_load()

    ttk.Button(pt1b, text="Browse...", command=pi_pick_repo).pack(side="left")
    ttk.Button(pt1b, text="Add list", command=lambda: pi_load()).pack(side="left", padx=4)
    pitf = ttk.Frame(pitab)
    pitf.pack(fill="x", padx=8, pady=4)
    pitree = ttk.Treeview(pitf, columns=("rel", "size"), height=7, selectmode="browse")
    pitree.heading("#0", text="Operating system")
    pitree.heading("rel", text="Released")
    pitree.heading("size", text="Download")
    pitree.column("#0", width=380, stretch=True)
    pitree.column("rel", width=90, stretch=False)
    pitree.column("size", width=90, stretch=False)
    pisb = ttk.Scrollbar(pitf, orient="vertical", command=pitree.yview)
    pitree.configure(yscrollcommand=pisb.set)
    pisb.pack(side="right", fill="y")
    pitree.pack(side="left", fill="x", expand=True)
    pidesc = ttk.Label(pitab, text="Pick an operating system.", wraplength=820, justify="left")
    pidesc.pack(anchor="w", padx=8)
    pt2 = ttk.Frame(pitab, padding=(8, 4))
    pt2.pack(fill="x")
    ttk.Label(pt2, text="Storage:").pack(side="left")
    pdcombo = ttk.Combobox(pt2, values=[d[1] for d in drives], width=50, state="readonly")
    if drives:
        pdcombo.current(0)
    pdcombo.pack(side="left", padx=6)
    ttk.Button(pt2, text="Use own image file...", command=lambda: pi_pick_custom()).pack(side="left")
    pbtn_page = ttk.Button(pt2, text="Open download page", state="disabled", command=lambda: pi_open_page())
    pbtn_page.pack(side="left", padx=6)
    picust = ttk.Label(pt2, text="")
    picust.pack(side="left", padx=8)

    sv = lambda k, d="": tk.StringVar(value=pi_saved.get(k, d))
    bv = lambda k, d=False: tk.BooleanVar(value=pi_saved.get(k, d))
    p_host, p_user, p_pass = sv("hostname", "raspberrypi"), sv("username", "pi"), tk.StringVar()
    p_ssid, p_wpass, p_cc = sv("wifi_ssid"), tk.StringVar(), sv("wifi_country", "US")
    p_tz, p_km = sv("timezone", "America/Boise"), sv("keymap", "us")
    p_on, p_ssh, p_sshpw = bv("on", True), bv("ssh", True), bv("ssh_pw", True)
    p_hid, p_spi, p_i2c, p_ser, p_ow = bv("wifi_hidden"), bv("spi"), bv("i2c"), bv("serial"), bv("onewire")
    p_verify = tk.BooleanVar(value=True)
    sf = ttk.LabelFrame(pitab, text=" First-boot setup (Imager's \"Edit settings\") ", padding=6)
    sf.pack(fill="x", padx=8, pady=4)
    ttk.Checkbutton(sf, text="Apply this setup after writing", variable=p_on).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(sf, text="Hostname").grid(row=1, column=0, sticky="w")
    ttk.Entry(sf, textvariable=p_host, width=20).grid(row=1, column=1, sticky="w", padx=4, pady=1)
    ttk.Label(sf, text="Username").grid(row=2, column=0, sticky="w")
    ttk.Entry(sf, textvariable=p_user, width=20).grid(row=2, column=1, sticky="w", padx=4, pady=1)
    ttk.Label(sf, text="Password").grid(row=3, column=0, sticky="w")
    ttk.Entry(sf, textvariable=p_pass, width=20, show="*").grid(row=3, column=1, sticky="w", padx=4, pady=1)
    ttk.Label(sf, text="Wi-Fi name").grid(row=1, column=2, sticky="w", padx=(14, 0))
    ttk.Entry(sf, textvariable=p_ssid, width=20).grid(row=1, column=3, sticky="w", padx=4)
    ttk.Label(sf, text="Wi-Fi password").grid(row=2, column=2, sticky="w", padx=(14, 0))
    ttk.Entry(sf, textvariable=p_wpass, width=20, show="*").grid(row=2, column=3, sticky="w", padx=4)
    ttk.Label(sf, text="Wi-Fi country").grid(row=3, column=2, sticky="w", padx=(14, 0))
    ttk.Combobox(sf, textvariable=p_cc, width=6, values=["US", "GB", "CA", "AU", "DE", "FR", "ES", "IT", "NL", "JP", "NZ", "IE"]).grid(row=3, column=3, sticky="w", padx=4)
    ttk.Checkbutton(sf, text="Hidden network", variable=p_hid).grid(row=3, column=3, sticky="e")
    ttk.Label(sf, text="Time zone").grid(row=1, column=4, sticky="w", padx=(14, 0))
    ttk.Combobox(sf, textvariable=p_tz, width=17, values=["America/Boise", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix", "America/Anchorage", "Pacific/Honolulu", "Europe/London", "Europe/Berlin", "Europe/Paris", "Asia/Tokyo", "Australia/Sydney", "UTC"]).grid(row=1, column=5, sticky="w", padx=4)
    ttk.Label(sf, text="Keyboard").grid(row=2, column=4, sticky="w", padx=(14, 0))
    ttk.Combobox(sf, textvariable=p_km, width=8, values=["us", "gb", "de", "fr", "es", "it", "jp", "ca"]).grid(row=2, column=5, sticky="w", padx=4)
    ttk.Checkbutton(sf, text="Enable SSH", variable=p_ssh).grid(row=4, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(sf, text="Allow SSH password login", variable=p_sshpw).grid(row=4, column=2, columnspan=2, sticky="w", padx=(14, 0))
    ttk.Label(sf, text="SSH public key").grid(row=5, column=0, sticky="w")
    pkey = tk.Text(sf, height=2, width=52, font=("Consolas", 9), wrap="char")
    pkey.grid(row=5, column=1, columnspan=3, sticky="we", padx=4, pady=1)
    pkey.insert("1.0", pi_saved.get("ssh_keys", ""))
    pkb = ttk.Frame(sf)
    pkb.grid(row=5, column=4, columnspan=2, sticky="w", padx=4)
    ttk.Button(pkb, text="From GitHub...", command=lambda: pi_key_github()).pack(side="left")
    ttk.Button(pkb, text="This PC's key", command=lambda: pi_key_local()).pack(side="left", padx=4)
    pif = ttk.Frame(sf)
    pif.grid(row=6, column=0, columnspan=6, sticky="w")
    ttk.Label(pif, text="Enable interfaces:").pack(side="left")
    for t_, v_ in (("SPI", p_spi), ("I2C", p_i2c), ("Serial", p_ser), ("1-Wire", p_ow)):
        ttk.Checkbutton(pif, text=t_, variable=v_).pack(side="left", padx=6)
    ttk.Label(pif, text="(cloud-init images only)").pack(side="left")
    pib = ttk.Frame(pitab, padding=(8, 4))
    pib.pack(fill="x")
    pbtn_write = ttk.Button(pib, text="Download and write to card", command=lambda: pi_start("write"))
    pbtn_write.pack(side="left")
    pbtn_apply = ttk.Button(pib, text="Apply setup only (card already written)", command=lambda: pi_start("apply"))
    pbtn_apply.pack(side="left", padx=6)
    pstop_btn = ttk.Button(pib, text="Stop", command=pistop.set, state="disabled")
    pstop_btn.pack(side="left")
    ttk.Checkbutton(pib, text="Verify after write", variable=p_verify).pack(side="left", padx=10)
    pipb = ttk.Progressbar(pitab, maximum=100)
    pipb.pack(fill="x", padx=8)
    pistatus = ttk.Label(pitab, text="Idle")
    pistatus.pack(anchor="w", padx=8)
    pitxt = tk.Text(pitab, font=("Consolas", 9), wrap="none", height=5)
    pitxt.pack(fill="both", expand=True, padx=8, pady=(2, 6))

    def pilog(m):
        pitxt.insert("end", m + "\n")
        pitxt.see("end")

    def pi_set_keys(keys):
        pkey.delete("1.0", "end")
        pkey.insert("1.0", "\n".join(keys))
        p_ssh.set(True)

    def pi_key_github():
        u = simpledialog.askstring("Get SSH key", "GitHub user name (your public keys are read from\n"
                                   "https://github.com/<name>.keys):", parent=root, initialvalue=pi_saved.get("gh_user", ""))
        if not u:
            return
        try:
            keys = pi_fetch_keys(u)
        except Exception as e:
            messagebox.showerror("Get SSH key", str(e))
            return
        pi_set_keys(keys)
        pi_saved["gh_user"] = u.strip()
        s_ = load_settings()
        s_.setdefault("pi", {})["gh_user"] = u.strip()
        save_settings(s_)
        pilog("Loaded %d public key(s) from github.com/%s" % (len(keys), u.strip()))

    def pi_key_local():
        try:
            k, how = pi_local_pubkey(True, pilog)
        except Exception as e:
            messagebox.showerror("SSH key", str(e))
            return
        pi_set_keys([k])
        pilog("Using " + how)

    def pi_opts():
        o = {"hostname": p_host.get().strip(), "username": p_user.get().strip(), "password": p_pass.get(),
             "wifi_ssid": p_ssid.get(), "wifi_pass": p_wpass.get(), "wifi_country": p_cc.get().strip(),
             "wifi_hidden": p_hid.get(), "timezone": p_tz.get().strip(), "keymap": p_km.get().strip(),
             "ssh": p_ssh.get(), "ssh_pw": p_sshpw.get(), "ssh_keys": pkey.get("1.0", "end").strip(),
             "spi": p_spi.get(), "i2c": p_i2c.get(), "serial": p_ser.get(), "onewire": p_ow.get()}
        return o

    def pi_save():
        s_ = load_settings()
        o = pi_opts()
        d = {k: o[k] for k in PI_SETTING_KEYS if k in o}      # passwords are never saved
        d["on"] = p_on.get()
        d["repo"] = p_repo.get().strip()
        d["gh_user"] = pi_saved.get("gh_user", "")
        s_["pi"] = d
        save_settings(s_)

    def pi_check_opts(o):
        if not p_on.get():
            return None
        if o["hostname"] and not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?", o["hostname"]):
            return "Hostname may only use letters, digits and hyphens."
        if o["password"] and not o["username"]:
            return "Enter a username for that password."
        if o["username"] and not o["password"] and not o["ssh_keys"]:
            return "Enter a password or an SSH key for that username (or leave the username empty)."
        if o["username"] and not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", o["username"]):
            return "Username must be lowercase letters/digits (start with a letter)."
        if o["wifi_ssid"] and o["wifi_pass"] and not (8 <= len(o["wifi_pass"]) <= 63):
            return "A Wi-Fi password must be 8-63 characters."
        if o["wifi_ssid"] and not re.fullmatch(r"[A-Za-z]{2}", o["wifi_country"]):
            return "Enter the 2-letter Wi-Fi country code (for example US)."
        return None

    # ---- OS list
    def pi_selected_node():
        sel = pitree.selection()
        n = pistate["nodes"].get(sel[0]) if sel else None
        if n is None and pistate["custom"]:
            return pistate["custom"]
        return n if (n and not pi_is_category(n)) else None

    def pi_fill(parent, nodes):
        for n in nodes:
            iid = pitree.insert(parent, "end", text=n.get("name", "?"),
                                values=(n.get("release_date", ""),
                                        fmt_size(int(n["image_download_size"])) if n.get("image_download_size") else ""))
            pistate["nodes"][iid] = n
            if pi_is_category(n):
                pitree.insert(iid, "end", iid=iid + "!dummy", text="...")

    def pi_rebuild():
        for i in pitree.get_children():
            pitree.delete(i)
        pistate["nodes"].clear()
        d = pistate["data"]
        if d:
            pi_fill("", [n for n in d["os_list"] if pi_visible(n, pistate["tags"])])

    def pi_open(_e=None):
        iid = pitree.focus()
        n = pistate["nodes"].get(iid)
        if not n or not pitree.exists(iid + "!dummy"):
            return
        pitree.delete(iid + "!dummy")
        if n.get("subitems") is not None:
            pi_fill(iid, pi_children(n, pistate["tags"]))
        else:
            ph = pitree.insert(iid, "end", iid=iid + "!wait", text="Loading...")
            tags = list(pistate["tags"])
            threading.Thread(target=lambda: piq.put(("kids", (iid, pi_children(n, tags, lambda m: piq.put(("log", m)))))), daemon=True).start()

    def pi_open_page():
        n = pi_selected_node()
        if n and n.get("page"):
            import webbrowser
            webbrowser.open(n["page"])
            pilog("Opened %s - save the .zip, then click 'Use own image file...' and choose it." % n["page"])

    def pi_pick(_e=None):
        if pitree.selection() and pistate["custom"]:
            pistate["custom"] = None
            picust.config(text="")
        n = pi_selected_node()
        pbtn_page.config(state="normal" if (n and n.get("page")) else "disabled")
        if n is None:
            pidesc.config(text="Pick an operating system (open a folder with the arrow).")
            return
        if n.get("page"):
            pidesc.config(text="%s\n%s\nThis one is downloaded from the project's web page (no direct link): click 'Open download "
                               "page', save the .zip, then click 'Use own image file...' and choose it." % (n.get("name", ""), n.get("description", "")))
            return
        fm = n.get("init_format") or ("none" if not n.get("local") else "detected after writing")
        setup = "supports first-boot setup" if fm in ("cloudinit", "cloudinit-rpi", "systemd") else \
            ("setup is applied if the image supports it" if n.get("local") else "no first-boot setup for this image")
        pidesc.config(text="%s\n%s  [%s]" % (n.get("name", ""), n.get("description", ""), setup))

    def pi_load():
        pisrc.config(text="Updating...")
        custom = p_repo.get().strip()
        pi_save()
        _PI_SUB_CACHE.clear()

        def w():
            try:
                piq.put(("repo", pi_load_repo(None, lambda m: piq.put(("log", m)), custom)))
            except Exception as e:
                piq.put(("log", "ERROR: %s" % e))
                piq.put(("repo", None))
        threading.Thread(target=w, daemon=True).start()

    def pi_model(_e=None):
        i = picombo.current()
        pistate["tags"] = pistate["devs"][i][1] if 0 <= i < len(pistate["devs"]) else []
        pi_rebuild()

    def pi_pick_custom():
        f = filedialog.askopenfilename(title="Image to write", filetypes=[
            ("Disk images", "*.img *.iso *.xz *.gz *.zip *.zst"), ("All files", "*.*")])
        if f:
            pistate["custom"] = {"name": os.path.basename(f), "local": f, "description": "Your own image file"}
            picust.config(text="Using: " + f)
            pitree.selection_set(())
            pi_pick()
        else:
            pistate["custom"] = None
            picust.config(text="")

    def pi_dev():
        sel = pdcombo.get().strip()
        for d in drives:
            if d[1] == sel:
                return d[0]
        return None

    def pi_busy(b):
        pistate["running"] = b
        for w_ in (pbtn_write, pbtn_apply):
            w_.config(state="disabled" if b else "normal")
        pstop_btn.config(state="normal" if b else "disabled")

    def pi_start(kind):
        if pistate["running"]:
            return
        dev = pi_dev()
        o = pi_opts()
        err = pi_check_opts(o)
        if err:
            messagebox.showwarning("Pi", err)
            return
        if not dev:
            messagebox.showwarning("Pi", "Select the storage (SD card) first.")
            return
        node = pi_selected_node()
        if kind == "apply":
            boot = dev[:2] + "\\" if IS_WIN else dev
            if not p_on.get() or not os.path.isdir(boot) or not pi_detect_format(boot):
                messagebox.showwarning("Pi", "Tick 'Apply this setup' and select the card's boot drive "
                                       "(the small FAT32 one that contains cmdline.txt).")
                return
            if not messagebox.askyesno("Pi", "Write the first-boot setup onto %s ?" % boot):
                return
            pi_save()
            pitxt.delete("1.0", "end")
            try:
                pi_write_boot_files(boot, o, node.get("init_format") if node else None, pilog)
            except Exception as e:
                pilog("ERROR: %s" % e)
            return
        if node is None:
            messagebox.showwarning("Pi", "Pick an operating system first (or use your own image file).")
            return
        if node.get("page"):
            if messagebox.askyesno("Pi", "This image is downloaded from the project's web page.\n\nOpen the page now? "
                                   "Save the .zip, then click 'Use own image file...' and choose it."):
                pi_open_page()
            return
        try:
            info = resolve_disk(dev[:1])
        except Exception as e:
            messagebox.showerror("Pi", str(e))
            return
        if not info["safe"]:
            messagebox.showerror("Pi", f"Refusing: disk {info['number']} is not a removable/USB/SD disk "
                                 f"(bus: {info['bus']}, system disk: {info['system']}).")
            return
        if node.get("extract_size") and int(node["extract_size"]) > (info["size"] or 0):
            messagebox.showerror("Pi", "This image is larger than the card. Nothing was written.")
            return
        ans = simpledialog.askstring(
            "Confirm WRITE",
            f"ALL DATA on disk {info['number']} will be destroyed:\n"
            f"  {info['model']}  {fmt_size(info['size'])}  volumes {', '.join(info['letters'])}\n"
            f"Image: {node.get('name')}\n\nType the drive letter ({dev[0]}) to confirm:")
        if not ans or ans.strip().upper().rstrip(":") != dev[0].upper():
            return
        pi_save()
        pitxt.delete("1.0", "end")
        pistop.clear()
        pi_busy(True)
        verify = p_verify.get()
        setup_on = p_on.get()

        def work():
            lg = lambda m: piq.put(("log", m))
            pg = lambda f_, s_: piq.put(("prog", (f_, s_)))
            tmp = None
            try:
                tmp = pi_prepare_image(node, lg, pg, pistop)
                ok = write_image(tmp, info["path"], info["letters"], verify, lg, pg, pistop)
                if not ok:
                    lg("Write finished with errors - the card may be faulty or fake. Run the Test tab.")
                else:
                    if setup_on:
                        lg("Waiting for the boot partition to appear...")
                        boot = pi_find_boot(info["number"], 40, lg)
                        if boot:
                            pi_write_boot_files(boot, o, node.get("init_format"), lg)
                        else:
                            lg("Could not find the boot partition. Unplug and re-insert the card, then use "
                               "'Apply setup only'.")
                    lg("DONE. Eject the card (Eject button on the right) and put it in the Pi.")
            except Stopped:
                lg("Stopped by user.")
            except Exception as e:
                lg("ERROR: %s" % e)
            finally:
                if tmp and os.path.isfile(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            piq.put(("done", None))
        threading.Thread(target=work, daemon=True).start()

    def pi_poll():
        try:
            while True:
                k, v = piq.get_nowait()
                if k == "log":
                    pilog(v)
                elif k == "prog":
                    pipb["value"] = v[0] * 100
                    pistatus.config(text=f"{v[1]}... {v[0] * 100:.0f}%")
                elif k == "repo":
                    if v is None:
                        pisrc.config(text="Could not load the list - check your internet")
                    else:
                        pistate["data"], src = v
                        pistate["devs"] = pi_device_choices(v[0])
                        picombo["values"] = [n for n, _ in pistate["devs"]]
                        picombo.current(0)
                        pisrc.config(text="updated %s from %s" % (time.strftime("%H:%M"), re.sub(r"^https?://([^/]+)/.*", r"\1", src)))
                        pi_model()
                elif k == "kids":
                    iid, kids = v
                    if pitree.exists(iid + "!wait"):
                        pitree.delete(iid + "!wait")
                    pi_fill(iid, kids)
                else:
                    pi_busy(False)
                    pistatus.config(text="Finished")
        except queue.Empty:
            pass
        root.after(150, pi_poll)

    picombo.bind("<<ComboboxSelected>>", lambda e: (pi_model(), picombo.selection_clear()))
    pitree.bind("<<TreeviewOpen>>", pi_open)
    pitree.bind("<<TreeviewSelect>>", pi_pick)
    pi_poll()
    root.after(400, pi_load)


    # ---------------- Devices panel (right) + themes ----------------
    settings = load_settings()
    theme0 = settings.get("theme") or ("Black" if settings.get("dark") else "Light")
    theme0 = LEGACY_THEMES.get(theme0, theme0)
    theme_var = tk.StringVar(value=theme0 if theme0 in THEMES else "Light")
    style = ttk.Style()
    orig_theme = style.theme_use()
    text_widgets = [txt, rtxt, itxt, atxt, ptxt, pitxt, pkey]
    warn_labels = [warn, iwarn, piwarn]
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
        for c in (combo, rcombo, icombo, pdcombo, picombo, tcombo):               # drop-down list colours
            try:
                c.tk.eval("set pd [ttk::combobox::PopdownWindow %s]; $pd.f.l configure -background %s "
                          "-foreground %s -selectbackground %s" % (c, pal["field"], pal["fg"], pal["accent"]))
            except tk.TclError:
                pass
        settings = load_settings()
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
                                 text="Disk %s  %s%s" % (d.get("Number"), d.get("Name") or "", "  (offline)" if d.get("Offline") else ""),
                                 values=(d.get("Bus", ""), "%.1f GB" % ((d.get("Size") or 0) / 1e9)))
            for v in d.get("Volumes") or []:
                tree.insert(top_id, "end", iid="v%s" % v.get("Letter"), tags=(tag,),
                            text="%s:  %s" % (v.get("Letter"), v.get("Label") or "(no label)"),
                            values=(v.get("FS") or "", "%.1f / %.1f GB" % ((v.get("Free") or 0) / 1e9, (v.get("Size") or 0) / 1e9)))

    def apply_drives(new):
        nonlocal drives
        old = {d[1]: d[0] for d in drives}
        sel = {c: old.get(c.get()) for c in (combo, rcombo, icombo, pdcombo)}
        drives = new
        vals = [d[1] for d in drives]
        for c in (combo, rcombo, icombo, pdcombo):
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
                for c in (combo, rcombo, icombo, pdcombo):
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
    tmenu.add_command(label="Set offline / online", command=lambda: (nb.select(ptab), follow_disk(tree_disk(), True), root.after(600, lambda: cmd_online(None))))
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
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("2pct.SDinfo")   # own taskbar icon
        except Exception:
            pass
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


ICON_PNG_B64 = """
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
UilZkM7Iu1vaZbi+QUJHS5hISui6ErgJCRxXAu1GnxNJCbI5KWfrROpyclcmG50pSsnxqZTsuP69Is3t4qWy4mdyIpms/LalVU5o
apInm9vEpjLipTLipzJiMzl5LpWWLAhaSUYpuaJjsgzc90cxS46RIFcvXjot4rryy3RGEkqJBtFKidZatIoegEzsmCLLz3yVHHvC
ybL8jHPkg/98o0xoaxOchJyarZO9GhGFeI4jHoTy2tdJ16suePj1cN2XWtuvBLjr7/fqf9PiqxtnzZpYX19/0v2z5tws175d/GQq
8JSSsuuKnHuOfG/KVJkcL/41V10jn7jls7LstHPktZe/SU44abk4jjO2+FoJWktWKXnv5Cni/+Z34rd1SJDKSJhJS1hZ9GRSgkRC
woQrvtYi2ZzcPnO2NCYSUkO5FkAckHubWkVSafG0I6GTkNCNH44roRMbgeNK2XFEkgn5frZOUEpckJtOOEnk7FeKBxJmc2KSaRlN
pmSeUgLID2bMEGlqEc9Nip9MiaQzsiKRlBSI6zpyNMjKn/9c5JprxUulxc/mRLSWbemszKxcu1LiaC2u64rrupEh6MgIWidMlFNO
P0eWnnCynHz6OXLDez4gzY2NopNpuSCTlUGQUCnxHEd8COTNV8mqI4786ZSMe8KHWlvr/7Oxnf6b2Tuxw3qBcP6HCuUjzjj/gg+a
P91nxfccESF17DH8Ydduvtg/SFcpz6Wvu4Rps+fz4COPMmlSB3v37GLls09ijcHROsbpIwRukQivv/ZtJH59D6bvQEQHCeMoP2bo
KrFYa3GB55taeNe+PQwHAVpFFT1dybkBPXs25OqidFDV3o9Kfm8j4o21oDS7deSKJyjFq6fPgNWrwHExYYgWyypj2RGfl9PbJ0WZ
t8QIgAj7rcVzHCaGhg988EMc2z+M98tf4iSTKK+Ml0jyfmvZbUz0fpVCOxqtVbUEDREW0d/bzaYN60il0owMD7Nu/QZe/09vJoHh
jwIfSqZQMUaBUm7w67vNMccf/8YvpRrOftr3T/9qlGXyjzYAdQvYExcvbt+0a2/p+ktf9/7EujU5s28vAio1dx6rCmVu2dPFtnKB
05efxpLjlvGXBx9kYvtEDuzfw/PPPR1RrrSOLjoOuLLGcOKkDo6aOp3wV3fhOAq8MhIESBAiQYiNyRvGWCTXwJdLRQbCMIof4qjf
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
"""


if __name__ == "__main__":
    main()
