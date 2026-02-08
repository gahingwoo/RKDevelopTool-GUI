# RKDevelopTool GUI

English | [中文](readme.md)

RKDevelopTool GUI 是 Rockchip 官方 rkdeveloptool 的图形化前端，旨在为用户提供一个直观易用的界面，简化固件烧录、分区管理和设备调试的操作流程。

**GitHub:** https://github.com/gahingwoo/RKDevelopTool-GUI

![项目界面截图](images/home_zh.png)  
*RKDevelopTool GUI 主界面*

## 功能特性

**设备监控** - 自动检测已连接的 Rockchip 设备，并显示当前工作模式（Maskrom 或 Loader）。

**一键烧录** - 简化了固件烧录流程。只需选择 update.img 文件，点击开始即可。

**分区管理** - 读取设备分区表，对特定分区进行单独操作：烧录、备份或擦除。

**模式切换** - 快速进入 Maskrom 或 Loader 模式，以及设备重启。

**实时日志** - 查看命令执行日志和烧录进度。

**多语言支持** - 同时支持中文和英文界面。

**主题支持** - 支持自动检测或手动切换深色和浅色模式。提供 Fusion、Windows、macOS 等多种样式。

---

## 系统要求

- Python 3.8 或更高版本
- PySide6 (Qt 6 Python 绑定)
- `rkdeveloptool`（必须安装并配置到 PATH）

验证 `rkdeveloptool` 是否正确安装：
```bash
rkdeveloptool --version
```

安装`rkdeveloptool`说明请参考 [Rockchip 官方文档](https://docs.radxa.com/zero/zero3/low-level-dev/rkdeveloptool)。

---

## 安装

### 从源码运行

```bash
git clone https://github.com/gahingwoo/RKDevelopTool-GUI
cd RKDevelopTool-GUI
pip install -r requirements.txt
python rkdevtoolgui.py
```

### 构建独立可执行文件

```bash
python build_nuitka.py
./rkdevtoolgui
```

### Arch Linux

在 AUR 中可用：
```bash
yay -S rkdeveloptool-gui
```

或通过社区仓库：
```bash
sudo pacman -S rkdeveloptool-gui
```

更多发行版的打包状态请查看 [Repology](https://repology.org/project/rkdeveloptool-gui/versions)。

另外也可通过 [自建源仓库](https://github.com/taotieren/aur-repo) 安装。

---

## 使用方法

### 基本工作流程

1. 用 USB 线连接 Rockchip 设备
2. 应用会自动检测设备并显示其状态
3. 选择你需要的操作：固件烧录、备份或分区管理
4. 检查设置并确认执行

### 固件烧录

1. 进入"Firmware Download"标签页
2. 点击"Browse"选择你的 update.img 文件
3. 点击"Start One-Click Burn"开始烧录
4. 等待完成（进度条显示当前进度）

### 分区管理

1. 进入"Partition Management"标签页
2. 点击"Read Partition Table"从设备读取分区
3. 选择分区并选择操作：烧录、备份或擦除
4. 确认并等待完成

### 主题和样式选择

状态栏底部提供快速访问：
- 样式选择器：在 Fusion、Windows、macOS 等可用样式之间切换
- 主题选择器：在自动、深色和浅色主题之间切换
- 语言选择器：在中文和英文之间选择

---

## 重要提示

本软件是 rkdeveloptool 的图形化界面封装。固件烧录是一项风险操作，如果操作不当可能导致设备损坏或数据丢失。

使用本工具前，请：
- 确保已备份重要数据
- 验证设备电量充足
- 了解每项操作的含义
- 必要时查阅设备相关文档

作者不对因使用本软件而导致的设备损坏、数据丢失或其他后果承担责任。

---

## 贡献

欢迎贡献代码。请提交 issue 或 pull request。

---

## 许可证

详见 [LICENSE](LICENSE) 文件。

---

## 技术支持

如有问题、疑问或功能建议，请访问：
https://github.com/gahingwoo/RKDevelopTool-GUI/issues


