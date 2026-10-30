# Changelog

Each release's notes come from its section here (packaging/release-notes.sh).
Releases before 5.5.0 are listed on the GitHub releases page.

## 5.7.0

### Fixes that matter for flashing

- **RK3576 and other NEWIDB chips boot after a full `update.img` flash.** The flash reported success, but the board came back in Maskrom: rkdeveloptool's `ul` writes the bootloader in a layout these chips' boot ROM rejects. The app now builds the boot image itself and writes it at sector 0x40. Raw images such as Armbian carry their own bootloader and weren't affected.
- **A full flash no longer fails on its first step** when you had already answered Yes to "load the Loader now?". A running Loader refuses a second one, and the flash gave up after three tries. It now skips that step; the image's own Loader still goes onto the board.
- **Multi-step jobs no longer stop halfway with no error.** When one step started the next one right away, the next step's follow-up was lost. This stopped the production line before the reset, and could skip the read-back after a large write.
- After loading the Loader, the app waits until the board answers before writing. Writing straight away was refused for a second or two.
- The storage size in the pre-flight check was always "unknown" on a real board. It's now read correctly.
- In Maskrom, the chip is known from the USB ID before any Loader runs, so **Get Loader for This Chip** works when it's most needed. Older chips (RK3368, RK3399, …) now show their product name instead of an internal number.
- Change Storage asks first; switching to storage the board doesn't have leaves every read and write failing. Erasing everything is one button with one confirmation.

### New

- **Safer flashing**
  - Before a full flash or Import GPT overwrites the partition table, the old one is saved as a parameter file. Import GPT restores it.
  - Before decompressing or unpacking, the app checks that the disk has room, instead of failing part-way through.
  - A full `update.img` flash can read every partition back and compare it with the image.
  - When a flash is done, **Reset Board** boots the new system straight away.
- **History** tab: every flash with its time, chip, image, result and duration. **Flash Again** puts the image back; right-click for details or to delete one.
- **Production line**: flash the same image onto boards one after another. Plug in a board in Maskrom, and it gets its Loader, the write, an optional read-back and a reset; then plug in the next. It replaces the old mass production, which couldn't work: rkdeveloptool refuses to run with more than one board connected.
- **For newcomers**
  - A first-run guide checks the setup (rkdeveloptool, and the USB rule on Linux), sets the language and theme, and shows how a flash goes.
  - **How do I get into Maskrom?** explains the button, `sudo reboot loader`, boards without a button, and what to check when nothing shows up.
  - **Search** (⌘K on macOS, Ctrl+K elsewhere, or the button in the status bar) finds any button or setting by its name in either language, or by everyday words like "flash", "backup" or "救砖", then takes you to it and highlights it.
- **Updates and installing**
  - The app updates itself on macOS and Linux (DMG, AppImage, deb, rpm): download, check against GitHub's SHA-256, install, restart.
  - One-line install: `curl -fsSL https://raw.githubusercontent.com/gahingwoo/RKDevelopTool-GUI/main/install.sh | sh`. It picks the right package for the system and checks it the same way.
  - Homebrew: `brew trust gahingwoo/tap && brew install --cask gahingwoo/tap/rkdeveloptool-gui`.
  - The DMG shows an Applications folder to drag onto, and how to get past the first-launch warning.
- **Report a Problem** opens a GitHub issue with the board, the environment and the end of the log filled in. You see and can edit everything before it's sent, and your home folder and user name are left out.
- A desktop notification when a flash ends while the app is in the background, and progress on the Dock icon.

### Smaller changes

- The Parameters tab's options (verify, erase before writing, reset after writing, timeout, retries) now take effect. Before, nothing read them.
- Partitions can be erased from their row in the partition table. Sizes read "4.00 MB" instead of `0x2000` sectors.
- Dialog titles, the `update.img` details and the Yes/No buttons are translated in the Chinese UI.
- Buttons whose name doesn't say what they do, or what they risk, have tooltips. Status colours suit light and dark themes. Ctrl+1…9 switch tabs.
- At the default window size, every tab fits beside the left panel again.

**Full Changelog**: https://github.com/gahingwoo/RKDevelopTool-GUI/compare/5.6.1...5.7.0

## 5.6.1

### Fixes

