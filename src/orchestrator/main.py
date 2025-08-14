# src/orchestrator/main.py

import sys
import os
import yaml
import socketio
import asyncio
import docker
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QPushButton, QTextEdit,
                             QLabel, QSplitter, QComboBox, QListWidgetItem)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- Backend Docker Manager Thread ---
class DockerManager(QThread):
    log_message = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        try:
            self.docker_client = docker.from_env()
            self.active_containers = {} # Changed to a dictionary {team_name: container}
        except docker.errors.DockerException as e:
            self.log_message.emit(f"Docker Error: {e}")
            self.log_message.emit("Please ensure Docker Desktop is running.")
            self.docker_client = None

    def start_scenario_containers(self, scenario_file):
        if not self.docker_client:
            self.log_message.emit("Docker is not available. Cannot start scenario.")
            return None

        scenario_dir = os.path.dirname(scenario_file)
        
        try:
            with open(scenario_file, 'r') as f:
                scenario_data = yaml.safe_load(f)
            
            self.log_message.emit(f"Successfully parsed {os.path.basename(scenario_file)}")
            
            teams = scenario_data.get('teams', {})
            for team_name, team_info in teams.items():
                dockerfile = team_info.get('dockerfile')
                if not dockerfile:
                    continue

                dockerfile_full_path = os.path.join(scenario_dir, dockerfile)
                docker_context_path = os.path.dirname(dockerfile_full_path)
                dockerfile_name = os.path.basename(dockerfile_full_path)

                image_tag = f"lise_{team_name}_image"
                
                self.log_message.emit(f"Building image '{image_tag}' for team '{team_name}'...")
                self.docker_client.images.build(path=docker_context_path, dockerfile=dockerfile_name, tag=image_tag, rm=True)
                
                self.log_message.emit(f"Image '{image_tag}' built. Starting container...")
                container = self.docker_client.containers.run(image_tag, detach=True)
                self.active_containers[team_name] = container # Store by team name
                self.log_message.emit(f"Container {container.short_id} for team '{team_name}' started.")
            
            return scenario_data # Return parsed data for injects

        except Exception as e:
            self.log_message.emit(f"Error processing scenario file: {e}")
            return None

    def stop_all_containers(self):
        if not self.docker_client or not self.active_containers:
            return
            
        self.log_message.emit("Stopping and removing active scenario containers...")
        for team_name, container in self.active_containers.items():
            try:
                container.stop()
                container.remove()
                self.log_message.emit(f"Stopped and removed container {container.short_id} for team '{team_name}'")
            except docker.errors.APIError as e:
                self.log_message.emit(f"Could not stop container {container.short_id}: {e}")
        self.active_containers = {}
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

        @self.sio.event
        def disconnect(sid):
            self.agent_disconnected.emit(sid)

        @self.sio.on('agent_log')
        def agent_log(sid, data):
            self.log_message.emit(f"[{sid[:8]}]: {data}")

    async def start_server(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', 5000)
        await site.start()
        self.log_message.emit("Orchestrator server started on port 5000.")
        await asyncio.Event().wait()

    def run(self):
        asyncio.run(self.start_server())
        
    def send_command_to_agent(self, sid, command, container_id):
        """Sends a command to a specific agent to run in a specific container."""
        asyncio.run(self.sio.emit('execute_command', {'command': command, 'container_id': container_id}, to=sid))
        self.log_message.emit(f"Sent command to agent {sid[:8]} for container {container_id[:12]}: {command}")

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
        
        # New Team Assignment UI
        left_layout.addWidget(QLabel("Assign Selected Agent to Team:"))
        self.team_combo = QComboBox()
        self.assign_button = QPushButton("Assign")
        assign_layout = QHBoxLayout()
        assign_layout.addWidget(self.team_combo)
        assign_layout.addWidget(self.assign_button)
        left_layout.addLayout(assign_layout)

        right_layout.addWidget(QLabel("Live Log:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        right_layout.addWidget(self.log_output)

        splitter.setSizes([400, 800])

        self.scenario_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scenarios')
        self.load_scenarios()
        
        self.server_thread = ServerThread()
        self.server_thread.log_message.connect(self.add_log)
        self.server_thread.agent_connected.connect(self.add_agent)
        self.server_thread.agent_disconnected.connect(self.remove_agent)
        self.server_thread.start()
        
        self.docker_manager = DockerManager()
        self.docker_manager.log_message.connect(self.add_log)
        
        self.start_button.clicked.connect(self.start_scenario)
        self.stop_button.clicked.connect(self.stop_scenario)
        self.assign_button.clicked.connect(self.assign_agent_to_team)
        self.scenario_list.currentItemChanged.connect(self.update_team_combo)
        
        self.agents = {} # {sid: {"ip": ip, "team": None}}

    def load_scenarios(self):
        if not os.path.exists(self.scenario_dir): return
        for filename in os.listdir(self.scenario_dir):
            if filename.endswith(('.yaml', '.yml')):
                self.scenario_list.addItem(filename)

    def update_team_combo(self, current_item):
        """Populates the team dropdown based on the selected scenario."""
        self.team_combo.clear()
        if not current_item: return
        
        scenario_filepath = os.path.join(self.scenario_dir, current_item.text())
        try:
            with open(scenario_filepath, 'r') as f:
                scenario_data = yaml.safe_load(f)
            teams = scenario_data.get('teams', {}).keys()
            self.team_combo.addItems(teams)
        except Exception as e:
            self.add_log(f"Error reading teams from scenario: {e}")

    def add_log(self, message):
        self.log_output.append(message)

    def add_agent(self, sid, ip):
        self.agents[sid] = {"ip": ip, "team": None}
        item = QListWidgetItem(f"{ip} (Unassigned)")
        item.setData(Qt.ItemDataRole.UserRole, sid) # Store SID in the item
        self.agent_list.addItem(item)
        self.add_log(f"Agent connected: {sid[:8]} from {ip}")

    def remove_agent(self, sid):
        if sid in self.agents:
            self.agents.pop(sid)
            for i in range(self.agent_list.count()):
                item = self.agent_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == sid:
                    self.agent_list.takeItem(i)
                    break
        self.add_log(f"Agent disconnected: {sid[:8]}")
        
    def assign_agent_to_team(self):
        """Assigns the selected agent to the selected team."""
        selected_agent_item = self.agent_list.currentItem()
        if not selected_agent_item:
            self.add_log("Error: No agent selected.")
            return
        
        sid = selected_agent_item.data(Qt.ItemDataRole.UserRole)
        team_name = self.team_combo.currentText()
        
        if sid in self.agents:
            self.agents[sid]['team'] = team_name
            ip = self.agents[sid]['ip']
            selected_agent_item.setText(f"{ip} (Team: {team_name})")
            self.add_log(f"Assigned agent {sid[:8]} to team '{team_name}'")

    def start_scenario(self):
        selected_item = self.scenario_list.currentItem()
        if not selected_item:
            self.add_log("Error: No scenario selected.")
            return
        
        scenario_filename = selected_item.text()
        scenario_filepath = os.path.join(self.scenario_dir, scenario_filename)
        self.add_log(f"Starting scenario: {scenario_filename}...")
        
        scenario_data = self.docker_manager.start_scenario_containers(scenario_filepath)
        
        if scenario_data:
            self.process_injects(scenario_data)
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.scenario_list.setEnabled(False)

    def process_injects(self, scenario_data):
        """Reads and executes injects from the scenario data."""
        injects = scenario_data.get('injects', [])
        self.add_log(f"Processing {len(injects)} injects...")
        for inject in injects:
            target_team = inject.get('team')
            command = inject.get('command')
            
            # Find an agent assigned to the target team
            target_sid = None
            for sid, agent_info in self.agents.items():
                if agent_info['team'] == target_team:
                    target_sid = sid
                    break
            
            # Get the container for the target team
            container = self.docker_manager.active_containers.get(target_team)
            
            if command and target_sid and container:
                self.server_thread.send_command_to_agent(target_sid, command, container.id)
            else:
                self.add_log(f"Could not execute inject: '{command}'. Check team assignment and container status.")

    def stop_scenario(self):
        self.add_log("Stopping scenario...")
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
