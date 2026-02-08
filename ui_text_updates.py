"""
UI Text update functions for RKDevelopTool GUI
Updates all UI text when language is changed
"""


def update_all_ui_text(gui):
    """Update all UI text based on current language"""
    update_window_and_device_texts(gui)
    update_download_tab_texts(gui)
    update_partition_tab_texts(gui)
    update_parameter_tab_texts(gui)
    update_upgrade_tab_texts(gui)
    update_advanced_tab_texts(gui)
    update_misc_texts(gui)
    update_statusbar_texts(gui)


def update_window_and_device_texts(gui):
    """Update window title and device panel texts"""
    gui.setWindowTitle(gui.tr("app_title"))
    gui.device_group.setTitle(gui.tr("device_status_group"))
    gui.device_status_label.setText(gui.tr("detecting_device"))
    gui.chip_info_label.setText(f"{gui.tr('chip')}: {gui.tr(gui.chip_info)}")
    gui.connected_devices_label.setText(gui.tr("connected_devices"))

    gui.mode_group.setTitle(gui.tr("mode_control_group"))
    gui.enter_maskrom_btn.setText(gui.tr("enter_maskrom_btn"))
    gui.enter_loader_btn.setText(gui.tr("enter_loader_btn"))
    gui.reset_device_btn.setText(gui.tr("reset_device_btn"))

    gui.quick_group.setTitle(gui.tr("quick_actions_group"))
    gui.read_info_btn.setText(gui.tr("read_info_btn"))
    gui.read_partitions_btn.setText(gui.tr("read_partitions_btn"))
    gui.backup_firmware_btn.setText(gui.tr("backup_firmware_btn"))
    gui.read_flash_id_btn.setText(gui.tr("read_flash_id_btn"))
    gui.read_flash_info_btn.setText(gui.tr("read_flash_info_btn"))


def update_download_tab_texts(gui):
    """Update download tab texts"""
    gui.tab_widget.setTabText(0, gui.tr("download_tab"))

    gui.log_group.setTitle(gui.tr("log_progress_group"))
    gui.clear_log_btn.setText(gui.tr("clear_log_btn"))
    gui.save_log_btn.setText(gui.tr("save_log_btn"))
    gui.progress_label.setText(gui.tr("ready"))

    gui.onekey_group.setTitle(gui.tr("onekey_burn_group"))
    gui.firmware_label.setText(gui.tr("firmware_file_placeholder"))
    gui.firmware_path.setPlaceholderText(gui.tr("firmware_file_placeholder"))
    gui.firmware_browse_btn.setText(gui.tr("browse_btn"))
    gui.onekey_burn_btn.setText(gui.tr("start_burn_btn"))

    gui.loader_group.setTitle(gui.tr("loader_config_group"))
    gui.loader_label.setText(gui.tr("loader_file_placeholder"))
    gui.loader_path.setPlaceholderText(gui.tr("loader_file_placeholder"))
    gui.loader_browse_btn.setText(gui.tr("browse_btn"))
    gui.auto_load_loader.setText(gui.tr("auto_load_loader"))
    gui.load_loader_btn.setText(gui.tr("load_loader_btn"))

    gui.image_group.setTitle(gui.tr("custom_image_group"))
    gui.image_label.setText(gui.tr("image_file_placeholder"))
    gui.image_path.setPlaceholderText(gui.tr("image_file_placeholder"))
    gui.image_browse_btn.setText(gui.tr("browse_btn"))
    gui.address_label.setText(gui.tr("target_address"))
    gui.custom_address.setPlaceholderText(gui.tr("custom_address_placeholder"))
    gui.burn_image_btn.setText(gui.tr("burn_image_btn"))

    # Populate address combo
    populate_address_combo(gui)

    # Storage and flash operations
    gui.change_storage_label.setText(gui.tr("change_storage_label"))
    gui.change_storage_btn.setText(gui.tr("change_storage_btn"))
    gui.erase_flash_btn.setText(gui.tr("erase_flash_btn"))
    gui.test_device_btn.setText(gui.tr("test_device_btn"))


