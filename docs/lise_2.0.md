LISE 2.0: Project Development Plan
This document outlines the initial phased development plan for LISE 2.0, a native desktop software suite for immersive cybersecurity training. The goal is to evolve the original web-based prototype into a powerful, standalone platform for educators and students.
Phase 1: The Foundation (Completed)
Goal: To migrate the project from a web-based interface to a robust, native desktop application framework. This phase focuses on building the core software structure and communication channels.
Key Milestones:
Native Applications: Create two distinct, installable desktop applications: LISE Orchestrator for educators and LISE Agent for students.
Technology Stack:
Language: Python
UI Framework: PyQt6 for a professional, cross-platform user interface.
Real-time Communication: Establish a stable, two-way communication link between the Orchestrator and Agent applications using Socket.IO.
Basic Functionality:
The Orchestrator can successfully launch and display its main window.
The Agent can successfully launch and connect to the Orchestrator.
The Orchestrator can see connected Agents in its UI.
Phase 2: The Environment (Completed)
Goal: To integrate Docker as the core virtualization engine, enabling the Orchestrator to automatically create and manage the simulation environments.
Key Milestones:
Scenario Parsing: The Orchestrator can read and understand scenario definitions from .yaml files.
Docker Integration:
The Orchestrator can build Docker images from Dockerfile specifications found in the scenario files.
The Orchestrator can start and stop Docker containers for each team defined in a scenario.
Team Management: The Orchestrator UI allows the educator to assign connected Agents to specific teams (e.g., "Red Team", "Blue Team").
Phase 3: The Immersive Experience (In Progress)
Goal: To create a fully immersive and interactive experience for the student by embedding the virtual machine's desktop directly inside the LISE Agent application.
Key Milestones:
Graphical VM: Create a Docker image (e.g., Dockerfile.kali) that includes a graphical desktop environment (XFCE) and a VNC server that starts automatically.
Embedded VNC Client: Replace the Agent's simple status window with a fully functional, real-time VNC client that can:
Display the desktop of the student's assigned Docker container.
Capture and transmit mouse and keyboard inputs from the student to the container, allowing for seamless interaction.
Seamless Workflow: The entire process—from the Orchestrator starting the container to the student seeing and controlling the desktop—is automated and smooth.
