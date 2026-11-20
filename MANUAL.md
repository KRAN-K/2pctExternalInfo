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
4. **Start it by double-clicking `SDCardChecker.py`.** The console window hides itself, and Windows asks for administrator rights (needed for recovery and the imager). Click **Yes**. If you click No, the Test tab still works but recovery and imaging will say access denied.
   - If double-clicking opens the file in an editor, right-click it, choose Open with, then Python (tick Always use this app).
   - Manual start from a terminal: `python SDCardChecker.py` (add `--no-admin` to skip the administrator prompt).
5. Optional: right-click `SDCardChecker.py`, Send to, Desktop (create shortcut).

## 3. Preparing the card

1. Insert the card and wait for a drive letter (for example `E:`).
2. Close programs that use it.
3. Make sure the lock switch is not locked.
4. Use a reader plugged directly into the PC, not through a hub.

## 3a. The window: devices panel and dark mode

- **Available devices (right side):** lists every disk and volume in the PC with bus type, free space and size, and updates by itself every few seconds when you insert or remove a card. **Green** is a removable or USB disk (safe to write), **red** is your system disk. Click a device and it becomes the selected device in all tabs. **Refresh now** forces an update.
- **Dark mode:** tick the box at the top right of the devices panel. The choice is remembered in `.sdcardchecker.json` in your user folder.

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
4. Start the program (double-click `SDCardChecker.py`) and click **Yes** on the administrator prompt. Raw card reads need admin rights.

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

## 8. Disk Imager tab (like Win32 Disk Imager)

Read a whole card to an image file, write an image back to a card (for example a Raspberry Pi OS image), verify, and hash.

**Safety rules built in**
- Only removable, USB and SD disks can be written. Your system and boot disks are refused.
- You must type the card's drive letter to confirm a write.
- An image larger than the card is refused before anything is written.
- Volumes on the card are locked and dismounted before writing. Close Explorer windows on the card first.

**Read card to image (backup)**
1. Choose the **Device**, then click **Save as...** and pick a file on a different drive.
2. Leave **Read whole disk** ticked to copy every partition (needed for Pi cards). Untick it to copy only the selected volume.
3. Click **Read card to image**. Unreadable areas are zero-filled and counted.

**Write image to card (flash)**
1. Click **Open...** and pick the `.img`, `.iso`, `.bin` or `.dd` file. Compressed files (`.zip`, `.xz`, `.gz`) must be extracted first.
2. Choose the **Device**. Check the drive letter and size twice.
3. Leave **Verify after write** ticked.
4. Click **Write image to card**, read the warning, type the drive letter and confirm.
5. When it finishes, Windows may ask to format the new partitions. Click Cancel. Eject the card.

**Verify:** compares the image with the card and reports the first differing sector. A failure on a fresh write often means a faulty or fake card; run the Test tab.

**Hash image:** shows MD5, SHA-1 and SHA-256 so you can compare with the download page.

Command line:

```
python SDCardChecker.py --image E:\ D:\Claude\card.img --whole-disk
python SDCardChecker.py --write-image D:\Claude\pi.img E:\
python SDCardChecker.py --verify D:\Claude\pi.img E:\
python SDCardChecker.py --hash D:\Claude\pi.img
```

Add `--yes` to skip the typed confirmation and `--no-verify` to skip verification after a write.

## 9. Command line

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

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `python` not recognized | Reinstall Python with Add to PATH ticked, open a new Command Prompt |
| `No module named tkinter` | Re-run the Python installer, Modify, enable tcl/tk and IDLE |
| Card not listed | Click Refresh, check Disk Management for a drive letter, or use Browse folder |
| Device details show n/a | Some readers hide them. Try a different reader or run as administrator |
| Access denied in recovery or imager | Start the program again and click Yes on the administrator prompt |
| Cannot lock the card when writing | Close Explorer windows, backup tools and anything using the card, then retry |
| Write error at the start | Check the lock switch, free space and read-only state |
| Write error partway | The card is failing or was removed |
| Very slow speeds | Try another USB port or reader, avoid hubs and USB 2.0 readers |
| Leftover `SDCHK_*.bin` | Delete them manually |

## 11. Limits

- SD cards have no S.M.A.R.T. data. USB readers usually hide the CID/CSD registers.
- Quick mode cannot prove full advertised capacity. Only Full can.
- Speed depends on the reader and port as well as the card.
- A pass is strong evidence for today, not a guarantee. Keep backups.

## 12. Quick-start checklist

1. Install Python with Add to PATH.
2. Copy `SDCardChecker.py` to `D:\Claude`.
3. Insert the card and run the program.
4. Click Card info only, then run Quick, then Full on new or suspicious cards.
5. Read the score and verdict and save the report.
6. Deleted something? Stop using the card, run as administrator, and use the Recover tab.