def update_partition_tab_texts(gui):
    """Update partition tab texts"""
    gui.tab_widget.setTabText(1, gui.tr("partition_tab"))

    gui.partition_list_group.setTitle(gui.tr("partition_info_group"))
    gui.partition_table.setHorizontalHeaderLabels([
        gui.tr("partition_name"),
        gui.tr("start_address"),
        gui.tr("size"),
        gui.tr("action")
    ])
    gui.refresh_partitions_btn.setText(gui.tr("refresh_partitions_btn"))

    gui.partition_ops_group.setTitle(gui.tr("partition_ops_group"))
    gui.select_partition_label.setText(gui.tr("select_partition"))
    gui.partition_file_label.setText(gui.tr("file_path"))
    gui.partition_file_path.setPlaceholderText(gui.tr("file_path"))
    gui.partition_file_browse_btn.setText(gui.tr("browse_btn"))
    gui.burn_partition_btn.setText(gui.tr("burn_partition_btn"))
    gui.backup_partition_btn.setText(gui.tr("backup_partition_btn"))
    gui.erase_partition_btn.setText(gui.tr("erase_partition_btn"))
    gui.erase_all_btn.setText(gui.tr("erase_all_btn"))
    gui.manual_address_enable.setText(gui.tr("manual_address_override"))
    
    # Update danger zone label
    if hasattr(gui, 'danger_label') and gui.danger_label:
        gui.danger_label.setText(gui.tr("danger_zone_label"))

    # Populate partition combo
    populate_partition_combo(gui)


def update_parameter_tab_texts(gui):
    """Update parameter tab texts"""
    gui.tab_widget.setTabText(2, gui.tr("parameter_tab"))

    gui.burn_params_group.setTitle(gui.tr("burn_params_group"))
    gui.verify_after_burn.setText(gui.tr("verify_after_burn"))
    gui.erase_before_burn.setText(gui.tr("erase_before_burn"))
    gui.reset_after_burn.setText(gui.tr("reset_after_burn"))

    gui.advanced_params_group.setTitle(gui.tr("advanced_params_group"))
    gui.timeout_label.setText(gui.tr("command_timeout"))
    gui.timeout_spinbox.setSuffix(f" {gui.tr('seconds')}")
    gui.retry_count_label.setText(gui.tr("retry_count"))
    gui.retry_count_spinbox.setSuffix(f" {gui.tr('times')}")

    gui.device_info_group.setTitle(gui.tr("device_info_group"))
    gui.get_device_info_btn.setText(gui.tr("get_detailed_info_btn"))
    gui.get_security_info_btn.setText(gui.tr("get_security_info_btn"))


def update_upgrade_tab_texts(gui):
    """Update upgrade/pack tab texts"""
    gui.tab_widget.setTabText(3, gui.tr("upgrade_tab"))

    gui.pack_group.setTitle(gui.tr("firmware_upgrade_group"))
    gui.pack_label.setText(gui.tr("pack_label"))
    gui.pack_browse_btn.setText(gui.tr("browse_btn"))
    gui.pack_btn.setText(gui.tr("pack_btn"))

    gui.unpack_group.setTitle(gui.tr("unpack_label"))
    gui.unpack_label.setText(gui.tr("unpack_label"))
    gui.unpack_browse_btn.setText(gui.tr("browse_btn"))
    gui.unpack_btn.setText(gui.tr("unpack_btn"))

    gui.pack_ops_group.setTitle(gui.tr("pack_ops_group"))
    gui.gpt_label.setText(gui.tr("gpt_label"))
    gui.gpt_browse_btn.setText(gui.tr("browse_btn"))
    gui.gpt_export_btn.setText(gui.tr("gpt_export_btn"))
    gui.gpt_btn.setText(gui.tr("gpt_btn"))

    gui.prm_label.setText(gui.tr("prm_label"))
    gui.prm_text.setPlaceholderText(gui.tr("prm_placeholder"))
    gui.prm_btn.setText(gui.tr("prm_btn"))

    gui.tagspl_label.setText(gui.tr("tagspl_label"))
    gui.tagspl_browse_btn.setText(gui.tr("browse_btn"))
    gui.tagspl_btn.setText(gui.tr("tagspl_btn"))


