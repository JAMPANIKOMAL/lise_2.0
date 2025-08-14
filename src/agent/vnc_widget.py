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
            self._recv(12) # Skip pixel format details
            name_len = struct.unpack('>I', self._recv(4))[0]
            self._recv(name_len) # Skip desktop name

            self.image = QImage(width, height, QImage.Format.Format_RGB32)
            self.update()

            # 5. Set Pixel Format and Encodings
            # We tell the server we want raw 32-bit pixel data
            self._send(struct.pack('>BxxxHHHBBBx', 0, width, height, 32, 24, 0, 1, 255, 255, 255, 0, 8, 16))
            self._send(struct.pack('>BxxxI', 2, 1, 0)) # We only support Raw encoding

            # 6. Main Loop
            while self.is_running:
                # Request a full screen update
                self._send(struct.pack('>BHHHH', 3, 0, 0, width, height, 0))
                
                # Process server messages
                msg_type = self._recv(1)[0]
                if msg_type == 0: # FramebufferUpdate
                    self._recv(1) # padding
                    num_rects = struct.unpack('>H', self._recv(2))[0]
                    for _ in range(num_rects):
                        x, y, w, h, encoding = struct.unpack('>HHHHi', self._recv(12))
                        if encoding == 0: # Raw encoding
                            data = self._recv(w * h * 4)
                            for j in range(h):
                                for i in range(w):
                                    pixel_start = (j * w + i) * 4
                                    pixel = data[pixel_start:pixel_start+4]
                                    # VNC sends BGRx, QImage wants ARGB
                                    color = (255 << 24) | (pixel[2] << 16) | (pixel[1] << 8) | pixel[0]
                                    self.image.setPixel(x + i, y + j, color)
                    self.update() # Trigger a repaint

        except (ConnectionAbortedError, ValueError, struct.error) as e:
            print(f"VNC thread error: {e}")
        finally:
            self.is_running = False
            self.sock.close()

    def _get_des_key(self, password):
        """Creates a DES key from a password."""
        key = bytearray(8)
        for i, char in enumerate(password.ljust(8, '\0')[:8]):
            key[i] = ord(char)
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

