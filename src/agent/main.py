# src/agent/main.py

import sys
import socketio
import docker
import time 
import socket 
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QStackedWidget)
from PyQt6.QtCore import QThread, pyqtSignal
from simple_vnc_widget import SimpleVncWidget

# --- VNC Connection Thread ---
# This new thread handles the potentially blocking process of finding the VNC port
# and waiting for the VNC service to be ready. This prevents the main communication
# thread from freezing.
class VncConnectionThread(QThread):
    log_message = pyqtSignal(str)
    connection_successful = pyqtSignal(str, int)
    connection_failed = pyqtSignal(str)

    def __init__(self, container_id, docker_client):
        super().__init__()
        self.container_id = container_id
        self.docker_client = docker_client

    def run(self):
        try:
            max_retries = 10
            retry_delay = 2  # seconds
            host_port = None

            self.log_message.emit(f"VM container {self.container_id[:12]} started. Waiting for network port...")

            # 1. Robustly wait for the container's port to be mapped by Docker
            for i in range(max_retries):
                container = self.docker_client.containers.get(self.container_id)
                container.reload()  # Refresh container data from the Docker daemon
                
                if container.ports and '5901/tcp' in container.ports and container.ports['5901/tcp'] is not None:
                    host_port = int(container.ports['5901/tcp'][0]['HostPort'])
                    self.log_message.emit(f"Network port found: {host_port}. Probing for VNC service...")
                    break
                else:
                    self.log_message.emit(f"Waiting for network... attempt {i+1}/{max_retries}")
                    time.sleep(retry_delay)
            
            if host_port is None:
                self.connection_failed.emit("Container started but could not find VNC port after multiple retries.")
                return

            # 2. Wait for the VNC service on that port to become responsive
            for i in range(max_retries):
                try:
                    with socket.create_connection(("127.0.0.1", host_port), timeout=1):
                        self.log_message.emit("VNC service is responsive. Connecting...")
                        self.connection_successful.emit("127.0.0.1", host_port)
                        return
                except (socket.timeout, ConnectionRefusedError):
                    self.log_message.emit(f"VNC connection attempt {i+1}/{max_retries} failed. Retrying...")
                    time.sleep(retry_delay)
            
            self.connection_failed.emit("Could not connect to VNC server after multiple retries.")

        except Exception as e:
            self.connection_failed.emit(f"An unexpected error occurred: {e}")


# --- SocketIO Client Thread ---
class ClientThread(QThread):
    connection_status = pyqtSignal(str)
    # New signal that passes the container ID to the main thread
    start_vnc_setup = pyqtSignal(str) 
    
    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url
        self.sio = socketio.Client()
        
        @self.sio.event
        def connect():
            self.connection_status.emit("Connected to Orchestrator")

        @self.sio.event
        def disconnect():
            self.connection_status.emit("Disconnected")

        @self.sio.on('start_vm')
        def start_vm(data):
            container_id = data.get('container_id')
            if container_id:
                # Don't do blocking work here. Just signal the main thread.
                self.start_vnc_setup.emit(container_id)

    def run(self):
        try:
            self.sio.connect(self.server_url)
            self.sio.wait()
        except socketio.exceptions.ConnectionError as e:
            self.connection_status.emit(f"Failed to connect: {e}")

    def send_log(self, message):
        if self.sio.connected:
            self.sio.emit('agent_log', message)

# --- Main Agent Window ---
class AgentWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LISE 2.0 - Agent")
        self.setGeometry(100, 100, 1280, 760)
        
        self.client_thread = None
        self.vnc_connection_thread = None
        self.docker_client = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login_widget = QWidget()
        login_layout = QVBoxLayout(self.login_widget)
        self.status_label = QLabel("Enter Orchestrator IP and connect.")
        self.ip_input = QLineEdit("http://127.0.0.1:5000")
        self.connect_button = QPushButton("Connect")
        login_layout.addWidget(self.status_label)
        login_layout.addWidget(self.ip_input)
        login_layout.addWidget(self.connect_button)
        self.stack.addWidget(self.login_widget)
        
        self.vnc_widget = SimpleVncWidget(self)
        self.stack.addWidget(self.vnc_widget)

        self.connect_button.clicked.connect(self.connect_to_server)

    def connect_to_server(self):
        try:
            self.docker_client = docker.from_env()
        except docker.errors.DockerException as e:
            self.update_status(f"Docker Error: {e}. Please start Docker Desktop.")
            return

        server_url = self.ip_input.text()
        self.status_label.setText(f"Connecting to {server_url}...")
        
        self.client_thread = ClientThread(server_url)
        self.client_thread.connection_status.connect(self.update_status)
        self.client_thread.start_vnc_setup.connect(self.on_start_vnc_setup)
        self.client_thread.start()
        
        self.connect_button.setEnabled(False)
        self.ip_input.setEnabled(False)

    def on_start_vnc_setup(self, container_id):
        """Starts the VNC connection thread."""
        self.vnc_connection_thread = VncConnectionThread(container_id, self.docker_client)
        self.vnc_connection_thread.log_message.connect(self.send_log_to_orchestrator)
        self.vnc_connection_thread.connection_successful.connect(self.start_vnc_session)
        self.vnc_connection_thread.connection_failed.connect(self.on_vnc_connection_failed)
        self.vnc_connection_thread.start()

    def send_log_to_orchestrator(self, message):
        if self.client_thread:
            self.client_thread.send_log(message)

    def on_vnc_connection_failed(self, reason):
        self.send_log_to_orchestrator(f"FATAL: VNC setup failed: {reason}")
        # Optionally, switch to an error page in the UI
        self.status_label.setText(f"Error: {reason}")
        self.stack.setCurrentWidget(self.login_widget)

    def update_status(self, message):
        self.status_label.setText(message)

    def start_vnc_session(self, host, port):
        self.vnc_widget.connect_to_vnc(host, port, "lise")
        self.stack.setCurrentWidget(self.vnc_widget)

if __name__ == "__main__":
    try:
        import des
    except ImportError:
        print("Required 'des' library not found. Please run: pip install des")
        sys.exit(1)
        
    app = QApplication(sys.argv)
    window = AgentWindow()
    window.show()
    sys.exit(app.exec())
