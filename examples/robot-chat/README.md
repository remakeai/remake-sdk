# Robot Chat App

A sample app demonstrating communication with the robot runtime using the Socket.IO SDK.

## Features

- Connects to robot runtime via Socket.IO
- Sends log events to the runtime
- Subscribes to sensor data (battery, pose)
- Sends movement commands
- Graceful shutdown handling

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
cd ~/remake-sdk/examples/robot-chat
../../.venv/bin/python app.py
```

## What it Does

1. Connects to robot runtime (mock server or real)
2. Subscribes to battery and pose updates
3. Runs a demo sequence:
   - Sends log events
   - Moves forward for 3 seconds
   - Rotates for 2 seconds
   - Stops
4. Enters main loop, sending periodic heartbeats
5. Handles Ctrl+C for graceful shutdown

## Building as Container

```bash
# Build (requires SDK to be available)
podman build -t robot-chat-app .

# Run with mock server
podman run --rm --network=host robot-chat-app
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REMAKE_ROBOT_URL` | Robot runtime URL | `http://localhost:8788` |
| `REMAKE_APP_ID` | App identifier | `com.example.robot-chat` |
| `REMAKE_APP_VERSION` | App version | `1.0.0` |
