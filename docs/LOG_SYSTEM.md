"""
Real-time Log System Implementation Guide
==========================================

This document describes the enhanced real-time logging system for RKDevelopTool-GUI.

## Features

1. **Real-time stdout Streaming**
   - Character-by-character reading from subprocess stdout
   - No buffering delays - logs appear immediately
   - Comprehensive ANSI code removal for clean output

2. **Progress Bar with % Parsing**
   - Automatically parses % values from output
   - Updates progress bar in real-time
   - Shows current progress percentage

3. **Enhanced Log UI**
   - Color-coded log levels (INFO, ERROR, WARNING, SUCCESS, COMMAND, START)
   - Automatic timestamps for each log entry
   - Auto-scrolling to latest messages
   - Maximum 1000 lines for performance

## Architecture

### Components

1. **log_widget.py - RealtimeLogWidget**
   - Main UI widget for displaying logs
   - Features:
     * Color-coded log levels
     * Timestamp formatting
     * Progress bar integration
     * Auto-scroll functionality
     * Clear and Export buttons

2. **workers.py - CommandWorker**
   - Enhanced subprocess executor
   - Features:
     * Real-time stdout streaming
     * ANSI code removal
     * Progress percentage extraction
     * Efficient line buffering
     * Deduplication of logs

3. **rkdevtoolgui.py - Main Integration**
   - Replaces old static log panel
   - Uses RealtimeLogWidget for dynamic logging
   - Connects worker signals to log widget

## Usage

### Basic Logging

```python
# Log messages automatically appear with:
# - Timestamp
# - Color coding based on log level
# - Progress parsing

# In CommandWorker, emit log signals:
self.log.emit("[ERROR] Connection failed")
self.log.emit("[SUCCESS] Operation completed")
self.log.emit("Flashing: 45%")  # Progress will be parsed
```

### Log Levels

The system recognizes these log levels:

- **ERROR**: Red text - errors and failures
- **WARNING**: Orange text - warnings
- **SUCCESS** / **OK**: Green text - successful operations
- **INFO**: Gray text - general information
- **COMMAND**: Light blue - commands being executed
- **START**: Blue - operation start messages

### Timestamps

Every log entry automatically includes a timestamp in HH:MM:SS format:

```
[14:23:45] [START] Starting operation...
[14:23:46] [COMMAND] /usr/bin/rkdeveloptool ld
[14:23:47] Flashing firmware... 25%
[14:23:48] Flashing firmware... 50%
[14:23:49] Flashing firmware... 75%
[14:23:50] Flashing firmware... 100%
[14:23:51] [OK] Operation completed successfully
```

### Progress Bar

Progress is automatically extracted from log messages containing '%':

```python
# This message will update the progress bar to 45%
self.log.emit("Flashing: 45%")

# The progress label will show "Progress: 45%"
# The progress bar will fill to 45%
```

## Integration Points

### In CommandWorker (workers.py)

The worker automatically:
1. Reads stdout in real-time
2. Removes ANSI codes
3. Extracts progress percentages
4. Emits log signals with clean text

### In Main GUI (rkdevtoolgui.py)

The GUI:
1. Creates RealtimeLogWidget instance
2. Connects worker signals to log_message()
3. Displays logs with colors and timestamps
4. Updates progress bar automatically

## Performance Optimization

- **Max 1000 lines**: Buffer limited for performance
- **Deduplication**: Prevents duplicate log entries
- **Efficient ANSI removal**: Uses compiled regex patterns
- **Signal batching**: Groups small chunks to reduce overhead

## Customization

### Change Log Colors

Edit log_widget.py LOG_COLORS dictionary:

```python
LOG_COLORS = {
    'ERROR': QColor(255, 85, 85),      # Red
    'WARNING': QColor(255, 170, 0),    # Orange
    'SUCCESS': QColor(85, 255, 85),    # Green
    # ... customize as needed
}
```

### Change Max Buffer Size

Edit log_widget.py:

```python
self.max_lines = 2000  # Increase from 1000
```

### Change Font

Edit log_widget.py init_ui():

```python
self.log_display.setFont(QFont("Monaco", 10))  # Change font
```

## Troubleshooting

### Logs not appearing in real-time

Check that:
1. Worker emits log signals: `self.log.emit(message)`
2. Signal is connected: `worker.log.connect(safe_slot(self.log_message))`
3. Process stdout is not fully buffered

### Progress not updating

Check that:
1. Output contains percentage: "45%" format
2. Progress signal is connected: `worker.progress.connect(...)`
3. Value is between 0-100

### ANSI codes still visible

The system removes standard ANSI codes, but some tools use custom codes.
Add patterns to _clean_ansi_codes() in workers.py for new formats.

## Future Enhancements

- [ ] Log filtering by level
- [ ] Search functionality
- [ ] Log rotation/archiving
- [ ] Live graph display for progress
- [ ] Custom color themes
- [ ] Log persistence to database
"""
