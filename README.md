# 2%SDinfo v1.5

A single-file Windows tool (Python 3.9+, standard library only) that checks micro SD cards and USB drives, and can recover accidentally deleted files.

- **Card info:** label, filesystem, size, serial, model, firmware, bus type, sector sizes, partition style, health, write-protect.
- **Integrity test:** H2testw-style write and read-back of unique data. Detects fake capacity, bad blocks and silent corruption.
- **Speed test:** sequential MB/s, random 4K IOPS, write stall detection.
- **Stability score:** 0-100 with a verdict.
- **Devices panel and dark mode:** the right side lists every disk and volume live; click one to select it in all tabs. Five themes (Light, Dark, Dark Gray, Crimson Eclipse, Deep Ocean) from a dropdown, remembered between launches.
- **Partitions (AOMEI-style):** disk map, format (including FAT32 above 32 GB), create, delete, resize NTFS, label, drive letter, initialize MBR/GPT, clean, wipe, eject. Removable/USB/SD disks only.
- **Eject:** button and right-click menu in the devices panel.
- **Disk Imager:** read a card to an image, write an image to a card with verification, compare, and hash (MD5, SHA-1, SHA-256), with safety locks.
- **Recover deleted files:** read-only signature carving for JPG, PNG, GIF, BMP, PDF, DOCX/XLSX/PPTX, ZIP, MP4/MOV/HEIC, WAV/AVI, 7z and SQLite.

See [MANUAL.md](MANUAL.md) for the full installation and usage guide.

## Quick start

Double-click **`2pctSDinfo_v1.5.py`** (needs Python 3.9+ with Tkinter, from python.org with "Add to PATH" ticked). The console hides itself and Windows asks for administrator rights, which recovery and the imager need.

Or from a terminal:

```
python 2pctSDinfo_v1.5.py
```

Add `--no-admin` to skip the administrator prompt.

Command line:

```
python 2pctSDinfo_v1.5.py --cli E:\ --mode quick --report report.txt
python 2pctSDinfo_v1.5.py --image E:\ D:\Claude\card.img
python 2pctSDinfo_v1.5.py --recover D:\Claude\card.img --out D:\Claude\Recovered
python 2pctSDinfo_v1.5.py --format E:\ --fs FAT32 --label MYCARD
python 2pctSDinfo_v1.5.py --eject E:\
```

## Versions

Versions are written v1.0, v1.1, v1.2, v1.3 ... The current file is `2pctSDinfo_v1.5.py`. To release a new version: change `APP_VERSION`, add an entry at the top of `CHANGELOG` (it appears on the About tab), rename the file to match, and update the docs. Extra About-tab sections can be added to `ABOUT_EXTRA`.

| Version | Highlights |
|---|---|
| v1.5 | Partitions tab (format, create, delete, resize, wipe), FAT32 above 32 GB, Eject |
| v1.4 | Theme dropdown: Dark Gray, Crimson Eclipse (black and red), Deep Ocean |
| v1.3 | Renamed 2%SDinfo, About tab, dark mode, live devices panel |
| v1.2 | Disk Imager (read, write, verify, hash) with safety locks |
| v1.1 | Deleted-file recovery |
| v1.0 | Card info, integrity and speed tests, stability score |

## Tests

`tests/make_test_image.py` builds a disk image containing 10 real files of different types among random data. Run the recovery against it and compare hashes to verify carving.

## Warning

If you want to recover deleted files, stop using the card first and do not run the integrity test. It writes to free space and can overwrite deleted data.
