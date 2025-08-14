# src/agent/vnc_widget.py

import socket
import struct
import threading
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QImage, QPainter, QMouseEvent, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal, QObject

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

        # Enable mouse and keyboard tracking
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def connect_to_vnc(self, host, port, password):
        self.password = password
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        
        self.is_running = True
        self.thread = threading.Thread(target=self._vnc_thread)
        self.thread.daemon = True
        self.thread.start()

    def _send(self, data):
        self.sock.sendall(data)

    def _recv(self, length):
        data = b''
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise ConnectionAbortedError("VNC connection closed.")
            data += chunk
        return data

    def _vnc_thread(self):
        """Main thread to handle the VNC protocol."""
        try:
            # 1. Protocol Version Handshake
            version = self._recv(12).decode().strip()
            self._send(version.encode())

            # 2. Security Handshake
            num_sec_types = self._recv(1)[0]
            sec_types = self._recv(num_sec_types)
            # We only support VNC Authentication (type 2)
            if 2 not in sec_types:
                raise ValueError("VNC Authentication not supported by server.")
            self._send(b'\x02') # Choose VNC Authentication

            # 3. VNC Authentication
            challenge = self._recv(16)
            # A simple password encryption for the challenge
            key = self._get_des_key(self.password)
            import des
            response = des.DesKey(key).encrypt(challenge, padding=True)
            self._send(response)
            
            status = struct.unpack('>I', self._recv(4))[0]
            if status != 0:
                raise ValueError("VNC Authentication failed.")

            # 4. Client/Server Init
            self._send(b'\x01') # Share desktop flag
            
            # ServerInit message
            width, height = struct.unpack('>HH', self._recv(4))
            bpp, depth, big_endian, true_color = struct.unpack('>BBBB', self._recv(4))
            red_max, green_max, blue_max = struct.unpack('>HHH', self._recv(6))
            red_shift, green_shift, blue_shift = struct.unpack('>BBB', self._recv(3))
            self._recv(3) # padding
            name_len = struct.unpack('>I', self._recv(4))[0]
            self._recv(name_len) # Skip desktop name

            print(f"VNC Server: {width}x{height}, {bpp}bpp, depth={depth}")
            self.image = QImage(width, height, QImage.Format.Format_RGB32)
            self.update()

            # 5. Set Pixel Format to RGB32
            # SetPixelFormat message: msg-type(1) + padding(3) + pixel-format(16)
            pixel_format = struct.pack('>BBBBHHHBBB3x', 
                32, 24, 0, 1,  # bpp, depth, big_endian, true_color
                255, 255, 255,  # red_max, green_max, blue_max  
                16, 8, 0)       # red_shift, green_shift, blue_shift
            self._send(b'\x00' + b'\x00\x00\x00' + pixel_format)
            
            # SetEncodings message: we only support Raw encoding (0)
            self._send(struct.pack('>BBHI', 2, 0, 1, 0))

            # 6. Main Loop
            while self.is_running:
                # Request a full screen update (non-incremental first time)
                self._send(struct.pack('>BBHHHH', 3, 0, 0, 0, width, height))
                
                # Process server messages
                msg_type = self._recv(1)[0]
                if msg_type == 0: # FramebufferUpdate
                    self._recv(1) # padding
                    num_rects = struct.unpack('>H', self._recv(2))[0]
                    print(f"Received {num_rects} rectangles")
                    for _ in range(num_rects):
                        x, y, w, h, encoding = struct.unpack('>HHHHi', self._recv(12))
                        print(f"Rectangle: {x},{y} {w}x{h} encoding={encoding}")
                        if encoding == 0: # Raw encoding
                            bytes_per_pixel = 4
                            data = self._recv(w * h * bytes_per_pixel)
                            for j in range(h):
                                for i in range(w):
                                    pixel_start = (j * w + i) * bytes_per_pixel
                                    pixel = data[pixel_start:pixel_start+bytes_per_pixel]
                                    # Convert BGRA to ARGB for QImage
                                    if len(pixel) >= 4:
                                        color = (255 << 24) | (pixel[2] << 16) | (pixel[1] << 8) | pixel[0]
                                        self.image.setPixel(x + i, y + j, color)
                    self.update() # Trigger a repaint
                    
                    # Request incremental updates
                    self._send(struct.pack('>BBHHHH', 3, 1, 0, 0, width, height))

        except (ConnectionAbortedError, ValueError, struct.error) as e:
            print(f"VNC thread error: {e}")
        finally:
            self.is_running = False
            self.sock.close()

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
        if not self.is_running: return
        button_mask = 0
        if event.buttons() & Qt.MouseButton.LeftButton: button_mask |= 1
        if event.buttons() & Qt.MouseButton.MiddleButton: button_mask |= 2
        if event.buttons() & Qt.MouseButton.RightButton: button_mask |= 4
        
        x, y = int(event.position().x()), int(event.position().y())
        self._send(struct.pack('>BBHH', 5, button_mask, x, y))

    def keyPressEvent(self, event: QKeyEvent):
        self._send_key_event(event, 1)

    def keyReleaseEvent(self, event: QKeyEvent):
        self._send_key_event(event, 0)

    def _send_key_event(self, event: QKeyEvent, down_flag):
        if not self.is_running: return
        keysym = event.nativeVirtualKey()
        self._send(struct.pack('>BBxxI', 4, down_flag, keysym))

    def closeEvent(self, event):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        super().closeEvent(event)

