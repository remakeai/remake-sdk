# Remake SDK Examples

Example apps demonstrating the Remake SDK.

## Examples

### [hello-world](hello-world/)

A minimal container app that demonstrates:
- Basic Dockerfile structure
- Graceful shutdown (SIGTERM handling)
- Integration with `remake app` CLI commands

```bash
cd hello-world
podman build -t hello-world-app .
remake app install com.example.hello-world --image localhost/hello-world-app:latest
remake app launch com.example.hello-world --local
```

### [robot-chat](robot-chat/)

An interactive app demonstrating the Socket.IO SDK:
- Connecting to robot runtime
- Sending log events
- Subscribing to sensor data (battery, pose)
- Sending movement commands
- Message format per ROBOT_APP_API.md and API_SENSOR_DATA.md

```bash
# Terminal 1: Start mock server
python -m remake_sdk.socketio.mock_server

# Terminal 2: Run app
cd robot-chat
../../.venv/bin/python app.py
```

### [app-dashboard](app-dashboard/)

A web-based dashboard app demonstrating:
- Web server accessible from outside the container
- REST API for programmatic control
- Real-time sensor data display in browser
- Movement controls via web UI
- Container port mapping

```bash
# Terminal 1: Start mock server
python -m remake_sdk.socketio.mock_server

# Terminal 2: Run app
cd app-dashboard
pip install flask
../../.venv/bin/python app.py

# Terminal 3: Open browser
open http://localhost:8080
```

## Running Examples

Most examples require the SDK to be installed or available in the Python path:

```bash
# From remake-sdk root
source .venv/bin/activate
pip install -e .

# Then run examples
cd examples/robot-chat
python app.py
```
