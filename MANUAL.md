# SD Card Checker: Installation and User Manual

For `SDCardChecker.py` on Windows 10/11. Tests micro SD cards and USB drives for real capacity, integrity, speed and stability, and recovers accidentally deleted files.

## 1. What you need

- Windows 10 or 11
- A micro SD card and a reader, or a USB drive
- Python 3.9 or newer
- `SDCardChecker.py`
- A backup of the card before running the Full test

## 2. Installation

1. **Check Python:** press Win+R, type `cmd`, run `python --version`. If it shows 3.9 or higher, skip to step 3.
2. **Install Python:** download from python.org/downloads. On the first screen tick **Add python.exe to PATH**, click Install Now, then confirm with `python --version` in a new Command Prompt. Tkinter is included.
3. **Place the file:** create `D:\Claude` and copy `SDCardChecker.py` into it.
4. **Start it:**
   ```
   cd /d D:\Claude
   python SDCardChecker.py
   ```
5. Optional shortcut target: `pythonw.exe "D:\Claude\SDCardChecker.py"` (no console window).

## 3. Preparing the card

1. Insert the card and wait for a drive letter (for example `E:`).
2. Close programs that use it.
3. Make sure the lock switch is not locked.
4. Use a reader plugged directly into the PC, not through a hub.

## 4. Test and Info tab

1. Select the card in the **Card / drive** list (removable drives first). Click Refresh after inserting.
2. Click **Card info only** to see label, filesystem, sizes, serials, model, firmware, bus type, sector sizes, partition style, health and write-protect state.
3. Choose a mode:

| Mode | Writes | Time | Finds |
|---|---|---|---|
| Quick | 512 MB of free space | 1-5 minutes | Bad cards, corruption, stalls, speed |
| Full | All free space | Minutes to hours | Everything in Quick plus fake capacity |

4. Click **Start test**. Phases: Writing, Verifying, random 4K. Do not remove the card. **Stop** ends it and removes the test files.
5. Click **Save report...** to keep the result.

USB flash drives work the same way. Ignore the SD speed class line for USB drives.

## 5. Safety notes

- The test only writes into free space and never changes existing files.
- Test files are named `SDCHK_*.bin` and deleted when the test ends, fails or is stopped. Delete leftovers manually if the program crashed.
- A Full test writes the card heavily. Back up first if the data matters.
- **If you want to recover deleted files, do not run the test.** It writes into the space where deleted files live.

## 6. Reading the results

| Line | Meaning |
|---|---|
| Bad blocks | 1 MB blocks that did not match. Should be 0 |
| Sequential write / read | Large-file speed in MB/s |
| Random 4K write / read | Small-file IOPS. Read is often cache-inflated |
| Write stalls | 1 MB writes slower than 0.5 s. Should be 0 |
| Speed variability | Below about 25% is healthy |

| Score | Verdict | Action |
|---|---|---|
| 90-100 | EXCELLENT, stable | Safe to use |
| 75-89 | GOOD, stable | Safe for normal use |
| 55-74 | FAIR | Non-critical data only |
| below 55 | POOR | Do not trust |
| 0, bad blocks | FAILING, DATA CORRUPTION | Replace |
| 0, wrap-around | FAKE CAPACITY | Return or discard. The report estimates the real size |

## 7. Recovering accidentally deleted files

The **Recover deleted files** tab scans the card read-only and rebuilds deleted files from their internal signatures.

### Do this first

1. **Stop using the card immediately.** New writes can permanently overwrite deleted files.
2. **Do not format** the card and **do not run the test**.
3. Put the card in a PC reader.
4. Start the program as **administrator** (right-click Command Prompt or PowerShell, Run as administrator, then `python D:\Claude\SDCardChecker.py`). Raw card reads need admin rights.

### Steps

1. Open the **Recover deleted files** tab.
2. Choose the card as **Source**, or click **Use image file...** to use a saved image.
3. Choose **Save recovered to** on a **different drive** (default `D:\Claude\Recovered`). The program refuses to save onto the card.
4. Tick the file groups you want.
5. Leave **Skip files that still exist on the card** ticked to get only deleted files.
6. Optional and safest: click **Make disk image first**, save the image on another drive, then recover from it.
7. Click **Scan and recover**.
8. Open the output folder. Files are sorted by group, and `recovery_report.csv` lists each file.

### Supported types

| Group | Types |
|---|---|
| Photos | JPG, PNG, GIF, BMP |
| Documents | PDF, DOCX, XLSX, PPTX, ODT, ZIP, APK |
| Video | MP4, MOV, HEIC, 3GP, M4A |
| Audio/Video | WAV, AVI |
| Other | 7z, SQLite |

### Limits

- File names and folders are lost. Files are named like `rec_00012_at340MB.jpg`.
- Overwritten data is gone for good.
- Fragmented files may fail. Files that cannot be validated are skipped.
- A quick format usually leaves data in place. A full format or secure erase does not.
- For failing cards, make an image first. Unreadable areas are zero-filled.
- Hardware-encrypted or physically dead cards cannot be recovered.

## 8. Command line

```
python SDCardChecker.py --cli E:\ --mode quick --size 512 --report D:\Claude\report.txt
python SDCardChecker.py --cli E:\ --mode full
python SDCardChecker.py --image E:\ D:\Claude\card.img
python SDCardChecker.py --recover D:\Claude\card.img --out D:\Claude\Recovered
python SDCardChecker.py --recover E:\ --out D:\Claude\Recovered --types Photos,Documents
```

| Option | Meaning |
|---|---|
| `--cli PATH` | Run the test without a window |
| `--mode quick\|full` | Test size |
| `--size MB` | Megabytes for quick mode |
| `--report FILE` | Save the report |
| `--image SRC DEST` | Sector-by-sector copy of the card |
| `--recover SRC` | Card, drive letter or image to scan |
| `--out FOLDER` | Recovery output folder (different drive) |
| `--types` | Photos, Documents, Video, Audio_Video, Other |
| `--keep-existing` | Also recover files that still exist |

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `python` not recognized | Reinstall Python with Add to PATH ticked, open a new Command Prompt |
| `No module named tkinter` | Re-run the Python installer, Modify, enable tcl/tk and IDLE |
| Card not listed | Click Refresh, check Disk Management for a drive letter, or use Browse folder |
| Device details show n/a | Some readers hide them. Try a different reader or run as administrator |
| Access denied in recovery | Start the program as administrator |
| Write error at the start | Check the lock switch, free space and read-only state |
| Write error partway | The card is failing or was removed |
| Very slow speeds | Try another USB port or reader, avoid hubs and USB 2.0 readers |
| Leftover `SDCHK_*.bin` | Delete them manually |

## 10. Limits

- SD cards have no S.M.A.R.T. data. USB readers usually hide the CID/CSD registers.
- Quick mode cannot prove full advertised capacity. Only Full can.
- Speed depends on the reader and port as well as the card.
- A pass is strong evidence for today, not a guarantee. Keep backups.

## 11. Quick-start checklist

1. Install Python with Add to PATH.
2. Copy `SDCardChecker.py` to `D:\Claude`.
3. Insert the card and run the program.
4. Click Card info only, then run Quick, then Full on new or suspicious cards.
5. Read the score and verdict and save the report.
6. Deleted something? Stop using the card, run as administrator, and use the Recover tab.
