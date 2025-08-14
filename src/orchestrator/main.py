# src/orchestrator/main.py

import sys
import os
import yaml
import socketio
import asyncio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QPushButton, QTextEdit,
                             QLabel, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- Backend Server Thread ---
# We run the Socket.IO server in a separate thread so it doesn't freeze the UI.
class ServerThread(QThread):
    # Signals to send data back to the UI thread
    agent_connected = pyqtSignal(str, str)
    agent_disconnected = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # Standard Python Socket.IO server setup
        self.sio = socketio.AsyncServer(async_mode='aiohttp')
        self.app = web.Application()
        self.sio.attach(self.app)
        self.runner = None

        # --- Socket.IO Event Handlers ---
        @self.sio.event
        def connect(sid, environ):
            """Handles a new agent connection."""
            client_ip = environ.get('REMOTE_ADDR', 'Unknown')
            self.agent_connected.emit(sid, client_ip)
            self.log_message.emit(f"Agent connected: {sid} from {client_ip}")

        @self.sio.event
        def disconnect(sid):
            """Handles an agent disconnection."""
            self.agent_disconnected.emit(sid)
            self.log_message.emit(f"Agent disconnected: {sid}")

        @self.sio.on('agent_log')
        def agent_log(sid, data):
            """Receives log messages from an agent."""
            self.log_message.emit(f"[{sid}]: {data}")

    async def start_server(self):
        """Coroutine to start the server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', 5000)
        await site.start()
        self.log_message.emit("Orchestrator server started on port 5000.")
        # Keep the server running indefinitely
        await asyncio.Event().wait()

    def run(self):
        """The main entry point for the thread."""
        asyncio.run(self.start_server())
        
    def send_command_to_all(self, command):
        """Sends a command to all connected agents."""
        asyncio.run(self.sio.emit('execute_command', {'command': command}))
        self.log_message.emit(f"Sent command to all agents: {command}")


# --- Main Application Window ---
class OrchestratorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LISE 2.0 - Orchestrator")
        self.setGeometry(100, 100, 1200, 800)

        # --- UI Layout ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Use a splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left Panel (Controls)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)

        # Right Panel (Logs)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)

        # --- Left Panel Widgets ---
        # Scenario List
        left_layout.addWidget(QLabel("Scenarios:"))
        self.scenario_list = QListWidget()
        left_layout.addWidget(self.scenario_list)

        # Control Buttons
        self.start_button = QPushButton("Start Scenario")
        self.stop_button = QPushButton("Stop Scenario")
        self.stop_button.setEnabled(False)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        left_layout.addLayout(button_layout)

        # Connected Agents List
        left_layout.addWidget(QLabel("Connected Agents:"))
        self.agent_list = QListWidget()
        left_layout.addWidget(self.agent_list)

        # --- Right Panel Widgets ---
        right_layout.addWidget(QLabel("Live Log:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        right_layout.addWidget(self.log_output)

        # Set initial sizes for the splitter panels
        splitter.setSizes([400, 800])

        # --- Load Scenarios ---
        self.load_scenarios()
        
        # --- Start Server ---
        self.server_thread = ServerThread()
        self.server_thread.log_message.connect(self.add_log)
        self.server_thread.agent_connected.connect(self.add_agent)
        self.server_thread.agent_disconnected.connect(self.remove_agent)
        self.server_thread.start()
        
        # --- Connect Button Signals ---
        self.start_button.clicked.connect(self.start_scenario)
        self.stop_button.clicked.connect(self.stop_scenario)
        
        self.agents = {} # Dictionary to store agent SIDs and IPs

    def load_scenarios(self):
        """Finds all .yaml files in the scenarios directory."""
        scenario_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scenarios')
        if not os.path.exists(scenario_dir):
            self.add_log(f"Error: Scenarios directory not found at {scenario_dir}")
            return
        
        for filename in os.listdir(scenario_dir):
            if filename.endswith(('.yaml', '.yml')):
                self.scenario_list.addItem(filename)

    def add_log(self, message):
        """Appends a message to the log window."""
        self.log_output.append(message)

    def add_agent(self, sid, ip):
        """Adds a connected agent to the list."""
        self.agents[sid] = ip
        self.agent_list.addItem(f"{ip} ({sid})")

    def remove_agent(self, sid):
        """Removes a disconnected agent from the list."""
        if sid in self.agents:
            ip = self.agents.pop(sid)
            # Find and remove the item from the list widget
            items = self.agent_list.findItems(f"{ip} ({sid})", Qt.MatchFlag.MatchExactly)
            if items:
                self.agent_list.takeItem(self.agent_list.row(items[0]))
    
    def start_scenario(self):
        """Handles the 'Start Scenario' button click."""
        selected_item = self.scenario_list.currentItem()
        if not selected_item:
            self.add_log("Error: No scenario selected.")
            return
        
        scenario_name = selected_item.text()
        self.add_log(f"Starting scenario: {scenario_name}...")
        
        # For Phase 1, we'll just send a simple command as an example.
        # In later phases, this will read the YAML and use Docker.
        self.server_thread.send_command_to_all("echo 'Scenario has started!'")
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.scenario_list.setEnabled(False)

    def stop_scenario(self):
        """Handles the 'Stop Scenario' button click."""
        self.add_log("Stopping scenario...")
        self.server_thread.send_command_to_all("echo 'Scenario has ended.'")
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.scenario_list.setEnabled(True)


if __name__ == "__main__":
    # Standard PyQt6 app setup
    app = QApplication(sys.argv)
    # We need to import the aiohttp web module for the server
    from aiohttp import web
    window = OrchestratorWindow()
    window.show()
    sys.exit(app.exec())
