"""
Dashboard Server - Web UI for robot control and monitoring.
"""

import json
import logging
import subprocess
from flask import Flask, jsonify, request, render_template_string

logger = logging.getLogger(__name__)

# Runtime API URL
RUNTIME_API_URL = "http://127.0.0.1:8787"


def is_runtime_running() -> bool:
    """Check if runtime is running."""
    import requests
    try:
        resp = requests.get(f"{RUNTIME_API_URL}/health", timeout=1)
        return resp.status_code == 200
    except:
        return False


def get_running_apps():
    """Get list of running app containers."""
    try:
        result = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}|{{.ID}}|{{.Status}}|{{.Image}}|{{.Labels}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return []

        apps = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                container_name = parts[0]
                labels = parts[4] if len(parts) > 4 else ""

                # Extract APP_ID from label if present
                app_id = container_name
                if "remake.app_id=" in labels:
                    for label in labels.split(","):
                        if label.startswith("remake.app_id="):
                            app_id = label.split("=", 1)[1]
                            break

                apps.append({
                    "app_id": app_id,
                    "container_name": container_name,
                    "container_id": parts[1][:12],
                    "status": parts[2],
                    "image": parts[3],
                })
        return apps
    except Exception as e:
        logger.error(f"Error getting running apps: {e}")
        return []


def get_installed_apps():
    """Get list of installed apps from registry."""
    try:
        from ..runtime.app_registry import AppRegistry
        registry = AppRegistry()
        installed = registry.list_all()
        return [app.to_dict() for app in installed]
    except Exception as e:
        logger.error(f"Error getting installed apps: {e}")
        return []


# Dashboard HTML template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Remake Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f1a;
            color: #eee;
            min-height: 100vh;
        }
        .header {
            background: #1a1a2e;
            padding: 15px 20px;
            border-bottom: 1px solid #0f3460;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            color: #00d4ff;
            font-size: 24px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header h1::before {
            content: "";
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #2ed573;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .status-bar {
            display: flex;
            gap: 20px;
            font-size: 14px;
            color: #888;
        }
        .status-item { display: flex; align-items: center; gap: 5px; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; }
        .status-dot.green { background: #2ed573; }
        .status-dot.yellow { background: #ffa502; }
        .status-dot.red { background: #ff4757; }

        .main { display: flex; height: calc(100vh - 60px); }

        .sidebar {
            width: 250px;
            background: #16213e;
            border-right: 1px solid #0f3460;
            padding: 20px;
            overflow-y: auto;
        }
        .sidebar h2 {
            font-size: 12px;
            text-transform: uppercase;
            color: #888;
            margin-bottom: 10px;
        }
        .nav-item {
            display: block;
            padding: 10px 15px;
            color: #ccc;
            text-decoration: none;
            border-radius: 6px;
            margin-bottom: 5px;
            cursor: pointer;
        }
        .nav-item:hover { background: #1a4a7a; color: #fff; }
        .nav-item.active { background: #0f3460; color: #00d4ff; }

        .content {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
        }
        .content h2 {
            margin-bottom: 20px;
            color: #00d4ff;
        }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card {
            background: #16213e;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #0f3460;
        }
        .card h3 {
            font-size: 14px;
            text-transform: uppercase;
            color: #888;
            margin-bottom: 15px;
        }

        .app-list { list-style: none; }
        .app-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px;
            background: #0f0f1a;
            border-radius: 6px;
            margin-bottom: 10px;
        }
        .app-info h4 { color: #fff; margin-bottom: 5px; }
        .app-info p { font-size: 12px; color: #888; }
        .app-status {
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            text-transform: uppercase;
        }
        .app-status.running { background: #2ed573; color: #000; }
        .app-status.stopped { background: #555; color: #fff; }

        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            margin-left: 10px;
        }
        .btn-primary { background: #00d4ff; color: #000; }
        .btn-primary:hover { background: #00b8e6; }
        .btn-danger { background: #ff4757; color: #fff; }
        .btn-danger:hover { background: #ff3344; }
        .btn-secondary { background: #0f3460; color: #fff; }
        .btn-secondary:hover { background: #1a4a7a; }

        .log-viewer {
            background: #0a0a12;
            border-radius: 6px;
            padding: 15px;
            font-family: monospace;
            font-size: 12px;
            max-height: 400px;
            overflow-y: auto;
        }
        .log-line { padding: 2px 0; border-bottom: 1px solid #1a1a2e; }
        .log-line.info { color: #2ed573; }
        .log-line.warn { color: #ffa502; }
        .log-line.error { color: #ff4757; }

        .stat-value { font-size: 32px; font-weight: bold; color: #00d4ff; }
        .stat-label { color: #888; font-size: 14px; }

        .control-pad {
            display: grid;
            grid-template-columns: repeat(3, 60px);
            gap: 5px;
            justify-content: center;
        }
        .control-btn {
            width: 60px;
            height: 60px;
            border: none;
            border-radius: 8px;
            background: #0f3460;
            color: #fff;
            font-size: 24px;
            cursor: pointer;
        }
        .control-btn:hover { background: #1a4a7a; }
        .control-btn:active { background: #00d4ff; color: #000; }
        .control-btn.stop { background: #ff4757; }
        .control-btn.stop:hover { background: #ff3344; }

        .refresh-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background: #00d4ff;
            color: #000;
            border: none;
            font-size: 20px;
            cursor: pointer;
            box-shadow: 0 4px 15px rgba(0, 212, 255, 0.3);
        }
        .refresh-btn:hover { transform: scale(1.1); }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #888;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Remake Dashboard</h1>
        <div class="status-bar">
            <div class="status-item">
                <span class="status-dot" id="runtime-status"></span>
                <span id="runtime-text">Checking...</span>
            </div>
            <div class="status-item">
                <span id="app-count">0 apps running</span>
            </div>
        </div>
    </div>

    <div class="main">
        <div class="sidebar">
            <h2>Navigation</h2>
            <a class="nav-item active" onclick="showSection('overview')">Overview</a>
            <a class="nav-item" onclick="showSection('apps')">Apps</a>
            <a class="nav-item" onclick="showSection('control')">Control</a>
            <a class="nav-item" onclick="showSection('logs')">Logs</a>
        </div>

        <div class="content">
            <!-- Overview Section -->
            <div id="section-overview" class="section">
                <h2>Overview</h2>
                <div class="grid">
                    <div class="card">
                        <h3>Running Apps</h3>
                        <div class="stat-value" id="stat-running">0</div>
                        <div class="stat-label">containers active</div>
                    </div>
                    <div class="card">
                        <h3>Installed Apps</h3>
                        <div class="stat-value" id="stat-installed">0</div>
                        <div class="stat-label">apps in registry</div>
                    </div>
                    <div class="card">
                        <h3>Runtime</h3>
                        <div class="stat-value" id="stat-runtime">--</div>
                        <div class="stat-label" id="stat-runtime-label">checking...</div>
                    </div>
                </div>

                <div style="margin-top: 30px;">
                    <h3 style="color: #888; margin-bottom: 15px;">Running Apps</h3>
                    <ul class="app-list" id="running-apps-list">
                        <li class="empty-state">Loading...</li>
                    </ul>
                </div>
            </div>

            <!-- Apps Section -->
            <div id="section-apps" class="section" style="display: none;">
                <h2>Installed Apps</h2>
                <ul class="app-list" id="installed-apps-list">
                    <li class="empty-state">Loading...</li>
                </ul>
            </div>

            <!-- Control Section -->
            <div id="section-control" class="section" style="display: none;">
                <h2>Manual Control</h2>
                <div class="grid">
                    <div class="card">
                        <h3>Movement</h3>
                        <p style="color: #888; margin-bottom: 15px; font-size: 14px;">
                            Send movement commands to the robot
                        </p>
                        <div class="control-pad">
                            <div></div>
                            <button class="control-btn" onclick="sendMove('forward')">&#8593;</button>
                            <div></div>
                            <button class="control-btn" onclick="sendMove('left')">&#8592;</button>
                            <button class="control-btn stop" onclick="sendMove('stop')">&#9632;</button>
                            <button class="control-btn" onclick="sendMove('right')">&#8594;</button>
                            <div></div>
                            <button class="control-btn" onclick="sendMove('backward')">&#8595;</button>
                            <div></div>
                        </div>
                        <p id="control-status" style="text-align: center; margin-top: 15px; color: #888; font-size: 12px;"></p>
                    </div>
                    <div class="card">
                        <h3>Quick Actions</h3>
                        <button class="btn btn-secondary" onclick="refreshAll()" style="width: 100%; margin: 5px 0;">
                            Refresh Status
                        </button>
                        <button class="btn btn-danger" onclick="stopAllApps()" style="width: 100%; margin: 5px 0;">
                            Stop All Apps
                        </button>
                    </div>
                </div>
            </div>

            <!-- Logs Section -->
            <div id="section-logs" class="section" style="display: none;">
                <h2>Logs</h2>
                <div style="margin-bottom: 15px;">
                    <select id="log-app-select" onchange="loadLogs()" style="padding: 8px; background: #0f3460; color: #fff; border: none; border-radius: 4px;">
                        <option value="">Select an app...</option>
                    </select>
                    <button class="btn btn-secondary" onclick="loadLogs()">Refresh</button>
                </div>
                <div class="log-viewer" id="log-viewer">
                    <div class="empty-state">Select an app to view logs</div>
                </div>
            </div>
        </div>
    </div>

    <button class="refresh-btn" onclick="refreshAll()" title="Refresh">&#8635;</button>

    <script>
        let currentSection = 'overview';

        function showSection(name) {
            document.querySelectorAll('.section').forEach(s => s.style.display = 'none');
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.getElementById('section-' + name).style.display = 'block';
            document.querySelector('.nav-item[onclick*="' + name + '"]').classList.add('active');
            currentSection = name;

            if (name === 'logs') {
                updateLogAppSelect();
            }
        }

        function refreshAll() {
            fetchStatus();
            fetchRunningApps();
            fetchInstalledApps();
        }

        function fetchStatus() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    const dot = document.getElementById('runtime-status');
                    const text = document.getElementById('runtime-text');
                    const stat = document.getElementById('stat-runtime');
                    const label = document.getElementById('stat-runtime-label');

                    if (data.runtime_running) {
                        dot.className = 'status-dot green';
                        text.textContent = 'Runtime active';
                        stat.textContent = 'ON';
                        label.textContent = 'runtime active';
                    } else {
                        dot.className = 'status-dot yellow';
                        text.textContent = 'Runtime offline';
                        stat.textContent = 'OFF';
                        label.textContent = 'using direct mode';
                    }
                })
                .catch(() => {
                    document.getElementById('runtime-status').className = 'status-dot red';
                    document.getElementById('runtime-text').textContent = 'Error';
                });
        }

        function fetchRunningApps() {
            fetch('/api/apps/running')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('running-apps-list');
                    const count = document.getElementById('app-count');
                    const stat = document.getElementById('stat-running');

                    stat.textContent = data.apps.length;
                    count.textContent = data.apps.length + ' apps running';

                    if (data.apps.length === 0) {
                        list.innerHTML = '<li class="empty-state">No apps running</li>';
                        return;
                    }

                    list.innerHTML = data.apps.map(app => `
                        <li class="app-item">
                            <div class="app-info">
                                <h4>${app.app_id}</h4>
                                <p>${app.image} | ${app.status}</p>
                            </div>
                            <div>
                                <span class="app-status running">Running</span>
                                <button class="btn btn-secondary" onclick="openAppUI('${app.app_id}')">UI</button>
                                <button class="btn btn-danger" onclick="stopApp('${app.container_name}')">Stop</button>
                            </div>
                        </li>
                    `).join('');
                })
                .catch(err => console.error('Error fetching running apps:', err));
        }

        function fetchInstalledApps() {
            fetch('/api/apps/installed')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('installed-apps-list');
                    const stat = document.getElementById('stat-installed');

                    stat.textContent = data.apps.length;

                    if (data.apps.length === 0) {
                        list.innerHTML = '<li class="empty-state">No apps installed</li>';
                        return;
                    }

                    list.innerHTML = data.apps.map(app => `
                        <li class="app-item">
                            <div class="app-info">
                                <h4>${app.app_id}</h4>
                                <p>v${app.version} | ${app.container_image}</p>
                            </div>
                            <div>
                                <button class="btn btn-primary" onclick="launchApp('${app.app_id}')">Launch</button>
                            </div>
                        </li>
                    `).join('');
                })
                .catch(err => console.error('Error fetching installed apps:', err));
        }

        function updateLogAppSelect() {
            fetch('/api/apps/running')
                .then(r => r.json())
                .then(data => {
                    const select = document.getElementById('log-app-select');
                    select.innerHTML = '<option value="">Select an app...</option>' +
                        data.apps.map(app => `<option value="${app.container_name}">${app.app_id}</option>`).join('');
                });
        }

        function loadLogs() {
            const appId = document.getElementById('log-app-select').value;
            if (!appId) return;

            fetch('/api/apps/' + encodeURIComponent(appId) + '/logs')
                .then(r => r.json())
                .then(data => {
                    const viewer = document.getElementById('log-viewer');
                    if (!data.logs || data.logs.length === 0) {
                        viewer.innerHTML = '<div class="empty-state">No logs available</div>';
                        return;
                    }
                    viewer.innerHTML = data.logs.map(line => {
                        let cls = 'log-line';
                        if (line.includes('ERROR') || line.includes('error')) cls += ' error';
                        else if (line.includes('WARN') || line.includes('warning')) cls += ' warn';
                        else if (line.includes('INFO')) cls += ' info';
                        return `<div class="${cls}">${escapeHtml(line)}</div>`;
                    }).join('');
                    viewer.scrollTop = viewer.scrollHeight;
                })
                .catch(err => {
                    document.getElementById('log-viewer').innerHTML =
                        '<div class="empty-state">Error loading logs</div>';
                });
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function launchApp(appId) {
            fetch('/api/apps/' + encodeURIComponent(appId) + '/launch', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        setTimeout(refreshAll, 1000);
                    } else {
                        alert('Failed to launch: ' + (data.message || 'Unknown error'));
                    }
                })
                .catch(err => alert('Error: ' + err));
        }

        function stopApp(appId) {
            fetch('/api/apps/' + encodeURIComponent(appId) + '/stop', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    setTimeout(refreshAll, 1000);
                })
                .catch(err => alert('Error: ' + err));
        }

        function stopAllApps() {
            if (!confirm('Stop all running apps?')) return;
            fetch('/api/apps/stop-all', { method: 'POST' })
                .then(() => setTimeout(refreshAll, 1000))
                .catch(err => alert('Error: ' + err));
        }

        function openAppUI(appId) {
            fetch('/api/apps/' + encodeURIComponent(appId) + '/ui-url')
                .then(r => r.json())
                .then(data => {
                    if (data.url) {
                        window.open(data.url, '_blank');
                    } else {
                        alert('No UI URL available for this app');
                    }
                });
        }

        function sendMove(direction) {
            const status = document.getElementById('control-status');
            status.textContent = 'Sending ' + direction + '...';

            fetch('/api/control/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({direction: direction})
            })
            .then(r => r.json())
            .then(data => {
                status.textContent = data.message || 'Command sent';
                setTimeout(() => status.textContent = '', 2000);
            })
            .catch(err => {
                status.textContent = 'Error: ' + err;
            });
        }

        // Initial load
        refreshAll();

        // Auto-refresh every 5 seconds
        setInterval(refreshAll, 5000);
    </script>
</body>
</html>
"""


class DashboardServer:
    """Web dashboard server for robot control."""

    def __init__(self, port: int = 8080):
        self.port = port
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        """Set up Flask routes."""

        @self.app.route("/")
        def index():
            return render_template_string(DASHBOARD_HTML)

        @self.app.route("/api/status")
        def api_status():
            return jsonify({
                "runtime_running": is_runtime_running(),
                "dashboard_version": "1.0.0",
            })

        @self.app.route("/api/apps/running")
        def api_running_apps():
            return jsonify({"apps": get_running_apps()})

        @self.app.route("/api/apps/installed")
        def api_installed_apps():
            return jsonify({"apps": get_installed_apps()})

        @self.app.route("/api/apps/<app_id>/logs")
        def api_app_logs(app_id):
            try:
                result = subprocess.run(
                    ["podman", "logs", "--tail", "100", app_id],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                logs = result.stdout.strip().split("\n") if result.stdout else []
                logs += result.stderr.strip().split("\n") if result.stderr else []
                return jsonify({"logs": [l for l in logs if l]})
            except Exception as e:
                return jsonify({"logs": [], "error": str(e)})

        @self.app.route("/api/apps/<app_id>/launch", methods=["POST"])
        def api_launch_app(app_id):
            try:
                from ..runtime.app_manager import AppManager
                manager = AppManager()
                success, container_id, message = manager.launch(app_id)
                return jsonify({
                    "success": success,
                    "container_id": container_id,
                    "message": message
                })
            except Exception as e:
                return jsonify({"success": False, "message": str(e)})

        @self.app.route("/api/apps/<app_id>/stop", methods=["POST"])
        def api_stop_app(app_id):
            try:
                result = subprocess.run(
                    ["podman", "stop", app_id],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                return jsonify({
                    "success": result.returncode == 0,
                    "message": "Stopped" if result.returncode == 0 else result.stderr
                })
            except Exception as e:
                return jsonify({"success": False, "message": str(e)})

        @self.app.route("/api/apps/stop-all", methods=["POST"])
        def api_stop_all():
            apps = get_running_apps()
            for app in apps:
                try:
                    subprocess.run(
                        ["podman", "stop", app["container_name"]],
                        capture_output=True,
                        timeout=30
                    )
                except:
                    pass
            return jsonify({"success": True, "stopped": len(apps)})

        @self.app.route("/api/apps/<app_id>/ui-url")
        def api_app_ui_url(app_id):
            # Try to get port from registry
            try:
                from ..runtime.app_registry import AppRegistry
                registry = AppRegistry()

                # Find app by ID or container name
                for installed in registry.list_all():
                    if installed.app_id == app_id or app_id in installed.app_id:
                        if installed.ports:
                            port = installed.ports[0]
                            host_port = port.host if hasattr(port, 'host') else port.get('host')
                            return jsonify({"url": f"http://localhost:{host_port}"})
            except:
                pass

            return jsonify({"url": None})

        @self.app.route("/api/control/move", methods=["POST"])
        def api_control_move():
            data = request.get_json() or {}
            direction = data.get("direction", "stop")

            # Try to send via Socket.IO to any running app
            # For now, just return success - actual movement requires robot connection
            commands = {
                "forward": {"linear_x": 0.3, "angular_z": 0},
                "backward": {"linear_x": -0.3, "angular_z": 0},
                "left": {"linear_x": 0, "angular_z": 0.5},
                "right": {"linear_x": 0, "angular_z": -0.5},
                "stop": {"linear_x": 0, "angular_z": 0},
            }

            cmd = commands.get(direction, commands["stop"])
            return jsonify({
                "success": True,
                "message": f"Command: {direction}",
                "command": cmd
            })

        @self.app.route("/health")
        def health():
            return jsonify({"status": "healthy"})

    def run(self, debug: bool = False):
        """Run the dashboard server."""
        # Suppress Flask logs in non-debug mode
        if not debug:
            import logging as flask_logging
            flask_logging.getLogger("werkzeug").setLevel(flask_logging.WARNING)

        self.app.run(host="0.0.0.0", port=self.port, debug=debug)


def run_dashboard(port: int = 8080, debug: bool = False):
    """Run the dashboard server."""
    server = DashboardServer(port=port)
    server.run(debug=debug)


if __name__ == "__main__":
    run_dashboard()