def update_advanced_tab_texts(gui):
    """Update advanced tab texts"""
    gui.tab_widget.setTabText(4, gui.tr("advanced_tab"))

    gui.flash_ops_group.setTitle(gui.tr("flash_ops_group"))

    gui.rw_ops_group.setTitle(gui.tr("rw_ops_group"))
    gui.read_address_label.setText(gui.tr("start_address"))
    gui.read_address.setPlaceholderText(gui.tr("start_address_placeholder"))
    gui.read_length_label.setText(gui.tr("read_length_placeholder"))
    gui.read_length.setPlaceholderText(gui.tr("read_length_placeholder"))
    gui.read_save_path_label.setText(gui.tr("save_path_placeholder"))
    gui.read_save_path.setPlaceholderText(gui.tr("save_path_placeholder"))
    gui.read_browse_btn.setText(gui.tr("browse_btn"))
    gui.read_flash_btn.setText(gui.tr("read_flash_btn"))

    gui.verify_group.setTitle(gui.tr("verify_tools_group"))
    gui.verify_file_label.setText(gui.tr("verify_file_placeholder"))
    gui.verify_file_path.setPlaceholderText(gui.tr("verify_file_placeholder"))
    gui.verify_browse_btn.setText(gui.tr("browse_btn"))
    gui.verify_address_label.setText(gui.tr("verify_address_placeholder"))
    gui.verify_address.setPlaceholderText(gui.tr("verify_address_placeholder"))
    gui.verify_btn.setText(gui.tr("verify_file_btn"))
    gui.calculate_md5_btn.setText(gui.tr("calculate_md5_btn"))

    gui.verify_sector_label.setText(gui.tr("verify_sector_label"))
    gui.verify_sector_combo.clear()
    gui.verify_sector_combo.addItem(gui.tr("verify_sector_512"), "512")
    gui.verify_sector_combo.addItem(gui.tr("verify_sector_4096"), "4096")
    gui.verify_sector_combo.addItem(gui.tr("verify_sector_custom"), "custom")
    gui.verify_sector_custom.setPlaceholderText(gui.tr("verify_sector_custom_placeholder"))

    # Boot operations (Week 6)
    if hasattr(gui, 'boot_group') and gui.boot_group:
        gui.boot_group.setTitle("🔧 Boot 文件操作" if gui.manager.lang == "zh" else "Boot File Operations")
        if hasattr(gui, 'download_boot_btn') and gui.download_boot_btn:
            gui.download_boot_btn.setText(gui.tr("download_boot_btn"))
        if hasattr(gui, 'upload_boot_btn') and gui.upload_boot_btn:
            gui.upload_boot_btn.setText(gui.tr("upload_boot_btn"))

    gui.debug_group.setTitle(gui.tr("debug_tools_group"))
    gui.enable_debug_log.setText(gui.tr("enable_debug_log"))
    gui.export_log_btn.setText(gui.tr("export_system_log_btn"))
    gui.show_usb_info_btn.setText(gui.tr("show_usb_info_btn"))

    # Mass production
    gui.mass_production_group.setTitle(gui.tr("mass_start_production"))
    gui.mass_scan_btn.setText(gui.tr("mass_device_scan"))
    gui.mass_firmware_label.setText(gui.tr("mass_firmware_select"))
    gui.mass_firmware_browse_btn.setText(gui.tr("browse_btn"))
    gui.mass_start_btn.setText(gui.tr("mass_start_production"))
    gui.mass_stop_btn.setText(gui.tr("mass_stop_production"))


def update_misc_texts(gui):
    """Update miscellaneous texts"""
    # These are already updated in other functions
    pass


def update_statusbar_texts(gui):
    """Update status bar texts"""
    gui.statusBar().showMessage(
        f"{gui.tr('ready_status')}{gui.tr('status_line_delimiter')}{gui.tr('not_connected_status')}"
    )
    gui.connection_status.setText(f"⚪ {gui.tr('not_connected')}")
    gui.update_device_status()


def populate_address_combo(gui):
    """Populate address combo box in download tab"""
    try:
        gui.address_combo.clear()
        gui.address_combo.addItem(gui.tr("address_full_firmware"))
        gui.address_combo.addItem(gui.tr("custom_address"))

        # Add parsed partitions if available
        if hasattr(gui, 'partitions') and gui.partitions:
            for name, info in gui.partitions.items():
                addr = info.get('address', '')
                gui.address_combo.addItem(f"{name} ({addr})")
    except:
        pass


def populate_partition_combo(gui):
    """Populate partition combo box"""
    try:
        gui.partition_combo.clear()
        if hasattr(gui, 'partitions') and gui.partitions:
            for name, info in gui.partitions.items():
                addr = info.get('address', '')
                display = f"{name} ({addr})"
                gui.partition_combo.addItem(display, name)
    except:
        pass