"""
UI Panel creation functions for RKDevelopTool GUI
Contains all UI panel and tab construction logic
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QLineEdit, QListWidget, QComboBox, QGroupBox, QCheckBox,
    QTableWidget, QSpinBox, QTextBrowser, QProgressBar, QHeaderView,
    QSizePolicy, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from utils import safe_slot
from widgets import AutoLoadCombo
import operations


def create_device_panel(gui):
    """Create device status panel"""
    group = QGroupBox()
    layout = QVBoxLayout()

    status_label = QLabel()
    status_label.setStyleSheet("QLabel { color: #aaaaaa; padding: 5px; }")

    chip_label = QLabel()
    chip_label.setStyleSheet("QLabel { color: #f0f0f0; font-weight: bold; padding: 5px; }")

    devices_label = QLabel()

    device_list = QListWidget()
    device_list.setMaximumHeight(80)

    layout.addWidget(status_label)
    layout.addWidget(chip_label)
    layout.addWidget(devices_label)
    layout.addWidget(device_list)

    group.setLayout(layout)

    widgets = {
        'status': status_label,
        'chip': chip_label,
        'label': devices_label,
        'list': device_list
    }

    return group, widgets


def create_mode_panel(gui):
    """Create mode control panel"""
    group = QGroupBox()
    layout = QVBoxLayout()

    maskrom_btn = QPushButton()
    maskrom_btn.setProperty("class", "warning")
    maskrom_btn.clicked.connect(safe_slot(lambda: operations.enter_maskrom_mode(gui)))

    loader_btn = QPushButton()
    loader_btn.setProperty("class", "primary")
    loader_btn.clicked.connect(safe_slot(lambda: operations.enter_loader_mode(gui)))

    reset_btn = QPushButton()
    reset_btn.clicked.connect(safe_slot(lambda: operations.reset_device(gui)))

    layout.addWidget(maskrom_btn)
    layout.addWidget(loader_btn)
    layout.addWidget(reset_btn)

    group.setLayout(layout)

    widgets = {
        'maskrom': maskrom_btn,
        'loader': loader_btn,
        'reset': reset_btn
    }

    return group, widgets


def create_quick_panel(gui):
    """Create quick actions panel"""
    group = QGroupBox()
    layout = QVBoxLayout()

    info_btn = QPushButton()
    info_btn.setProperty("class", "primary")
    info_btn.clicked.connect(safe_slot(lambda: operations.read_device_info(gui)))

    partitions_btn = QPushButton()
    partitions_btn.clicked.connect(safe_slot(lambda: operations.read_partition_table(gui)))

    backup_btn = QPushButton()
    backup_btn.setProperty("class", "success")
    backup_btn.clicked.connect(safe_slot(lambda: operations.backup_firmware(gui)))

    flash_id_btn = QPushButton()
    flash_id_btn.clicked.connect(safe_slot(lambda: read_flash_id(gui)))

    flash_info_btn = QPushButton()
    flash_info_btn.clicked.connect(safe_slot(lambda: read_flash_info(gui)))

    layout.addWidget(info_btn)
    layout.addWidget(partitions_btn)
    layout.addWidget(backup_btn)
    layout.addWidget(flash_id_btn)
    layout.addWidget(flash_info_btn)

    group.setLayout(layout)

    widgets = {
        'info': info_btn,
        'partitions': partitions_btn,
        'backup': backup_btn,
        'flash_id': flash_id_btn,
        'flash_info': flash_info_btn
    }

    return group, widgets


def create_download_tab(gui):
    """Create download tab"""
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # One-key burn group
    onekey_group = QGroupBox()
    onekey_layout = QGridLayout()

    firmware_label = QLabel()
    firmware_path = QLineEdit()
    firmware_browse = QPushButton()
    gui.register_browse(firmware_browse, firmware_path, "file_dialog_firmware")

    burn_btn = QPushButton()
    burn_btn.setProperty("class", "success")
    burn_btn.clicked.connect(safe_slot(lambda: operations.onekey_burn(gui)))

    onekey_layout.addWidget(firmware_label, 0, 0)
    onekey_layout.addWidget(firmware_path, 0, 1)
    onekey_layout.addWidget(firmware_browse, 0, 2)
    onekey_layout.addWidget(burn_btn, 1, 0, 1, 3)

    onekey_group.setLayout(onekey_layout)

    # Loader group
    loader_group = QGroupBox()
    loader_layout = QGridLayout()

    loader_label = QLabel()
    loader_path = QLineEdit()
    loader_browse = QPushButton()
    gui.register_browse(loader_browse, loader_path, "file_dialog_loader")

    auto_load = QCheckBox()
    load_btn = QPushButton()
    load_btn.setProperty("class", "primary")
    load_btn.clicked.connect(safe_slot(lambda: operations.load_loader(gui)))

    loader_layout.addWidget(loader_label, 0, 0)
    loader_layout.addWidget(loader_path, 0, 1)
    loader_layout.addWidget(loader_browse, 0, 2)
    loader_layout.addWidget(auto_load, 1, 0)
    loader_layout.addWidget(load_btn, 1, 2)

    loader_group.setLayout(loader_layout)

    # Image group
    image_group = QGroupBox()
    image_layout = QGridLayout()

    image_label = QLabel()
    image_path = QLineEdit()
    image_browse = QPushButton()
    gui.register_browse(image_browse, image_path, "file_dialog_image")

    address_label = QLabel()
    address_combo = AutoLoadCombo(gui, on_open=lambda: operations.read_partition_table(gui))
    address_combo.currentTextChanged.connect(safe_slot(lambda: on_address_changed(gui)))

    custom_address = QLineEdit()
    custom_address.setEnabled(False)

    burn_image_btn = QPushButton()
    burn_image_btn.setProperty("class", "success")
    burn_image_btn.clicked.connect(safe_slot(lambda: operations.burn_image(gui)))

    image_layout.addWidget(image_label, 0, 0)
    image_layout.addWidget(image_path, 0, 1)
    image_layout.addWidget(image_browse, 0, 2)
    image_layout.addWidget(address_label, 1, 0)
    image_layout.addWidget(address_combo, 1, 1)
    image_layout.addWidget(custom_address, 1, 2)
    image_layout.addWidget(burn_image_btn, 2, 0, 1, 3)

    image_group.setLayout(image_layout)

    # Storage controls
    storage_label = QLabel()
    storage_combo = QComboBox()
    storage_combo.addItem("EMMC", "1")
    storage_combo.addItem("SD", "2")
    storage_combo.addItem("SPINOR", "9")

    storage_btn = QPushButton()
    storage_btn.clicked.connect(safe_slot(lambda: change_storage(gui)))

    storage_layout = QHBoxLayout()
    storage_layout.addWidget(storage_label)
    storage_layout.addWidget(storage_combo)
    storage_layout.addWidget(storage_btn)

    # Flash operations
    erase_btn = QPushButton()
    erase_btn.setProperty("class", "danger")
    erase_btn.clicked.connect(safe_slot(lambda: erase_flash(gui)))

    test_btn = QPushButton()
    test_btn.clicked.connect(safe_slot(lambda: test_device(gui)))

    ops_layout = QHBoxLayout()
    ops_layout.addWidget(erase_btn)
    ops_layout.addWidget(test_btn)

    layout.addWidget(onekey_group)
    layout.addWidget(loader_group)
    layout.addWidget(image_group)
    layout.addLayout(storage_layout)
    layout.addLayout(ops_layout)

    widgets = {
        'onekey_group': onekey_group,
        'firmware_path': firmware_path,
        'firmware_browse': firmware_browse,
        'burn_btn': burn_btn,
        'loader_group': loader_group,
        'loader_path': loader_path,
        'loader_browse': loader_browse,
        'auto_load': auto_load,
        'load_btn': load_btn,
        'image_group': image_group,
        'image_path': image_path,
        'image_browse': image_browse,
        'address_combo': address_combo,
        'custom_address': custom_address,
        'burn_image_btn': burn_image_btn,
        'storage_label': storage_label,
        'storage_combo': storage_combo,
        'storage_btn': storage_btn,
        'erase_btn': erase_btn,
        'test_btn': test_btn,
        'firmware_label': firmware_label,
        'loader_label': loader_label,
        'image_label': image_label,
        'address_label': address_label
    }

    return widget, widgets


def create_partition_tab(gui):
    """Create partition management tab"""
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Partition list group
    list_group = QGroupBox()
    list_layout = QVBoxLayout()

    partition_table = QTableWidget()
    partition_table.setColumnCount(4)

    # Configure table
    header = partition_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    try:
        table_font = QApplication.font()
        table_font.setPointSize(max(table_font.pointSize(), 11))
        partition_table.setFont(table_font)
    except:
        pass

    partition_table.verticalHeader().setDefaultSectionSize(28)
    partition_table.setMinimumHeight(320)
    partition_table.setMinimumWidth(760)
    partition_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    refresh_btn = QPushButton()
    refresh_btn.clicked.connect(safe_slot(lambda: operations.read_partition_table(gui)))

    list_layout.addWidget(partition_table)
    list_layout.addWidget(refresh_btn)
    list_group.setLayout(list_layout)
    list_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # Partition operations group
    ops_group = QGroupBox()
    ops_layout = QGridLayout()

    select_label = QLabel()
    partition_combo = QComboBox()

    file_label = QLabel()
    file_path = QLineEdit()
    file_browse = QPushButton()
    gui.register_browse(file_browse, file_path, "file_dialog_image")

    burn_btn = QPushButton()
    burn_btn.setProperty("class", "success")
    burn_btn.clicked.connect(safe_slot(lambda: burn_partition(gui)))

    backup_btn = QPushButton()
    backup_btn.setProperty("class", "primary")
    backup_btn.clicked.connect(safe_slot(lambda: backup_partition(gui)))

    manual_enable = QCheckBox()
    manual_address = QLineEdit()
    manual_address.setPlaceholderText("0x2000")

    ops_layout.addWidget(select_label, 0, 0)
    ops_layout.addWidget(partition_combo, 0, 1)
    ops_layout.addWidget(file_label, 1, 0)
    ops_layout.addWidget(file_path, 1, 1)
    ops_layout.addWidget(file_browse, 1, 2)
    ops_layout.addWidget(burn_btn, 2, 0)
    ops_layout.addWidget(backup_btn, 2, 1)
    ops_layout.addWidget(manual_enable, 3, 0)
    ops_layout.addWidget(manual_address, 3, 1)

    ops_group.setLayout(ops_layout)
    ops_group.hide()  # Hide by default as operations are in table

    layout.addWidget(list_group, 1)

    widgets = {
        'list_group': list_group,
        'table': partition_table,
        'refresh_btn': refresh_btn,
        'ops_group': ops_group,
        'combo': partition_combo,
        'file_path': file_path,
        'file_browse': file_browse,
        'burn_btn': burn_btn,
        'backup_btn': backup_btn,
        'manual_enable': manual_enable,
        'manual_address': manual_address,
        'select_label': select_label,
        'file_label': file_label
    }

    return widget, widgets


def create_parameter_tab(gui):
    """Create parameter settings tab"""
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Burn parameters group
    burn_group = QGroupBox()
    burn_layout = QGridLayout()

    verify_check = QCheckBox()
    verify_check.setChecked(True)

    erase_check = QCheckBox()
    erase_check.setChecked(False)

    reset_check = QCheckBox()
    reset_check.setChecked(True)

    burn_layout.addWidget(verify_check, 0, 0)
    burn_layout.addWidget(erase_check, 0, 1)
    burn_layout.addWidget(reset_check, 1, 0)

    burn_group.setLayout(burn_layout)

    # Advanced parameters group
    advanced_group = QGroupBox()
    advanced_layout = QGridLayout()

    timeout_label = QLabel()
    timeout_spin = QSpinBox()
    timeout_spin.setRange(10, 300)
    timeout_spin.setValue(30)

    retry_label = QLabel()
    retry_spin = QSpinBox()
    retry_spin.setRange(0, 10)
    retry_spin.setValue(3)

    advanced_layout.addWidget(timeout_label, 0, 0)
    advanced_layout.addWidget(timeout_spin, 0, 1)
    advanced_layout.addWidget(retry_label, 1, 0)
    advanced_layout.addWidget(retry_spin, 1, 1)

    advanced_group.setLayout(advanced_layout)

    # Device info group
    info_group = QGroupBox()
    info_layout = QVBoxLayout()

    info_text = QTextBrowser()
    info_text.setMaximumHeight(150)

    info_btn = QPushButton()
    info_btn.clicked.connect(safe_slot(lambda: operations.read_capability(gui)))

    info_layout.addWidget(info_text)
    info_layout.addWidget(info_btn)

    info_group.setLayout(info_layout)

    layout.addWidget(burn_group)
    layout.addWidget(advanced_group)
    layout.addWidget(info_group)

    widgets = {
        'burn_group': burn_group,
        'verify': verify_check,
        'erase': erase_check,
        'reset': reset_check,
        'advanced_group': advanced_group,
        'timeout': timeout_spin,
        'retry': retry_spin,
        'info_group': info_group,
        'info_text': info_text,
        'info_btn': info_btn,
        'timeout_label': timeout_label,
        'retry_label': retry_label
    }

    return widget, widgets


def create_upgrade_tab(gui):
    """Create pack/unpack tab"""
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Pack group
    pack_group = QGroupBox()
    pack_layout = QGridLayout()

    pack_label = QLabel()
    pack_output = QLineEdit()
    pack_browse = QPushButton()
    gui.register_browse(pack_browse, pack_output, "file_dialog_all", save=True)

    pack_btn = QPushButton()
    pack_btn.clicked.connect(safe_slot(lambda: pack_bootloader(gui)))

    pack_layout.addWidget(pack_label, 0, 0)
    pack_layout.addWidget(pack_output, 0, 1)
    pack_layout.addWidget(pack_browse, 0, 2)
    pack_layout.addWidget(pack_btn, 0, 3)

    pack_group.setLayout(pack_layout)

    # Unpack group
    unpack_group = QGroupBox()
    unpack_layout = QGridLayout()

    unpack_label = QLabel()
    unpack_input = QLineEdit()
    unpack_browse = QPushButton()
    gui.register_browse(unpack_browse, unpack_input, "file_dialog_all")

    unpack_btn = QPushButton()
    unpack_btn.clicked.connect(safe_slot(lambda: unpack_bootloader(gui)))

    unpack_layout.addWidget(unpack_label, 0, 0)
    unpack_layout.addWidget(unpack_input, 0, 1)
    unpack_layout.addWidget(unpack_browse, 0, 2)
    unpack_layout.addWidget(unpack_btn, 0, 3)

    unpack_group.setLayout(unpack_layout)

    # Pack operations group
    ops_group = QGroupBox()
    ops_layout = QGridLayout()

    gpt_label = QLabel()
    gpt_path = QLineEdit()
    gpt_browse = QPushButton()
    gui.register_browse(gpt_browse, gpt_path, "file_dialog_all")
    gpt_btn = QPushButton()
    gpt_btn.clicked.connect(safe_slot(lambda: write_gpt(gui)))

    prm_label = QLabel()
    prm_text = QLineEdit()
    prm_btn = QPushButton()
    prm_btn.clicked.connect(safe_slot(lambda: write_parameter(gui)))

    tagspl_label = QLabel()
    tagspl_tag = QLineEdit()
    tagspl_path = QLineEdit()
    tagspl_browse = QPushButton()
    gui.register_browse(tagspl_browse, tagspl_path, "file_dialog_all")
    tagspl_btn = QPushButton()
    tagspl_btn.clicked.connect(safe_slot(lambda: tag_spl(gui)))

    ops_layout.addWidget(gpt_label, 0, 0)
    ops_layout.addWidget(gpt_path, 0, 1)
    ops_layout.addWidget(gpt_browse, 0, 2)
    ops_layout.addWidget(gpt_btn, 0, 3)

    ops_layout.addWidget(prm_label, 1, 0)
    ops_layout.addWidget(prm_text, 1, 1)
    ops_layout.addWidget(prm_btn, 1, 2)

    ops_layout.addWidget(tagspl_label, 2, 0)
    ops_layout.addWidget(tagspl_tag, 2, 1)
    ops_layout.addWidget(tagspl_path, 2, 2)
    ops_layout.addWidget(tagspl_browse, 2, 3)
    ops_layout.addWidget(tagspl_btn, 2, 4)

    ops_group.setLayout(ops_layout)

    layout.addWidget(pack_group)
    layout.addWidget(unpack_group)
    layout.addWidget(ops_group)

    widgets = {
        'pack_group': pack_group,
        'pack_output': pack_output,
        'pack_browse': pack_browse,
        'pack_btn': pack_btn,
        'unpack_group': unpack_group,
        'unpack_input': unpack_input,
        'unpack_browse': unpack_browse,
        'unpack_btn': unpack_btn,
        'ops_group': ops_group,
        'gpt_path': gpt_path,
        'gpt_browse': gpt_browse,
        'gpt_btn': gpt_btn,
        'prm_text': prm_text,
        'prm_btn': prm_btn,
        'tagspl_tag': tagspl_tag,
        'tagspl_path': tagspl_path,
        'tagspl_browse': tagspl_browse,
        'tagspl_btn': tagspl_btn,
        'pack_label': pack_label,
        'unpack_label': unpack_label,
        'gpt_label': gpt_label,
        'prm_label': prm_label,
        'tagspl_label': tagspl_label
    }

    return widget, widgets


def create_advanced_tab(gui):
    """Create advanced tools tab"""
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Flash operations group (empty for now, operations moved to download tab)
    flash_group = QGroupBox()
    flash_layout = QGridLayout()
    flash_group.setLayout(flash_layout)

    # Read/Write operations group
    rw_group = QGroupBox()
    rw_layout = QGridLayout()

    read_address_label = QLabel()
    read_address = QLineEdit()

    read_length_label = QLabel()
    read_length = QLineEdit()

    read_save_label = QLabel()
    read_save = QLineEdit()
    read_browse = QPushButton()
    gui.register_browse(read_browse, read_save, save=True)

    read_btn = QPushButton()
    read_btn.setProperty("class", "primary")
    read_btn.clicked.connect(safe_slot(lambda: read_flash(gui)))

    rw_layout.addWidget(read_address_label, 0, 0)
    rw_layout.addWidget(read_address, 0, 1)
    rw_layout.addWidget(read_length_label, 0, 2)
    rw_layout.addWidget(read_length, 0, 3)
    rw_layout.addWidget(read_save_label, 1, 0)
    rw_layout.addWidget(read_save, 1, 1, 1, 2)
    rw_layout.addWidget(read_browse, 1, 3)
    rw_layout.addWidget(read_btn, 2, 0, 1, 4)

    rw_group.setLayout(rw_layout)

    # Verification group
    verify_group = QGroupBox()
    verify_layout = QGridLayout()

    verify_file_label = QLabel()
    verify_file = QLineEdit()
    verify_browse = QPushButton()
    gui.register_browse(verify_browse, verify_file, "file_dialog_all")

    verify_address_label = QLabel()
    verify_address = QLineEdit()

    verify_sector_label = QLabel()
    sector_combo = QComboBox()
    sector_combo.addItem("512 B", "512")
    sector_combo.addItem("4096 B", "4096")
    sector_combo.addItem("Custom", "custom")

    sector_custom = QLineEdit()
    sector_custom.setEnabled(False)
    sector_combo.currentIndexChanged.connect(safe_slot(lambda: on_verify_sector_changed(gui)))

    verify_btn = QPushButton()
    verify_btn.setProperty("class", "success")
    verify_btn.clicked.connect(safe_slot(lambda: verify_flash(gui)))

    md5_btn = QPushButton()
    md5_btn.clicked.connect(safe_slot(lambda: calculate_md5(gui)))

    verify_layout.addWidget(verify_file_label, 0, 0)
    verify_layout.addWidget(verify_file, 0, 1)
    verify_layout.addWidget(verify_browse, 0, 2)
    verify_layout.addWidget(verify_address_label, 1, 0)
    verify_layout.addWidget(verify_address, 1, 1)
    verify_layout.addWidget(verify_sector_label, 1, 2)
    verify_layout.addWidget(sector_combo, 1, 3)
    verify_layout.addWidget(sector_custom, 1, 4)
    verify_layout.addWidget(verify_btn, 2, 0)
    verify_layout.addWidget(md5_btn, 2, 1)

    verify_group.setLayout(verify_layout)

    # Debug group
    debug_group = QGroupBox()
    debug_layout = QGridLayout()

    debug_log = QCheckBox()
    debug_log.stateChanged.connect(safe_slot(lambda: toggle_debug_log(gui)))

    export_log = QPushButton()
    export_log.clicked.connect(safe_slot(lambda: export_system_log(gui)))

    usb_info = QPushButton()
    usb_info.clicked.connect(safe_slot(lambda: show_usb_info(gui)))

    debug_layout.addWidget(debug_log, 0, 0, 1, 2)
    debug_layout.addWidget(export_log, 1, 0)
    debug_layout.addWidget(usb_info, 1, 1)

    debug_group.setLayout(debug_layout)

    # Mass production group
    mass_group = QGroupBox()
    mass_layout = QGridLayout()

    mass_list = QListWidget()
    mass_list.setMaximumHeight(100)
    mass_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)

    mass_scan = QPushButton()
    mass_scan.clicked.connect(safe_slot(lambda: scan_mass_devices(gui)))

    mass_firmware_label = QLabel()
    mass_firmware = QLineEdit()
    mass_browse = QPushButton()
    gui.register_browse(mass_browse, mass_firmware, "file_dialog_firmware")

    mass_start = QPushButton()
    mass_start.setProperty("class", "success")
    mass_start.clicked.connect(safe_slot(lambda: start_mass_production(gui)))

    mass_stop = QPushButton()
    mass_stop.setProperty("class", "danger")
    mass_stop.clicked.connect(safe_slot(lambda: stop_mass_production(gui)))
    mass_stop.setEnabled(False)

    mass_progress = QLabel()

    mass_layout.addWidget(QLabel(), 0, 0, 1, 3)  # Will be updated with text
    mass_layout.addWidget(mass_list, 1, 0, 1, 3)
    mass_layout.addWidget(mass_scan, 2, 0, 1, 3)
    mass_layout.addWidget(mass_firmware_label, 3, 0)
    mass_layout.addWidget(mass_firmware, 3, 1)
    mass_layout.addWidget(mass_browse, 3, 2)
    mass_layout.addWidget(mass_start, 4, 0)
    mass_layout.addWidget(mass_stop, 4, 1)
    mass_layout.addWidget(mass_progress, 5, 0, 1, 3)

    mass_group.setLayout(mass_layout)

    # Add to main layout (skip flash_group if empty)
    layout.addWidget(rw_group)
    layout.addWidget(verify_group)
    layout.addWidget(debug_group)
    layout.addWidget(mass_group)

    widgets = {
        'flash_group': flash_group,
        'rw_group': rw_group,
        'read_address': read_address,
        'read_length': read_length,
        'read_save': read_save,
        'read_browse': read_browse,
        'read_btn': read_btn,
        'verify_group': verify_group,
        'verify_file': verify_file,
        'verify_browse': verify_browse,
        'verify_address': verify_address,
        'verify_btn': verify_btn,
        'md5_btn': md5_btn,
        'sector_combo': sector_combo,
        'sector_custom': sector_custom,
        'debug_group': debug_group,
        'debug_log': debug_log,
        'export_log': export_log,
        'usb_info': usb_info,
        'mass_group': mass_group,
        'mass_list': mass_list,
        'mass_scan': mass_scan,
        'mass_firmware': mass_firmware,
        'mass_browse': mass_browse,
        'mass_start': mass_start,
        'mass_stop': mass_stop,
        'mass_progress': mass_progress,
        'read_address_label': read_address_label,
        'read_length_label': read_length_label,
        'read_save_label': read_save_label,
        'verify_file_label': verify_file_label,
        'verify_address_label': verify_address_label,
        'verify_sector_label': verify_sector_label,
        'mass_firmware_label': mass_firmware_label
    }

    return widget, widgets


def create_log_panel(gui):
    """Create log and progress panel"""
    group = QGroupBox()
    layout = QVBoxLayout()

    # Log controls
    controls = QHBoxLayout()

    clear_btn = QPushButton()
    clear_btn.clicked.connect(safe_slot(lambda: gui.log_output.clear()))

    save_btn = QPushButton()
    save_btn.clicked.connect(safe_slot(lambda: save_log(gui)))

    controls.addWidget(clear_btn)
    controls.addWidget(save_btn)
    controls.addStretch()

    # Log output
    log_output = QTextBrowser()
    log_output.setMaximumHeight(200)

    # Progress
    progress_bar = QProgressBar()
    progress_label = QLabel()

    layout.addLayout(controls)
    layout.addWidget(log_output)
    layout.addWidget(progress_label)
    layout.addWidget(progress_bar)

    group.setLayout(layout)

    widgets = {
        'clear': clear_btn,
        'save': save_btn,
        'output': log_output,
        'progress': progress_bar,
        'label': progress_label
    }

    return group, widgets


# ==================== Helper Functions ====================

def on_address_changed(gui):
    """Handle address combo change"""
    text = gui.address_combo.currentText()
    if gui.tr("custom_address") in text:
        gui.custom_address.setEnabled(True)
    else:
        gui.custom_address.setEnabled(False)


def change_storage(gui):
    """Change storage medium and auto-refresh partition table"""
    from utils import RKTOOL
    storage = gui.change_storage_combo.currentData()
    if not storage:
        gui.show_message("Warning", "select_storage", "Warning")
        return
    
    storage_name = gui.change_storage_combo.currentText()
    gui.log_message(f"🔄 Switching storage to {storage_name}...")
    
    # Store the storage name for use in callback
    gui._storage_switch_target = storage_name
    
    # Disconnect previous finished signal if any
    if gui.command_worker and gui.command_worker.isRunning():
        try:
            gui.command_worker.finished_signal.disconnect()
        except:
            pass
    
    # Run the storage change command using standard run_command
    gui.run_command([RKTOOL, "cs", storage], "changing_storage")
    
    # Connect to the finished signal to auto-refresh partitions
    if gui.command_worker:
        def on_storage_finished(success, error_msg):
            """Handle storage change completion and auto-refresh partition table"""
            target_name = getattr(gui, '_storage_switch_target', 'Storage')
            if success:
                gui.log_message(f"✅ Storage switched to {target_name}")
                gui.log_message(f"📦 Auto-refreshing partition table...")
                # Auto-refresh partition table after successful storage switch
                operations.read_partition_table(gui)
            else:
                gui.log_message(f"❌ Failed to switch storage: {error_msg if error_msg else 'Unknown error'}")
            # Call the original on_command_finished
            gui.on_command_finished(success, error_msg)
        
        try:
            gui.command_worker.finished_signal.disconnect()
        except:
            pass
        gui.command_worker.finished_signal.connect(safe_slot(on_storage_finished))


def erase_flash(gui):
    """Erase entire flash"""
    from PySide6.QtWidgets import QMessageBox
    from operations import style_messagebox
    from utils import RKTOOL

    msg = QMessageBox()
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr("erase_flash_warning_title"))
    msg.setText(gui.tr("erase_flash_warning_message"))
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setMinimumWidth(500)
    
    if msg.exec() == QMessageBox.StandardButton.Yes:
        gui.run_command([RKTOOL, "ef"], "erase_flash")


def test_device(gui):
    """Test device connection"""
    from utils import RKTOOL
    gui.run_command([RKTOOL, "td"], "test_connection")


def read_flash_id(gui):
    """Read Flash ID using enhanced operations function"""
    from operations import read_flash_id as read_flash_id_op
    read_flash_id_op(gui)


def on_flash_id_read(gui, success):
    """Handle flash ID read completion (legacy support)"""
    if not success:
        return

    from utils import parse_flash_info
    log_text = gui.log_output.toPlainText()
    flash_info = parse_flash_info(log_text)

    if flash_info:
        info_text = "🔍 Flash Information:\n"
        if 'manufacturer' in flash_info:
            info_text += f"  Manufacturer: {flash_info['manufacturer']}\n"
        if 'id' in flash_info:
            info_text += f"  Flash ID: {flash_info['id']}\n"
        if 'capacity' in flash_info:
            info_text += f"  Capacity: {flash_info['capacity']}\n"
        gui.log_message(info_text)


def read_flash_info(gui):
    """Read detailed flash info using enhanced operations function"""
    from operations import show_flash_info_detailed
    show_flash_info_detailed(gui)


def on_flash_info_read(gui, success):
    """Handle flash info read completion"""
    if not success:
        return

    from utils import parse_flash_info
    log_text = gui.log_output.toPlainText()
    flash_info = parse_flash_info(log_text)

    if flash_info:
        info_text = "📊 Detailed Flash Info:\n"
        if 'manufacturer' in flash_info:
            info_text += f"  Manufacturer: {flash_info['manufacturer']}\n"
        if 'id' in flash_info:
            info_text += f"  Flash ID: {flash_info['id']}\n"
        if 'capacity' in flash_info:
            info_text += f"  Total Capacity: {flash_info['capacity']}\n"
        gui.log_message(info_text)


def burn_partition(gui):
    """Burn partition"""
    import re
    import os
    from utils import RKTOOL

    selected_partition_key = gui.partition_combo.currentData()
    selected_partition = gui.partition_combo.currentText()
    partition_path = gui.partition_file_path.text()

    if not selected_partition:
        gui.show_message("Warning", "select_partition", "Warning")
        return
    if not partition_path or not os.path.exists(partition_path):
        gui.show_message("Warning", "select_file_for_partition", "Warning")
        return

    # Manual override
    try:
        if gui.manual_address_enable.isChecked():
            addr = gui.manual_address.text().strip()
            if not addr:
                gui.show_message("Warning", "enter_manual_address", "Warning")
                return
            gui.run_command([RKTOOL, "wl", addr, partition_path], "burning")
            return
    except:
        pass

    # Use partition name key
    if selected_partition_key:
        gui.run_command([RKTOOL, "wlx", selected_partition_key, partition_path], "burning")
        return

    # Fallback: parse address
    match = re.search(r'\((\S+)\)', selected_partition)
    if not match:
        gui.show_message("Warning", "select_partition", "Warning")
        return
    part_arg = match.group(1)
    gui.run_command([RKTOOL, "wl", part_arg, partition_path], "burning")


def backup_partition(gui):
    """Backup partition"""
    import re
    import os
    from PySide6.QtWidgets import QFileDialog
    from utils import RKTOOL

    selected_partition_key = gui.partition_combo.currentData()
    selected_partition = gui.partition_combo.currentText()
    save_path = gui.partition_file_path.text()

    if not selected_partition:
        gui.show_message("Warning", "select_partition", "Warning")
        return
    if not save_path:
        save_path, _ = QFileDialog.getSaveFileName(gui, gui.tr("save_file_dialog"))
        if not save_path:
            return

    # Manual override
    try:
        if gui.manual_address_enable.isChecked():
            addr = gui.manual_address.text().strip()
            if not addr:
                gui.show_message("Warning", "enter_manual_address", "Warning")
                return
            gui.run_command([RKTOOL, "rl", addr, "0x1000", save_path], "backing_up")
            return
    except:
        pass

    # Use parsed partitions
    if selected_partition_key and selected_partition_key in gui.partitions:
        address = gui.partitions[selected_partition_key].get('address')
        if address:
            gui.run_command([RKTOOL, "rl", address, "0x1000", save_path], "backing_up")
            return

    # Fallback
    match = re.search(r'\((\S+)\)', selected_partition)
    if not match:
        gui.show_message("Warning", "select_partition", "Warning")
        return
    address = match.group(1)
    gui.run_command([RKTOOL, "rl", address, "0x1000", save_path], "backing_up")


def pack_bootloader(gui):
    """Pack bootloader"""
    import os
    from utils import RKTOOL

    outpath = gui.pack_output_path.text()
    if not outpath:
        gui.show_message("Warning", "select_pack_output", "Warning")
        return
    gui.run_command([RKTOOL, "pack", outpath], "packing_bootloader")


def unpack_bootloader(gui):
    """Unpack bootloader"""
    import os
    from utils import RKTOOL

    inpath = gui.unpack_input_path.text()
    if not inpath or not os.path.exists(inpath):
        gui.show_message("Warning", "select_unpack_input", "Warning")
        return
    gui.run_command([RKTOOL, "unpack", inpath], "unpacking_bootloader")


def write_gpt(gui):
    """Write GPT"""
    import os
    from utils import RKTOOL

    gptfile = gui.gpt_path.text()
    if not gptfile or not os.path.exists(gptfile):
        gui.show_message("Warning", "select_gpt_file", "Warning")
        return
    gui.run_command([RKTOOL, "gpt", gptfile], "writing_gpt")


def write_parameter(gui):
    """Write parameter"""
    from utils import RKTOOL

    prm = gui.prm_text.text()
    if not prm:
        gui.show_message("Warning", "select_parameter", "Warning")
        return
    gui.run_command([RKTOOL, "prm", prm], "writing_parameter")


def tag_spl(gui):
    """Tag SPL"""
    import os
    from utils import RKTOOL

    tag = gui.tagspl_tag.text()
    spl = gui.tagspl_spl_path.text()
    if not tag or not spl or not os.path.exists(spl):
        gui.show_message("Warning", "select_tagspl_input", "Warning")
        return
    gui.run_command([RKTOOL, "tagspl", tag, spl], "tagging_spl")


def read_flash(gui):
    """Read flash"""
    from utils import RKTOOL

    address = gui.read_address.text()
    length = gui.read_length.text()
    save_path = gui.read_save_path.text()

    if not address or not length or not save_path:
        gui.show_message("Warning", "enter_address_length", "Warning")
        return
    gui.run_command([RKTOOL, "rl", address, length, save_path], "reading_flash")


def verify_flash(gui):
    """Verify flash"""
    import os
    import math
    import tempfile
    import hashlib
    from utils import RKTOOL

    file_path = gui.verify_file_path.text()
    address = gui.verify_address.text()

    if not file_path or not os.path.exists(file_path):
        gui.show_message("Warning", "select_file_to_verify", "Warning")
        return
    if not address:
        gui.show_message("Warning", "select_address_for_verify", "Warning")
        return

    # Determine sector size
    sector_size = 512
    try:
        sel = gui.verify_sector_combo.currentData()
        if sel == 'custom':
            custom = gui.verify_sector_custom.text().strip()
            if custom:
                sector_size = int(custom)
        else:
            sector_size = int(sel)
    except:
        sector_size = 512

    # Calculate sectors
    sector_len_arg = None
    try:
        user_len = gui.read_length.text().strip()
        if user_len:
            sector_len_arg = user_len
    except:
        pass

    if not sector_len_arg:
        try:
            fsize = os.path.getsize(file_path)
            sectors = math.ceil(fsize / sector_size)
            sector_len_arg = hex(sectors)
        except:
            sector_len_arg = "0x1000"

    # Create temp file
    try:
        tf = tempfile.NamedTemporaryFile(delete=False)
        tmpfile = tf.name
        tf.close()
    except:
        tmpdir = tempfile.gettempdir()
        tmpfile = os.path.join(tmpdir, f"rkverify_{os.getpid()}_{int(hashlib.md5(file_path.encode()).hexdigest(),16) % 100000}.bin")

    # Save for verification
    gui._verify_tmpfile = tmpfile
    gui._verify_expected_file = file_path

    gui.run_command([RKTOOL, "rl", address, sector_len_arg, tmpfile], "verifying")


def calculate_md5(gui):
    """Calculate MD5 of file"""
    import os
    from PySide6.QtWidgets import QFileDialog
    from utils import calculate_file_md5

    file_path = gui.verify_file_path.text()
    if not file_path or not os.path.exists(file_path):
        file_path, _ = QFileDialog.getOpenFileName(gui, gui.tr("select_file_dialog"), "", gui.tr("file_dialog_all"))
        if not file_path:
            return

    try:
        md5sum = calculate_file_md5(file_path)
        gui.show_message("Information", f"MD5: {md5sum}")
        gui.log_message(f"MD5({file_path}) = {md5sum}")
    except Exception as e:
        gui.show_message("Warning", "md5_failed")
        gui.log_message(f"MD5 calculation failed: {e}")


def on_verify_sector_changed(gui):
    """Handle sector size combo change"""
    try:
        sel = gui.verify_sector_combo.currentData()
        if sel == 'custom':
            gui.verify_sector_custom.setEnabled(True)
        else:
            gui.verify_sector_custom.setEnabled(False)
    except:
        pass


def toggle_debug_log(gui):
    """Toggle debug logging"""
    pass  # Placeholder for debug log functionality


def export_system_log(gui):
    """Export system log"""
    from PySide6.QtWidgets import QFileDialog

    file_path, _ = QFileDialog.getSaveFileName(
        gui, gui.tr("save_log_dialog"), "rkdevtool.log", "Log Files (*.log);;All Files (*)"
    )
    if file_path:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(gui.log_output.toPlainText())
        gui.show_message("Information", "log_saved")


def show_usb_info(gui):
    """Show USB info"""
    gui.show_message("Information", "usb_info_not_implemented")


def save_log(gui):
    """Save log to file"""
    from PySide6.QtWidgets import QFileDialog

    file_path, _ = QFileDialog.getSaveFileName(
        gui, gui.tr("save_log_dialog"), "rkdevtool.log", "Log Files (*.log);;All Files (*)"
    )
    if file_path:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(gui.log_output.toPlainText())


def scan_mass_devices(gui):
    """Scan for mass production devices"""
    import subprocess
    from utils import RKTOOL

    try:
        result = subprocess.run([RKTOOL, "ld"], capture_output=True, text=True, timeout=3)
        lines = result.stdout.strip().splitlines()
        devices = [l.strip() for l in lines if l.strip() and
                  "Did not find" not in l and "not found" not in l]

        gui.mass_device_list.clear()
        for device in devices:
            gui.mass_device_list.addItem(device)

        gui.log_message(f"🔍 {gui.tr('found_devices')}: {len(devices)}")
    except Exception as e:
        gui.log_message(f"⚠️ {gui.tr('scan_failed')}: {e}")


def start_mass_production(gui):
    """Start mass production"""
    import os
    from PySide6.QtWidgets import QMessageBox
    from utils import RKTOOL
    from workers import CommandWorker

    firmware = gui.mass_firmware_path.text()
    if not firmware or not os.path.exists(firmware):
        gui.show_message("Warning", "select_firmware_file", "Warning")
        return

    selected_items = gui.mass_device_list.selectedItems()
    if not selected_items:
        gui.show_message("Warning", "select_devices_for_mass", "Warning")
        return

    # Confirm
    msg = QMessageBox()
    from operations import style_messagebox
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr("confirm_mass_production"))
    msg.setText(gui.tr("mass_production_warning").format(len(selected_items)))
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setMinimumWidth(500)
    
    if msg.exec() != QMessageBox.StandardButton.Yes:
        return

    gui.mass_production_active = True
    gui.mass_start_btn.setEnabled(False)
    gui.mass_stop_btn.setEnabled(True)

    # Create workers
    for item in selected_items:
        device = item.text()
        worker = CommandWorker([RKTOOL, "wl", "0x0", firmware], "burning", gui.manager)
        worker.log.connect(safe_slot(lambda msg, d=device: gui.log_message(f"[{d}] {msg}")))
        worker.finished_signal.connect(safe_slot(lambda s, e, d=device: on_mass_device_finished(gui, d, s, e)))
        gui.mass_workers.append(worker)
        worker.start()

    gui.mass_progress_label.setText(gui.tr("mass_production_running").format(len(selected_items)))


def stop_mass_production(gui):
    """Stop mass production"""
    gui.mass_production_active = False

    for worker in gui.mass_workers:
        try:
            if hasattr(worker, 'terminate_process'):
                worker.terminate_process()
            worker.wait(1000)
        except:
            pass

    gui.mass_workers.clear()
    gui.mass_start_btn.setEnabled(True)
    gui.mass_stop_btn.setEnabled(False)
    gui.mass_progress_label.setText(gui.tr("mass_production_stopped"))
    gui.log_message("⏹️ " + gui.tr("mass_production_stopped"))


def on_mass_device_finished(gui, device, success, error):
    """Handle mass device completion"""
    if success:
        gui.log_message(f"✅ [{device}] {gui.tr('success')}")
    else:
        gui.log_message(f"❌ [{device}] {gui.tr('failure')}: {error}")

    # Check if all done
    all_done = all(not w.isRunning() for w in gui.mass_workers)
    if all_done and gui.mass_production_active:
        gui.mass_start_btn.setEnabled(True)
        gui.mass_stop_btn.setEnabled(False)
        gui.mass_production_active = False

        success_count = sum(1 for w in gui.mass_workers if hasattr(w, '_success') and w._success)
        total = len(gui.mass_workers)

        gui.mass_progress_label.setText(
            gui.tr("mass_production_complete").format(success_count, total)
        )
        gui.show_message("Information", f"mass_production_result:{success_count}/{total}")

        gui.mass_workers.clear()