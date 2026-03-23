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
