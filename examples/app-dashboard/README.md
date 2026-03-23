# App Dashboard

A sample app demonstrating a web-based dashboard for robot interaction.

## Features

- Web UI accessible from outside the container
- Real-time sensor data display (battery, pose)
- Movement controls via web interface
- REST API for programmatic access
- Automatic reconnection handling

## Running Locally (Development)

### 1. Start the Mock Robot Server

In one terminal:

```bash
cd ~/remake-sdk
source .venv/bin/activate
python -m remake_sdk.socketio.mock_server
```

### 2. Run the App

In another terminal:

```bash
cd ~/remake-sdk/examples/app-dashboard
pip install flask  # if not installed
../../.venv/bin/python app.py
```

### 3. Open the Dashboard

Navigate to http://localhost:8080 in your browser.

## Building as Container

```bash
cd ~/remake-sdk

# Build from repo root (Dockerfile copies SDK)
podman build -f examples/app-dashboard/Dockerfile -t app-dashboard .

# Run with port mapping
podman run --rm -p 8080:8080 --network=host app-dashboard
```

Then open http://localhost:8080

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML UI |
| `/api/status` | GET | Current app and robot status |
| `/api/command` | POST | Send command (`forward`, `backward`, `left`, `right`, `stop`) |
| `/health` | GET | Health check |

### Examples

```bash
# Get status
curl http://localhost:8080/api/status

# Send command
curl -X POST http://localhost:8080/api/command \
  -H "Content-Type: application/json" \
  -d '{"command": "forward"}'

# Health check
curl http://localhost:8080/health
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REMAKE_ROBOT_URL` | Robot runtime URL | `http://localhost:8788` |
| `REMAKE_APP_ID` | App identifier | `com.example.app-dashboard` |
| `REMAKE_APP_VERSION` | App version | `1.0.0` |
| `APP_WEB_PORT` | Web server port | `8080` |

## Dashboard UI

The web dashboard shows:

- **Connection status** - Connected/disconnected indicator with robot ID
- **Battery** - Current level with visual bar, charging status
- **Position** - X, Y coordinates and theta (rotation)
- **Controls** - Buttons for forward, backward, rotate left/right, stop
- **Logs** - Recent app log entries

The dashboard auto-refreshes every second.
