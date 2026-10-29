# Changelog

Each release's notes come from its section here (packaging/release-notes.sh).
Releases before 5.5.0 are listed on the GitHub releases page.

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