- Writes no longer fail on boards such as the RK3576 with "Write LBA failed!". To list storage types, the app used to switch the Loader's storage target with `cs`, and the board then refused every read and write. It now offers eMMC, SD card and SPI NOR without switching anything.
- The chip shows as a name (RK3576) instead of the raw bytes from `rci`.
- Reading the partition table no longer fails because the app was talking to the board in the background at the same time.
- Import GPT writes a `parameter.txt` with `rkdeveloptool gpt`, and Export GPT saves the board's partition table as one.
- When a read-back after a write doesn't match, the app checks whether the Loader just can't read that part of the storage back (it returns filler) and says the write couldn't be verified, instead of calling it bad.

### New

- **Get Loader for This Chip** on the Firmware Download tab builds the Loader for the connected chip from Rockchip's rkbin repository and fills in the Loader field. rkbin has the parts but no ready-made Loader; the app downloads them and puts them together.
- The progress row stays at the bottom of the window instead of scrolling away with a long tab.
- Releases include a Python wheel.

**Full Changelog**: https://github.com/gahingwoo/RKDevelopTool-GUI/compare/5.6.0...5.6.1

## 5.6.0

### Flashing

- The burn confirmation now checks the write first: is a device connected, is a Loader loaded, does the image suit the address, and does it fit in the storage. If a check fails, the write doesn't start. If the storage size can't be read, that line says unknown rather than passed.
- Progress covers the whole write, with the speed over the last few seconds and the time left. A full `update.img` flash shows its step ("[3/9] …") but uses one bar for the whole flash instead of restarting at each step.
- You can cancel a write, a full flash, or decompressing an image. Cancelling a write asks first, and afterwards tells you the board needs flashing again.
- For raw and compressed images you can tick "Read back and verify": after writing, the app reads the data back and compares it with the image.
- If the board disconnects mid-write, the app stops and tells you how to recover it from Maskrom.
- The app no longer opens the device in the background while rkdeveloptool is writing to it.

### When something fails

- For the common rkdeveloptool errors (no device, can't open the device, wrong Loader, write failed and a few more) the app says what probably went wrong and what to try. rkdeveloptool's own output is under Show Details.

### Linux

- The `.deb` and `.rpm` install a udev rule, so you don't need `sudo` to reach the board. With the AppImage or pip, the app gives you a one-line command to install the rule when it's missing.

### Settings and everyday use

- A new Settings tab (Cmd+, on macOS, Ctrl+, elsewhere) holds the style, theme, language, interface and log text size, which rkdeveloptool to use, a default Loader, where to decompress images, debug logging and the update check.
- You can drop a firmware or Loader file onto the window and it lands in the right field. A Loader dropped on a firmware field goes to the Loader field instead, and a file the app can't identify is refused with a hint.
- The command bar runs commands now: type or edit rkdeveloptool arguments and press Enter. Up and Down recall earlier commands, and anything that writes or erases asks first.
- The version in the bottom-right corner reads "Check for updates", and the check no longer fails with a certificate error on python.org Python.

### Fixes

- The macOS style uses the system's own colours, and light or dark follows your choice.
- The theme picker stays on "Auto" in auto mode, so you can switch back to a fixed theme.
- The progress row no longer overlaps the log, and the Home tab no longer has an empty band under it.
- Import GPT and Unpack use the file in their field instead of always asking for one.
- Switching tabs or changing the text size no longer makes the window flicker.

**Full Changelog**: https://github.com/gahingwoo/RKDevelopTool-GUI/compare/5.5.0...5.6.0

## 5.5.0

### Flashing

- Compressed distro images (`.img.xz`, `.img.gz`, `.img.bz2`) can be flashed directly. They are decompressed next to the original file first and the copy is deleted afterwards. Before, an archive picked through "All files" was written to the board as-is: the flash reported success and the board didn't boot. zstd, zip and 7z archives are now refused with a message instead.
- RKFW `update.img` firmware larger than 4 GiB is extracted in full. Before, the rootfs was cut to its size modulo 4 GiB. (#22 by @yejingx, #25)
- In Maskrom mode the Loader is loaded with `db` without asking. In Loader mode, the db/ul dialog now explains what each choice does.

### Updates

- The version is shown in the bottom-right corner; click it to check for a newer release. The app also checks by itself at most once a day and only changes that label, without a pop-up. You can turn the automatic check off in the update dialog.

### Fixes

- The English "load Loader now?" prompt no longer ends with a line in Chinese.
- Accepting that prompt no longer marks the Loader as loaded before it has actually loaded.
- Closing the window right after it opened could crash the app on exit.

### Known issue

- On Python installed from python.org (running from source or via pip), the update check fails with a certificate error unless that Python's "Install Certificates.command" has been run. Fixed for the next release.

**Full Changelog**: https://github.com/gahingwoo/RKDevelopTool-GUI/compare/5.4.0...5.5.0
