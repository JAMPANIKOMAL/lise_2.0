# src/agent/main.py

import sys
import socketio
import docker # New import
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, 
                             QLineEdit, QPushButton)
from PyQt6.QtCore import QThread, pyqtSignal

# --- SocketIO Client Thread ---
# Handles all communication with the server in the background.
class ClientThread(QThread):
    connection_status = pyqtSignal(str)
    
    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url
        self.sio = socketio.Client()
        
        # --- New: Initialize Docker Client ---
        try:
            self.docker_client = docker.from_env()
        except docker.errors.DockerException as e:
            self.connection_status.emit(f"Docker Error: {e}")
            self.docker_client = None

        # --- Socket.IO Event Handlers ---
        @self.sio.event
        def connect():
            self.connection_status.emit(f"Connected to {self.server_url}")

        @self.sio.event
        def disconnect():
            self.connection_status.emit("Disconnected")

        @self.sio.on('execute_command')
        def execute_command(data):
            """Receives a command from the orchestrator."""
            if not self.docker_client:
                self.sio.emit('agent_log', "ERROR: Docker is not available on this agent.")
                return

            command = data.get('command')
            container_id = data.get('container_id')
            if not command or not container_id:
                return

            self.sio.emit('agent_log', f"Received command for container {container_id[:12]}: {command}")
            
            try:
                # --- MODIFIED: Execute command inside the specified container ---
                # Get the container object using its ID
                container = self.docker_client.containers.get(container_id)
                
                # Execute the command inside the container
                exit_code, output = container.exec_run(command)
                
                # Decode the output from bytes to a string
                output_str = output.decode('utf-8').strip()
                
                # Send the result back to the orchestrator
                if output_str:
                    self.sio.emit('agent_log', f"OUTPUT:\n{output_str}")
                else:
                    self.sio.emit('agent_log', "Command executed with no output.")

            except docker.errors.NotFound:
                self.sio.emit('agent_log', f"ERROR: Container {container_id[:12]} not found on this agent.")
            except Exception as e:
                self.sio.emit('agent_log', f"Failed to execute command in container: {e}")

    def run(self):
        """The main entry point for the thread."""
        if not self.docker_client:
            return # Stop the thread if Docker isn't running
        try:
            self.sio.connect(self.server_url)
            self.sio.wait()
        except socketio.exceptions.ConnectionError as e:
            self.connection_status.emit(f"Failed to connect: {e}")

# --- Main Agent Window ---
class AgentWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LISE 2.0 - Agent")
        self.setGeometry(100, 100, 400, 150)
        
        self.client_thread = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Enter Orchestrator IP and connect.")
        self.ip_input = QLineEdit("http://127.0.0.1:5000")
        self.connect_button = QPushButton("Connect")
        
        layout.addWidget(self.status_label)
        layout.addWidget(self.ip_input)
        layout.addWidget(self.connect_button)
        
        self.connect_button.clicked.connect(self.connect_to_server)

    def connect_to_server(self):
        server_url = self.ip_input.text()
        self.status_label.setText(f"Connecting to {server_url}...")
        
        self.client_thread = ClientThread(server_url)
        self.client_thread.connection_status.connect(self.update_status)
        self.client_thread.start()
        
        self.connect_button.setEnabled(False)
        self.ip_input.setEnabled(False)

    def update_status(self, message):
        self.status_label.setText(message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AgentWindow()
    window.show()
    sys.exit(app.exec())
