# SD Card Checker

A single-file Windows tool (Python 3.9+, standard library only) that checks micro SD cards and USB drives, and can recover accidentally deleted files.

- **Card info:** label, filesystem, size, serial, model, firmware, bus type, sector sizes, partition style, health, write-protect.
- **Integrity test:** H2testw-style write and read-back of unique data. Detects fake capacity, bad blocks and silent corruption.
- **Speed test:** sequential MB/s, random 4K IOPS, write stall detection.
- **Stability score:** 0-100 with a verdict.
- **Disk Imager:** read a card to an image, write an image to a card with verification, compare, and hash (MD5, SHA-1, SHA-256), with safety locks.
- **Recover deleted files:** read-only signature carving for JPG, PNG, GIF, BMP, PDF, DOCX/XLSX/PPTX, ZIP, MP4/MOV/HEIC, WAV/AVI, 7z and SQLite.

See [MANUAL.md](MANUAL.md) for the full installation and usage guide.

## Quick start

Double-click **`SDCardChecker.bat`**. It starts the app, asks for administrator rights (needed for recovery) and installs Python with winget if it is missing. Keep it in the same folder as `SDCardChecker.py`.

Or from a terminal:

```
python SDCardChecker.py
```

Add `--no-admin` to skip the administrator prompt.

Command line:

```
python SDCardChecker.py --cli E:\ --mode quick --report report.txt
python SDCardChecker.py --image E:\ D:\Claude\card.img
python SDCardChecker.py --recover D:\Claude\card.img --out D:\Claude\Recovered
```

## Tests

`tests/make_test_image.py` builds a disk image containing 10 real files of different types among random data. Run the recovery against it and compare hashes to verify carving.

## Warning

If you want to recover deleted files, stop using the card first and do not run the integrity test. It writes to free space and can overwrite deleted data.
