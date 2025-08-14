# src/agent/simple_vnc_widget.py

import subprocess
import tempfile
import os
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtGui import QPixmap, QMouseEvent, QKeyEvent
from PyQt6.QtCore import QTimer, Qt

class SimpleVncWidget(QWidget):
    """
    A simple VNC widget that uses vncdotool to capture screenshots
    and displays them in a QLabel with mouse and keyboard interaction.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = None
        self.port = None
        self.password = None
        self.temp_file = None
        self.vnc_scale_x = 1.0
        self.vnc_scale_y = 1.0
        self.vnc_width = 1280
        self.vnc_height = 720
        
        # Setup UI
        self.layout = QVBoxLayout(self)
        self.image_label = QLabel("Connecting to VNC...")
        self.image_label.setStyleSheet("background-color: lightblue; color: black; font-size: 18px;")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.image_label)
        
        # Enable mouse and keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.image_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.image_label.mousePressEvent = self.mouse_press_event
        self.image_label.mouseReleaseEvent = self.mouse_release_event
        self.image_label.mouseMoveEvent = self.mouse_move_event
        
        # Timer for refreshing the screen
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.capture_screen)
        
    def connect_to_vnc(self, host, port, password):
        self.host = host
        self.port = port 
        self.password = password
        
        # Create temporary file for screenshots
        self.temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        self.temp_file.close()
        
        self.image_label.setText("Connected! Loading desktop...")
        
        # Start capturing screenshots every 1 second for better responsiveness
        self.refresh_timer.start(1000)
        
        # Capture first screenshot immediately
        self.capture_screen()
        
    def calculate_vnc_coordinates(self, widget_x, widget_y):
        """Convert widget coordinates to VNC coordinates"""
        if self.image_label.pixmap():
            pixmap = self.image_label.pixmap()
            # Calculate scaling factors
            self.vnc_scale_x = self.vnc_width / pixmap.width()
            self.vnc_scale_y = self.vnc_height / pixmap.height()
            
            # Calculate VNC coordinates
            vnc_x = int(widget_x * self.vnc_scale_x)
            vnc_y = int(widget_y * self.vnc_scale_y)
            
            # Clamp to VNC bounds
            vnc_x = max(0, min(vnc_x, self.vnc_width - 1))
            vnc_y = max(0, min(vnc_y, self.vnc_height - 1))
            
            return vnc_x, vnc_y
        return widget_x, widget_y
    
    def send_vnc_command(self, command_args):
        """Send a command to VNC using vncdotool"""
        if not self.host or not self.port or not self.password:
            return
            
        try:
            cmd = [
                'vncdo', 
                '-s', f'{self.host}::{self.port}',
                '--password', self.password
            ] + command_args
            
            subprocess.run(cmd, capture_output=True, timeout=2)
        except Exception as e:
            print(f"VNC command error: {e}")
    
    def mouse_press_event(self, event):
        """Handle mouse press events"""
        vnc_x, vnc_y = self.calculate_vnc_coordinates(event.position().x(), event.position().y())
        
        if event.button() == Qt.MouseButton.LeftButton:
            self.send_vnc_command(['click', str(vnc_x), str(vnc_y)])
        elif event.button() == Qt.MouseButton.RightButton:
            self.send_vnc_command(['rightclick', str(vnc_x), str(vnc_y)])
            
        # Refresh screen immediately after click
        self.capture_screen()
    
    def mouse_release_event(self, event):
        """Handle mouse release events"""
        pass  # vncdotool handles click release automatically
    
    def mouse_move_event(self, event):
        """Handle mouse move events"""
        vnc_x, vnc_y = self.calculate_vnc_coordinates(event.position().x(), event.position().y())
        self.send_vnc_command(['mousemove', str(vnc_x), str(vnc_y)])
    
    def keyPressEvent(self, event):
        """Handle keyboard events"""
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.send_vnc_command(['key', 'Return'])
        elif event.key() == Qt.Key.Key_Escape:
            self.send_vnc_command(['key', 'Escape'])
        elif event.key() == Qt.Key.Key_Tab:
            self.send_vnc_command(['key', 'Tab'])
        elif event.key() == Qt.Key.Key_Backspace:
            self.send_vnc_command(['key', 'BackSpace'])
        elif event.key() == Qt.Key.Key_Delete:
            self.send_vnc_command(['key', 'Delete'])
        elif event.key() == Qt.Key.Key_Space:
            self.send_vnc_command(['key', 'space'])
        else:
            # Handle regular characters
            text = event.text()
            if text and text.isprintable():
                self.send_vnc_command(['type', text])
        
        # Refresh screen after key press
        self.capture_screen()
        super().keyPressEvent(event)
        
    def capture_screen(self):
        if not self.host or not self.port or not self.password:
            return
            
        try:
            # Use vncdotool to capture screenshot
            cmd = [
                'vncdo', 
                '-s', f'{self.host}::{self.port}',
                '--password', self.password,
                'capture', self.temp_file.name
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and os.path.exists(self.temp_file.name):
                # Load and display the screenshot
                pixmap = QPixmap(self.temp_file.name)
                if not pixmap.isNull():
                    # Scale to fit the widget
                    scaled_pixmap = pixmap.scaled(
                        self.size(), 
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.image_label.setPixmap(scaled_pixmap)
                    self.image_label.setText("")  # Clear text when image is shown
            else:
                self.image_label.setText(f"VNC Error: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            self.image_label.setText("VNC Timeout")
        except Exception as e:
            self.image_label.setText(f"Error: {str(e)}")
    
    def closeEvent(self, event):
        self.refresh_timer.stop()
        if self.temp_file and os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
        super().closeEvent(event)
