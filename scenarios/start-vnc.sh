#!/bin/bash

# Clean up any old VNC locks that might prevent startup
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# Start the VNC server in the background
vncserver :1 -geometry 1280x720 -depth 24 -localhost no

# Start tailing the VNC log file. This serves two purposes:
# 1. It keeps the container running indefinitely.
# 2. It allows us to see the VNC server's logs for debugging if needed.
tail -f /root/.vnc/*.log
