# src/orchestrator/main.py

import sys
import os
import yaml
import socketio
import asyncio
import docker # New import
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QPushButton, QTextEdit,
                             QLabel, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- Backend Docker Manager Thread ---
# Manages all Docker operations in a background thread to avoid freezing the UI.
class DockerManager(QThread):
    log_message = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        try:
            self.docker_client = docker.from_env()
            self.active_containers = []
        except docker.errors.DockerException as e:
            self.log_message.emit(f"Docker Error: {e}")
            self.log_message.emit("Please ensure Docker Desktop is running.")
            self.docker_client = None

    def start_scenario_containers(self, scenario_file):
        if not self.docker_client:
            self.log_message.emit("Docker is not available. Cannot start scenario.")
            return

        scenario_dir = os.path.dirname(scenario_file)
        
        try:
            with open(scenario_file, 'r') as f:
                scenario_data = yaml.safe_load(f)
            
            self.log_message.emit(f"Successfully parsed {os.path.basename(scenario_file)}")
            
            # Look for team definitions in the YAML
            teams = scenario_data.get('teams', {})
            for team_name, team_info in teams.items():
                dockerfile = team_info.get('dockerfile')
                if not dockerfile:
                    continue

                # --- FIX: Correctly construct the path to the Dockerfile's DIRECTORY ---
                # The 'path' argument for build() needs to be the directory containing the Dockerfile.
                dockerfile_full_path = os.path.join(scenario_dir, dockerfile)
                docker_context_path = os.path.dirname(dockerfile_full_path)
                dockerfile_name = os.path.basename(dockerfile_full_path)

                image_tag = f"lise_{team_name}_image"
                
                self.log_message.emit(f"Building image '{image_tag}' for team '{team_name}' from path '{docker_context_path}'...")
                
                # Build the Docker image from the specified Dockerfile
                self.docker_client.images.build(path=docker_context_path, dockerfile=dockerfile_name, tag=image_tag, rm=True)
                
                self.log_message.emit(f"Image '{image_tag}' built. Starting container...")
                
                # Run the container
                container = self.docker_client.containers.run(image_tag, detach=True)
                self.active_containers.append(container)
                self.log_message.emit(f"Container {container.short_id} for team '{team_name}' started.")

        except Exception as e:
            self.log_message.emit(f"Error processing scenario file: {e}")

    def stop_all_containers(self):
        if not self.docker_client or not self.active_containers:
            return
            
        self.log_message.emit("Stopping and removing active scenario containers...")
        for container in self.active_containers:
            try:
                container.stop()
                container.remove()
                self.log_message.emit(f"Stopped and removed container {container.short_id}")
            except docker.errors.APIError as e:
                self.log_message.emit(f"Could not stop container {container.short_id}: {e}")
        self.active_containers = []
        self.log_message.emit("All scenario containers stopped.")


# --- Backend Server Thread ---
class ServerThread(QThread):
    agent_connected = pyqtSignal(str, str)
    agent_disconnected = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.sio = socketio.AsyncServer(async_mode='aiohttp')
        self.app = web.Application()
        self.sio.attach(self.app)
        self.runner = None

        @self.sio.event
        def connect(sid, environ):
            client_ip = environ.get('REMOTE_ADDR', 'Unknown')
            self.agent_connected.emit(sid, client_ip)
            self.log_message.emit(f"Agent connected: {sid} from {client_ip}")

        @self.sio.event
        def disconnect(sid):
            self.agent_disconnected.emit(sid)
            self.log_message.emit(f"Agent disconnected: {sid}")

        @self.sio.on('agent_log')
        def agent_log(sid, data):
            self.log_message.emit(f"[{sid}]: {data}")

    async def start_server(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', 5000)
        await site.start()
        self.log_message.emit("Orchestrator server started on port 5000.")
        await asyncio.Event().wait()

    def run(self):
        asyncio.run(self.start_server())
        
    def send_command_to_all(self, command):
        asyncio.run(self.sio.emit('execute_command', {'command': command}))
        self.log_message.emit(f"Sent command to all agents: {command}")


# --- Main Application Window ---
class OrchestratorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LISE 2.0 - Orchestrator")
        self.setGeometry(100, 100, 1200, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)

        left_layout.addWidget(QLabel("Scenarios:"))
        self.scenario_list = QListWidget()
        left_layout.addWidget(self.scenario_list)

        self.start_button = QPushButton("Start Scenario")
        self.stop_button = QPushButton("Stop Scenario")
        self.stop_button.setEnabled(False)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        left_layout.addLayout(button_layout)

        left_layout.addWidget(QLabel("Connected Agents:"))
        self.agent_list = QListWidget()
        left_layout.addWidget(self.agent_list)

        right_layout.addWidget(QLabel("Live Log:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        right_layout.addWidget(self.log_output)

        splitter.setSizes([400, 800])

        self.scenario_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scenarios')
        self.load_scenarios()
        
        # --- Start Server and Docker Manager ---
        self.server_thread = ServerThread()
        self.server_thread.log_message.connect(self.add_log)
        self.server_thread.agent_connected.connect(self.add_agent)
        self.server_thread.agent_disconnected.connect(self.remove_agent)
        self.server_thread.start()
        
        self.docker_manager = DockerManager()
        self.docker_manager.log_message.connect(self.add_log)
        
        self.start_button.clicked.connect(self.start_scenario)
        self.stop_button.clicked.connect(self.stop_scenario)
        
        self.agents = {}

    def load_scenarios(self):
        if not os.path.exists(self.scenario_dir):
            self.add_log(f"Error: Scenarios directory not found at {self.scenario_dir}")
            return
        
        for filename in os.listdir(self.scenario_dir):
            if filename.endswith(('.yaml', '.yml')):
                self.scenario_list.addItem(filename)

    def add_log(self, message):
        self.log_output.append(message)

    def add_agent(self, sid, ip):
        self.agents[sid] = ip
        self.agent_list.addItem(f"{ip} ({sid})")

    def remove_agent(self, sid):
        if sid in self.agents:
            ip = self.agents.pop(sid)
            items = self.agent_list.findItems(f"{ip} ({sid})", Qt.MatchFlag.MatchExactly)
            if items:
                self.agent_list.takeItem(self.agent_list.row(items[0]))
    
    def start_scenario(self):
        selected_item = self.scenario_list.currentItem()
        if not selected_item:
            self.add_log("Error: No scenario selected.")
            return
        
        scenario_filename = selected_item.text()
        scenario_filepath = os.path.join(self.scenario_dir, scenario_filename)
        self.add_log(f"Starting scenario: {scenario_filename}...")
        
        # Use the DockerManager to start containers
        self.docker_manager.start_scenario_containers(scenario_filepath)
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.scenario_list.setEnabled(False)

    def stop_scenario(self):
        self.add_log("Stopping scenario...")
        
        # Use the DockerManager to stop all containers
        self.docker_manager.stop_all_containers()
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.scenario_list.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    from aiohttp import web
    window = OrchestratorWindow()
    window.show()
    sys.exit(app.exec())
