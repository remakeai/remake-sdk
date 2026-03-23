#!/usr/bin/env python3
"""
App Dashboard - Sample app with web UI for robot interaction.

This app demonstrates:
1. Connecting to the robot runtime via Socket.IO
2. Running a web server accessible from outside the container
3. Providing REST API and simple HTML UI
4. Real-time sensor data display
5. Sending commands via web interface
"""

import asyncio
import signal
import sys
import os
import json
import logging
from datetime import datetime
from threading import Thread

from flask import Flask, jsonify, request, render_template_string

# Add SDK to path for local development (when running from examples/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from remake_sdk.socketio import RobotClient

# App metadata
APP_ID = os.environ.get("REMAKE_APP_ID", "com.example.app-dashboard")
VERSION = os.environ.get("REMAKE_APP_VERSION", "1.0.0")
WEB_PORT = int(os.environ.get("APP_WEB_PORT", "8080"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Flask app
flask_app = Flask(__name__)

# Global state (shared between Flask and async robot client)
app_state = {
    "connected": False,
    "robot_id": None,
    "capabilities": [],
    "battery": {"level": 100, "charging": False},
    "pose": {"x": 0, "y": 0, "theta": 0},
    "logs": [],
    "started_at": None,
}


# HTML template for the dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>App Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
        }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        h2 { color: #888; font-size: 14px; text-transform: uppercase; margin-bottom: 10px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card {
            background: #16213e;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #0f3460;
        }
        .status { display: flex; align-items: center; gap: 10px; margin-bottom: 15px; }
        .status-dot {
            width: 12px; height: 12px; border-radius: 50%;
            background: #ff4757;
        }
        .status-dot.connected { background: #2ed573; }
        .stat { margin: 10px 0; }
        .stat-label { color: #888; font-size: 12px; }
        .stat-value { font-size: 24px; font-weight: bold; }
        .battery-bar {
            height: 20px; background: #0f3460; border-radius: 4px;
            overflow: hidden; margin-top: 5px;
        }
        .battery-fill {
            height: 100%; background: #2ed573;
            transition: width 0.3s;
        }
        .battery-fill.low { background: #ff4757; }
        .battery-fill.charging { background: #ffa502; }
        button {
            background: #0f3460; color: #fff; border: none;
            padding: 10px 20px; border-radius: 4px; cursor: pointer;
            margin: 5px; font-size: 14px;
        }
        button:hover { background: #1a4a7a; }
        button:active { background: #00d4ff; }
        .controls { display: flex; flex-wrap: wrap; gap: 5px; }
        .log-list {
            max-height: 200px; overflow-y: auto;
            font-family: monospace; font-size: 12px;
            background: #0f0f1a; padding: 10px; border-radius: 4px;
        }
        .log-entry { padding: 2px 0; border-bottom: 1px solid #222; }
        .log-entry.warning { color: #ffa502; }
        .log-entry.error { color: #ff4757; }
        .pose-display { font-family: monospace; }
    </style>
</head>
<body>
    <h1>App Dashboard</h1>

    <div class="grid">
        <div class="card">
            <h2>Connection</h2>
            <div class="status">
                <div class="status-dot" id="status-dot"></div>
                <span id="status-text">Disconnected</span>
            </div>
            <div class="stat">
                <div class="stat-label">Robot ID</div>
                <div class="stat-value" id="robot-id">-</div>
            </div>
            <div class="stat">
                <div class="stat-label">Capabilities</div>
                <div id="capabilities">-</div>
            </div>
        </div>

        <div class="card">
            <h2>Battery</h2>
            <div class="stat">
                <div class="stat-value"><span id="battery-level">100</span>%</div>
                <div class="battery-bar">
                    <div class="battery-fill" id="battery-fill" style="width: 100%"></div>
                </div>
            </div>
            <div id="charging-status" style="margin-top: 10px; color: #888;">Not charging</div>
        </div>

        <div class="card">
            <h2>Position</h2>
            <div class="pose-display">
                <div class="stat">
                    <span class="stat-label">X:</span> <span id="pose-x">0.00</span>m
                </div>
                <div class="stat">
                    <span class="stat-label">Y:</span> <span id="pose-y">0.00</span>m
                </div>
                <div class="stat">
                    <span class="stat-label">Theta:</span> <span id="pose-theta">0.00</span>rad
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Controls</h2>
            <div class="controls">
                <button onclick="sendCommand('forward')">Forward</button>
                <button onclick="sendCommand('backward')">Backward</button>
                <button onclick="sendCommand('left')">Rotate Left</button>
                <button onclick="sendCommand('right')">Rotate Right</button>
                <button onclick="sendCommand('stop')" style="background: #ff4757;">Stop</button>
            </div>
        </div>

        <div class="card" style="grid-column: 1 / -1;">
            <h2>App Logs</h2>
            <div class="log-list" id="log-list">
                <div class="log-entry">Waiting for logs...</div>
            </div>
        </div>
    </div>

    <script>
        function updateStatus() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    // Connection status
                    const dot = document.getElementById('status-dot');
                    const text = document.getElementById('status-text');
                    if (data.connected) {
                        dot.classList.add('connected');
                        text.textContent = 'Connected';
                    } else {
                        dot.classList.remove('connected');
                        text.textContent = 'Disconnected';
                    }

                    document.getElementById('robot-id').textContent = data.robot_id || '-';
                    document.getElementById('capabilities').textContent =
                        data.capabilities?.join(', ') || '-';

                    // Battery
                    const level = data.battery?.level || 0;
                    document.getElementById('battery-level').textContent = level;
                    const fill = document.getElementById('battery-fill');
                    fill.style.width = level + '%';
                    fill.className = 'battery-fill';
                    if (data.battery?.charging) fill.classList.add('charging');
                    else if (level < 20) fill.classList.add('low');
                    document.getElementById('charging-status').textContent =
                        data.battery?.charging ? 'Charging' : 'Not charging';

                    // Pose
                    document.getElementById('pose-x').textContent =
                        (data.pose?.x || 0).toFixed(2);
                    document.getElementById('pose-y').textContent =
                        (data.pose?.y || 0).toFixed(2);
                    document.getElementById('pose-theta').textContent =
                        (data.pose?.theta || 0).toFixed(2);

                    // Logs
                    const logList = document.getElementById('log-list');
                    if (data.logs && data.logs.length > 0) {
                        logList.innerHTML = data.logs.map(log =>
                            `<div class="log-entry ${log.level}">[${log.time}] ${log.message}</div>`
                        ).join('');
                        logList.scrollTop = logList.scrollHeight;
                    }
                })
                .catch(err => console.error('Status update failed:', err));
        }

        function sendCommand(cmd) {
            fetch('/api/command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: cmd})
            })
            .then(r => r.json())
            .then(data => console.log('Command result:', data))
            .catch(err => console.error('Command failed:', err));
        }

        // Update every second
        setInterval(updateStatus, 1000);
        updateStatus();
    </script>
</body>
</html>
"""


# Flask routes
@flask_app.route("/")
def index():
    """Serve the dashboard UI."""
    return render_template_string(DASHBOARD_HTML)


@flask_app.route("/api/status")
def api_status():
    """Get current app and robot status."""
    return jsonify(app_state)


@flask_app.route("/api/command", methods=["POST"])
def api_command():
    """Send a command to the robot."""
    data = request.get_json() or {}
    command = data.get("command")

    if not command:
        return jsonify({"error": "No command specified"}), 400

    # Queue command for async execution
    command_queue.append(command)
    add_log(f"Command queued: {command}", "info")

    return jsonify({"status": "queued", "command": command})


@flask_app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "app_id": APP_ID,
        "version": VERSION,
        "connected": app_state["connected"],
    })


# Command queue for async processing
command_queue = []


def add_log(message: str, level: str = "info"):
    """Add a log entry to the state."""
    app_state["logs"].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "level": level,
    })
    # Keep only last 50 logs
    if len(app_state["logs"]) > 50:
        app_state["logs"] = app_state["logs"][-50:]


class AppDashboard:
    """Dashboard app with web server and robot client."""

    def __init__(self):
        self.client = RobotClient(
            app_id=APP_ID,
            app_version=VERSION,
        )
        self.running = True

    async def start(self):
        """Start the app and connect to robot."""
        logger.info(f"App Dashboard v{VERSION}")
        logger.info(f"App ID: {APP_ID}")
        logger.info(f"Web server will run on port {WEB_PORT}")
        logger.info("")

        app_state["started_at"] = datetime.now().isoformat()
        add_log("App starting...", "info")

        # Connect to robot
        logger.info("Connecting to robot runtime...")
        add_log("Connecting to robot...", "info")

        connected = await self.client.connect(timeout=10.0)

        if not connected:
            logger.error("Failed to connect to robot!")
            add_log("Failed to connect to robot", "error")
            # Continue anyway - web server will still work
            return True

        app_state["connected"] = True
        app_state["robot_id"] = self.client.robot_id
        app_state["capabilities"] = self.client.granted_capabilities

        logger.info(f"Connected to robot: {self.client.robot_id}")
        add_log(f"Connected to robot: {self.client.robot_id}", "info")

        # Register event handlers
        self._setup_handlers()

        # Subscribe to sensor data
        await self.client.subscribe(sensor="battery")
        await self.client.subscribe(sensor="pose")

        await self.client.log("App Dashboard started", level="info")
        add_log("Subscribed to sensor data", "info")

        return True

    def _setup_handlers(self):
        """Set up event handlers."""

        @self.client.on_battery
        def handle_battery(data):
            app_state["battery"] = {
                "level": data.get("level", 0),
                "charging": data.get("charging", False),
            }

        @self.client.on_pose
        def handle_pose(data):
            app_state["pose"] = {
                "x": data.get("x", 0),
                "y": data.get("y", 0),
                "theta": data.get("theta", 0),
            }

    async def process_commands(self):
        """Process queued commands."""
        while command_queue:
            cmd = command_queue.pop(0)
            try:
                if cmd == "forward":
                    await self.client.move(linear_x=0.3)
                    await self.client.log("Moving forward", level="debug")
                elif cmd == "backward":
                    await self.client.move(linear_x=-0.3)
                    await self.client.log("Moving backward", level="debug")
                elif cmd == "left":
                    await self.client.move(angular_z=0.5)
                    await self.client.log("Rotating left", level="debug")
                elif cmd == "right":
                    await self.client.move(angular_z=-0.5)
                    await self.client.log("Rotating right", level="debug")
                elif cmd == "stop":
                    await self.client.stop()
                    await self.client.log("Stopped", level="debug")
                add_log(f"Executed: {cmd}", "info")
            except Exception as e:
                add_log(f"Command failed: {cmd} - {e}", "error")

    async def run(self):
        """Run the main loop."""
        logger.info("App is running. Press Ctrl+C to stop.")
        add_log("Main loop started", "info")

        counter = 0
        while self.running:
            counter += 1

            # Process any queued commands
            await self.process_commands()

            # Periodic heartbeat every 30 seconds
            if counter % 30 == 0 and app_state["connected"]:
                await self.client.log(
                    f"Heartbeat #{counter // 30}",
                    level="debug",
                    data={
                        "battery": app_state["battery"]["level"],
                        "pose": app_state["pose"],
                    }
                )

            await asyncio.sleep(1)

    async def stop(self):
        """Stop the app gracefully."""
        logger.info("Stopping app...")
        add_log("Shutting down...", "info")
        self.running = False

        if app_state["connected"]:
            await self.client.log("App Dashboard shutting down", level="info")
            await self.client.disconnect()

        logger.info("App stopped.")


def run_flask():
    """Run Flask in a separate thread."""
    # Disable Flask's default logging to reduce noise
    import logging as flask_logging
    flask_logging.getLogger("werkzeug").setLevel(flask_logging.WARNING)

    flask_app.run(
        host="0.0.0.0",
        port=WEB_PORT,
        debug=False,
        use_reloader=False,
    )


async def main():
    """Main entry point."""
    app = AppDashboard()

    # Handle signals
    loop = asyncio.get_event_loop()

    def signal_handler():
        asyncio.create_task(app.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Start Flask in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Web server started at http://0.0.0.0:{WEB_PORT}")

    # Start robot client
    if not await app.start():
        logger.warning("Running without robot connection")

    # Run main loop
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
