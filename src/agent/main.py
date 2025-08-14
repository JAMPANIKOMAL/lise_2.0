# src/agent/main.py

import sys
import socketio
import subprocess
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
            command = data.get('command')
            if not command:
                return

            # Log that we received the command
            self.sio.emit('agent_log', f"Received command: {command}")
            
            try:
                # Execute the command on the host machine
                # We use shell=True for simplicity, but it has security implications.
                # For this controlled educational tool, it's acceptable.
                result = subprocess.run(
                    command, 
                    shell=True, 
                    capture_output=True, 
                    text=True, 
                    check=False
                )
                
                # Send stdout back to the orchestrator
                if result.stdout:
                    self.sio.emit('agent_log', f"OUTPUT:\n{result.stdout}")
                # Send stderr back if there was an error
                if result.stderr:
                    self.sio.emit('agent_log', f"ERROR:\n{result.stderr}")

            except Exception as e:
                self.sio.emit('agent_log', f"Failed to execute command: {e}")

    def run(self):
        """The main entry point for the thread."""
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

        # --- UI Layout ---
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Enter Orchestrator IP and connect.")
        self.ip_input = QLineEdit("http://127.0.0.1:5000")
        self.connect_button = QPushButton("Connect")
        
        layout.addWidget(self.status_label)
        layout.addWidget(self.ip_input)
        layout.addWidget(self.connect_button)
        
        # --- Connect Button Signal ---
        self.connect_button.clicked.connect(self.connect_to_server)

    def connect_to_server(self):
        """Handles the 'Connect' button click."""
        server_url = self.ip_input.text()
        self.status_label.setText(f"Connecting to {server_url}...")
        
        # Start the client thread to handle the connection
        self.client_thread = ClientThread(server_url)
        self.client_thread.connection_status.connect(self.update_status)
        self.client_thread.start()
        
        self.connect_button.setEnabled(False)
        self.ip_input.setEnabled(False)

    def update_status(self, message):
        """Updates the status label with messages from the client thread."""
        self.status_label.setText(message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AgentWindow()
    window.show()
    sys.exit(app.exec())
