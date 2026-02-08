# RKDevelopTool GUI

[中文](readme.zh.md) | English

RKDevelopTool GUI is a graphical front-end for Rockchip's official rkdeveloptool. It provides an intuitive interface to perform firmware flashing, partition management, and device debugging tasks without using the command line.

**GitHub:** https://github.com/gahingwoo/RKDevelopTool-GUI

![App Screenshot](images/home_en.png)  
*RKDevelopTool GUI Main Interface*

## Features

**Device Monitoring** - Automatically detects connected Rockchip devices and displays their current mode (Maskrom or Loader).

**One-Click Firmware Flashing** - Simplifies the firmware flashing process. Just select your update.img file and click to begin.

**Partition Management** - Read device partition tables and perform individual operations on specific partitions: flashing, backup, or erasing.

**Mode Switching** - Quick buttons to enter Maskrom or Loader mode, and to reboot the device.

**Real-time Logging** - View command execution logs and flashing progress in real time.

**Multi-language Support** - Available in both Chinese and English.

**Theme Support** - Automatic system theme detection with manual switching between light and dark modes. Supports multiple styles: Fusion, Windows, macOS, and others.

---

## Requirements

- Python 3.8 or later
- PySide6 (Qt 6 for Python)
- `rkdeveloptool` (must be installed and added to PATH)

To verify `rkdeveloptool` is properly installed:
```bash
rkdeveloptool --version
```

For `rkdeveloptool` installation instructions, see the [Rockchip documentation](https://docs.radxa.com/en/zero/zero3/low-level-dev/rkdeveloptool).

---

## Installation

### From Source

```bash
git clone https://github.com/gahingwoo/RKDevelopTool-GUI
cd RKDevelopTool-GUI
pip install -r requirements.txt
python rkdevtoolgui.py
```

### Build Standalone Executable

```bash
python build_nuitka.py
./rkdevtoolgui
```

### Arch Linux

Available in AUR:
```bash
yay -S rkdeveloptool-gui
```

Or through a community repository:
```bash
sudo pacman -S rkdeveloptool-gui
```

For the packaging status across more distributions, please refer to [Repology](https://repology.org/project/rkdeveloptool-gui/versions)

Alternatively, you can install it via a [self-hosted package repository](https://github.com/taotieren/aur-repo)

---

## Usage

### Basic Workflow

1. Connect your Rockchip device via USB
2. The application will automatically detect the device and display its status
3. Select the operation you need: firmware flashing, backup, or partition management
4. Review the settings and confirm to proceed

### Firmware Flashing

1. Navigate to the "Firmware Download" tab
2. Click "Browse" and select your update.img file
3. Click "Start One-Click Burn" to begin
4. Wait for the process to complete (progress bar shows current status)

### Partition Management

1. Go to the "Partition Management" tab
2. Click "Read Partition Table" to retrieve partitions from the device
3. Select a partition and choose your operation: flash, backup, or erase
4. Confirm and wait for completion

### Theme and Style Selection

The status bar at the bottom provides quick access to:
- Style selector: Choose between Fusion, Windows, macOS, and other available styles
- Theme selector: Switch between Automatic, Dark, and Light themes
- Language selector: Choose between Chinese and English

---

## Important Notice

This software is a graphical wrapper around rkdeveloptool. Firmware flashing is inherently risky and may result in device bricking or data loss if not performed correctly.

Before using this tool:
- Ensure you have a backup of important data
- Verify that your device has sufficient battery
- Understand the implications of each operation
- Consult device-specific documentation if needed

The author is not responsible for any device damage, data loss, or other consequences resulting from the use of this software.

---

## Contributing

Contributions are welcome. Please feel free to submit issues or pull requests.

---

## License

See [LICENSE](LICENSE) file for details.

---

## Support

For issues, questions, or feature requests, please visit:
https://github.com/gahingwoo/RKDevelopTool-GUI/issues


