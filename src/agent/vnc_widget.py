# src/agent/vnc_widget.py

import socket
import struct
import threading
import des
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QImage, QPainter, QMouseEvent, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer

class VncWidget(QWidget):
    """
    A simple, self-contained VNC client widget.
    This handles the basic VNC protocol (RFB) to display a remote desktop.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage(1, 1, QImage.Format.Format_RGB32)
        self.password = ""
        self.sock = None
        self.thread = None
        self.is_running = False
        self.width = 0
        self.height = 0

        # Enable mouse and keyboard tracking
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def connect_to_vnc(self, host, port, password):
        """Connect to VNC server and start the protocol thread."""
        self.password = password
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)  # 10 second timeout for connection
            self.sock.connect((host, port))
            print(f"Connected to VNC server at {host}:{port}")
            
            self.is_running = True
            self.thread = threading.Thread(target=self._vnc_thread)
            self.thread.daemon = True
            self.thread.start()
        except Exception as e:
            print(f"Failed to connect to VNC server: {e}")
            if self.sock:
                self.sock.close()
            raise

    def _send(self, data):
        """Send data to VNC server with error handling."""
        try:
            self.sock.sendall(data)
        except Exception as e:
            print(f"Send error: {e}")
            self.is_running = False
            raise

    def _recv(self, length):
        """Receive exactly 'length' bytes from VNC server."""
        data = b''
        while len(data) < length and self.is_running:
            try:
                chunk = self.sock.recv(length - len(data))
                if not chunk:
                    raise ConnectionAbortedError("VNC connection closed by server.")
                data += chunk
            except socket.timeout:
                print("Receive timeout")
                raise
            except Exception as e:
                print(f"Receive error: {e}")
                self.is_running = False
                raise
        return data

    def _vnc_thread(self):
        """Main thread to handle the VNC protocol."""
        try:
            print("Starting VNC protocol handshake...")
            
            # 1. Protocol Version Handshake
            version = self._recv(12).decode().strip()
            print(f"Server version: {version}")
            self._send(version.encode())

            # 2. Security Handshake
            num_sec_types = self._recv(1)[0]
            sec_types = self._recv(num_sec_types)
            print(f"Security types: {list(sec_types)}")
            
            # We only support VNC Authentication (type 2)
            if 2 not in sec_types:
                raise ValueError("VNC Authentication not supported by server.")
            self._send(b'\x02') # Choose VNC Authentication

            # 3. VNC Authentication
            challenge = self._recv(16)
            key = self._get_des_key(self.password)
            response = des.DesKey(key).encrypt(challenge, padding=True)
            self._send(response)
            
            status = struct.unpack('>I', self._recv(4))[0]
            if status != 0:
                raise ValueError("VNC Authentication failed.")
            print("Authentication successful")

            # 4. Client/Server Init
            self._send(b'\x01') # Share desktop flag
            
            # ServerInit message
            self.width, self.height = struct.unpack('>HH', self._recv(4))
            bpp, depth, big_endian, true_color = struct.unpack('>BBBB', self._recv(4))
            red_max, green_max, blue_max = struct.unpack('>HHH', self._recv(6))
            red_shift, green_shift, blue_shift = struct.unpack('>BBB', self._recv(3))
            self._recv(3) # padding
            name_len = struct.unpack('>I', self._recv(4))[0]
            desktop_name = self._recv(name_len).decode() if name_len > 0 else "Unknown"

            print(f"Desktop: {desktop_name}, {self.width}x{self.height}, {bpp}bpp, depth={depth}")
            
            # Create the image with proper dimensions
            self.image = QImage(self.width, self.height, QImage.Format.Format_RGB32)
            self.image.fill(0)  # Fill with black initially
            
            # 5. Set Encodings - MUST come before any framebuffer requests
            # SetEncodings: msg-type(2) + padding(1) + num-encodings(2) + encodings(4*n)
            set_encodings = struct.pack('>BBHi', 2, 0, 1, 0)  # Type 2, 0 padding, 1 encoding, Raw(0)
            self._send(set_encodings)
            print("Set encodings to Raw")
            
            # Initial framebuffer request (non-incremental)
            self._send(struct.pack('>BBHHHH', 3, 0, 0, 0, self.width, self.height))
            print("Requested initial framebuffer")

            # 6. Main message loop
            while self.is_running:
                try:
                    # Process server messages
                    msg_type = self._recv(1)[0]
                    
                    if msg_type == 0:  # FramebufferUpdate
                        self._handle_framebuffer_update()
                    elif msg_type == 1:  # SetColourMapEntries
                        self._handle_color_map_entries()
                    elif msg_type == 2:  # Bell
                        print("Bell received")
                    elif msg_type == 3:  # ServerCutText
                        self._handle_server_cut_text()
                    else:
                        print(f"Unknown message type: {msg_type}")
                        
                except socket.timeout:
                    # Send keepalive incremental update request
                    if self.is_running:
                        self._send(struct.pack('>BBHHHH', 3, 1, 0, 0, self.width, self.height))
                    continue
                    
        except Exception as e:
            print(f"VNC thread error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("VNC thread ending")
            self.is_running = False
            if self.sock:
                self.sock.close()

    def _handle_framebuffer_update(self):
        """Handle framebuffer update message."""
        self._recv(1)  # padding
        num_rects = struct.unpack('>H', self._recv(2))[0]
        print(f"Received framebuffer update with {num_rects} rectangles")
        
        for _ in range(num_rects):
            x, y, w, h, encoding = struct.unpack('>HHHHi', self._recv(12))
            print(f"Rectangle: {x},{y} {w}x{h} encoding={encoding}")
            
            if encoding == 0:  # Raw encoding
                self._handle_raw_rectangle(x, y, w, h)
            else:
                print(f"Unsupported encoding: {encoding}")
                # Skip unknown encodings by reading appropriate amount of data
                # For now, we'll just fail
                raise ValueError(f"Unsupported encoding: {encoding}")
        
        # Trigger GUI update
        self.update()
        
        # Request incremental updates for continuous updates
        if self.is_running:
            self._send(struct.pack('>BBHHHH', 3, 1, 0, 0, self.width, self.height))

    def _handle_raw_rectangle(self, x, y, w, h):
        """Handle raw encoding rectangle."""
        bytes_per_pixel = 4  # Assuming 32-bit pixels
        data = self._recv(w * h * bytes_per_pixel)
        
        # Process pixel data
        for j in range(h):
            for i in range(w):
                if x + i >= self.width or y + j >= self.height:
                    continue
                    
                pixel_start = (j * w + i) * bytes_per_pixel
                if pixel_start + bytes_per_pixel <= len(data):
                    pixel = data[pixel_start:pixel_start + bytes_per_pixel]
                    # Convert BGRA to ARGB for QImage (server sends BGRA in little endian)
                    b, g, r, a = pixel[0], pixel[1], pixel[2], pixel[3] if len(pixel) > 3 else 255
                    color = (a << 24) | (r << 16) | (g << 8) | b
                    self.image.setPixel(x + i, y + j, color)

    def _handle_color_map_entries(self):
        """Handle color map entries message (not used in true color mode)."""
        self._recv(1)  # padding
        first_color = struct.unpack('>H', self._recv(2))[0]
        num_colors = struct.unpack('>H', self._recv(2))[0]
        # Skip the color data
        self._recv(num_colors * 6)  # 6 bytes per color (RGB, 2 bytes each)

    def _handle_server_cut_text(self):
        """Handle server cut text message."""
        self._recv(3)  # padding
        length = struct.unpack('>I', self._recv(4))[0]
        text = self._recv(length)  # Skip the cut text

    def _get_des_key(self, password):
        """Creates a DES key from a password with bit reversal for VNC."""
        key = bytearray(8)
        for i, char in enumerate(password.ljust(8, '\0')[:8]):
            byte = ord(char)
            # Reverse the bits in each byte (VNC requirement)
            reversed_byte = 0
            for j in range(8):
                if byte & (1 << j):
                    reversed_byte |= (1 << (7 - j))
            key[i] = reversed_byte
        return key

    def paintEvent(self, event):
        """Draws the VNC image to the widget."""
        painter = QPainter(self)
        painter.drawImage(self.rect(), self.image, self.image.rect())

    def mousePressEvent(self, event: QMouseEvent):
        self._send_pointer_event(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._send_pointer_event(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        self._send_pointer_event(event)

    def _send_pointer_event(self, event: QMouseEvent):
        """Send pointer event to VNC server."""
        if not self.is_running or not self.sock:
            return
            
        try:
            button_mask = 0
            if event.buttons() & Qt.MouseButton.LeftButton: 
                button_mask |= 1
            if event.buttons() & Qt.MouseButton.MiddleButton: 
                button_mask |= 2
            if event.buttons() & Qt.MouseButton.RightButton: 
                button_mask |= 4
            
            # Scale coordinates if widget is resized
            widget_width = self.width()
            widget_height = self.height()
            
            if widget_width > 0 and widget_height > 0:
                x = int(event.position().x() * self.width / widget_width)
                y = int(event.position().y() * self.height / widget_height)
                
                # Clamp coordinates to image bounds
                x = max(0, min(x, self.width - 1))
                y = max(0, min(y, self.height - 1))
                
                # PointerEvent: msg-type(5) + button-mask(1) + x(2) + y(2)
                self._send(struct.pack('>BBHH', 5, button_mask, x, y))
        except Exception as e:
            print(f"Error sending pointer event: {e}")

    def keyPressEvent(self, event: QKeyEvent):
        self._send_key_event(event, 1)

    def keyReleaseEvent(self, event: QKeyEvent):
        self._send_key_event(event, 0)

    def _send_key_event(self, event: QKeyEvent, down_flag):
        """Send key event to VNC server."""
        if not self.is_running or not self.sock:
            return
            
        try:
            # Convert Qt key to X11 keysym
            keysym = self._qt_key_to_keysym(event.key())
            if keysym:
                # KeyEvent: msg-type(4) + down-flag(1) + padding(2) + keysym(4)
                self._send(struct.pack('>BBxxI', 4, down_flag, keysym))
        except Exception as e:
            print(f"Error sending key event: {e}")

    def _qt_key_to_keysym(self, qt_key):
        """Convert Qt key code to X11 keysym."""
        # Basic mapping for common keys
        key_map = {
            Qt.Key.Key_Return: 0xFF0D,      # Return
            Qt.Key.Key_Enter: 0xFF0D,       # Enter
            Qt.Key.Key_Backspace: 0xFF08,   # BackSpace
            Qt.Key.Key_Tab: 0xFF09,         # Tab
            Qt.Key.Key_Escape: 0xFF1B,      # Escape
            Qt.Key.Key_Space: 0x0020,       # Space
            Qt.Key.Key_Delete: 0xFFFF,      # Delete
            Qt.Key.Key_Home: 0xFF50,        # Home
            Qt.Key.Key_End: 0xFF57,         # End
            Qt.Key.Key_PageUp: 0xFF55,      # Page_Up
            Qt.Key.Key_PageDown: 0xFF56,    # Page_Down
            Qt.Key.Key_Left: 0xFF51,        # Left
            Qt.Key.Key_Up: 0xFF52,          # Up
            Qt.Key.Key_Right: 0xFF53,       # Right
            Qt.Key.Key_Down: 0xFF54,        # Down
            Qt.Key.Key_Shift: 0xFFE1,       # Shift_L
            Qt.Key.Key_Control: 0xFFE3,     # Control_L
            Qt.Key.Key_Alt: 0xFFE9,         # Alt_L
        }
        
        if qt_key in key_map:
            return key_map[qt_key]
        
        # For printable characters, use ASCII value
        if 0x20 <= qt_key <= 0x7E:  # Printable ASCII range
            return qt_key
            
        # Function keys
        if Qt.Key.Key_F1 <= qt_key <= Qt.Key.Key_F12:
            return 0xFFBE + (qt_key - Qt.Key.Key_F1)
        
        return qt_key  # Fallback

    def disconnect_vnc(self):
        """Disconnect from VNC server and cleanup."""
        print("Disconnecting from VNC server...")
        self.is_running = False
        
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        
        self.thread = None

    def closeEvent(self, event):
        """Handle widget close event."""
        self.disconnect_vnc()
        super().closeEvent(event)

