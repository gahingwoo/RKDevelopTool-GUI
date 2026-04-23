"""
Real-time log widget with live streaming display
Provides color-coded log levels, timestamps, and auto-scrolling
"""
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QLabel, QProgressBar
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor, QFont, QColor, QTextCharFormat
import re


class RealtimeLogWidget(QWidget):
    """Enhanced real-time log display widget with colors and timestamps"""
    
    # Log level colors
    LOG_COLORS = {
        'ERROR': QColor(255, 85, 85),      # Red
        'WARNING': QColor(255, 170, 0),    # Orange
        'SUCCESS': QColor(85, 255, 85),    # Green
        'OK': QColor(85, 255, 85),         # Green
        'INFO': QColor(170, 170, 170),     # Gray
        'COMMAND': QColor(100, 200, 255),  # Light Blue
        'START': QColor(150, 150, 255),    # Blue
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.log_buffer = []
        self.max_lines = 1000  # Limit to 1000 lines for performance
        
    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Courier", 9))
        self.log_display.setMinimumHeight(150)
        
        # Progress bar section
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        
        self.progress_label = QLabel("Progress: 0%")
        self.progress_label.setMinimumWidth(80)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)
        
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar, 1)
        
        # Control buttons
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.clicked.connect(self.clear_log)
        
        self.export_btn = QPushButton("Export Log")
        self.export_btn.setMinimumWidth(100)
        
        button_layout.addWidget(self.clear_btn)
        button_layout.addWidget(self.export_btn)
        button_layout.addStretch()
        
        # Assemble layout
        layout.addLayout(button_layout)
        layout.addWidget(self.log_display)
        layout.addLayout(progress_layout)
        
        self.setLayout(layout)
    
    def add_log(self, message):
        """Add a log message with color coding and timestamp"""
        # Extract log level
        level = self._extract_log_level(message)
        
        # Add timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}"
        
        # Parse progress percentage
        progress = self._extract_progress(message)
        if progress is not None:
            self.set_progress(progress)
        
        # Store in buffer
        self.log_buffer.append((formatted_msg, level))
        
        # Limit buffer size
        if len(self.log_buffer) > self.max_lines:
            self.log_buffer.pop(0)
        
        # Update display
        self._update_display()
    
    def _extract_log_level(self, message):
        """Extract log level from message"""
        if "[ERROR]" in message or "[CRITICAL]" in message:
            return "ERROR"
        elif "[WARNING]" in message or "[WARN]" in message:
            return "WARNING"
        elif "[OK]" in message or "[SUCCESS]" in message:
            return "SUCCESS"
        elif "[COMMAND]" in message:
            return "COMMAND"
        elif "[START]" in message:
            return "START"
        else:
            return "INFO"
    
    def _extract_progress(self, message):
        """Extract progress percentage from message"""
        match = re.search(r'(\d+)%', message)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, AttributeError):
                return None
        return None
    
    def _update_display(self):
        """Update the log display with colored text"""
        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_display.setTextCursor(cursor)
        
        # Clear and rebuild (more efficient for large buffers)
        self.log_display.clear()
        
        for msg, level in self.log_buffer:
            # Set text color based on level
            fmt = QTextCharFormat()
            fmt.setForeground(self.LOG_COLORS.get(level, QColor(170, 170, 170)))
            fmt.setFont(QFont("Courier", 9))
            
            # Add to document
            cursor.insertText(msg + "\n", fmt)
        
        # Auto-scroll to bottom
        cursor.movePosition(QTextCursor.End)
        self.log_display.setTextCursor(cursor)
    
    def set_progress(self, value):
        """Set progress bar value (0-100)"""
        value = max(0, min(100, value))
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"Progress: {value}%")
    
    def clear_log(self):
        """Clear all logs"""
        self.log_buffer.clear()
        self.log_display.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Progress: 0%")
    
    def get_log_text(self):
        """Get all log text"""
        return "\n".join([msg for msg, _ in self.log_buffer])
    
    def set_clear_callback(self, callback):
        """Set callback for clear button"""
        self.clear_btn.clicked.disconnect()
        self.clear_btn.clicked.connect(callback)
    
    def set_export_callback(self, callback):
        """Set callback for export button"""
        self.export_btn.clicked.connect(callback)
    
    def toPlainText(self):
        """Get plain text for saving (for compatibility with save_log function)"""
        return self.log_display.toPlainText()
