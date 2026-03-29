# Remake SDK

Python SDK for Remake.ai robot platform.

## Installation

```bash
# Install full SDK
pip install remake-sdk[all]

# Or install specific subpackages
pip install remake-sdk[platform]   # Robot-to-platform communication
pip install remake-sdk[socketio]   # Robot-to-app communication
pip install remake-sdk[podman]     # Container management (Podman)
pip install remake-sdk[mqtt]       # MQTT messaging

# Install Host Agent (on the host machine, not in the robot container)
pip install remake-sdk[agent]
```

## Quick Start

### Platform Connection

```python
import asyncio
from remake_sdk.platform import PlatformClient, PlatformConfig

async def main():
    # Load config from ~/.config/remake/
    config = PlatformConfig.from_file()
    client = PlatformClient(config)

    @client.on_app_command
    def handle_command(cmd):
        print(f"Received: {cmd.action} for {cmd.app_id}")
        if cmd.action == "launch":
            # Launch the app container
            pass

    await client.connect()
    await client.run()

asyncio.run(main())
```

### Configuration

Config is stored in `~/.config/remake/`:

```yaml
# config.yml
platform:
  url: https://api.remake.ai
  reconnect: true
  heartbeat_interval: 30.0

runtime:
  mode: dev            # prod, dev, mock
  backend: auto        # agent, podman, or auto
  agent_url: http://host.docker.internal:8785  # Host Agent URL (optional)
```

```yaml
# credentials.yml (chmod 600)
robot_id: robot-abc123
robot_secret: your-secret
```

### Container Backend

The SDK supports two container backends for managing app lifecycle:

- **podman** - Local Podman subprocess calls (requires Podman installed)
- **agent** - HTTP calls to the Host Agent running on the host machine
- **auto** (default) - Tries Host Agent first, falls back to Podman

Set via config file (`runtime.backend`) or CLI flag (`--backend`).

## Host Agent

The Host Agent runs on the host machine and manages app containers
alongside (not inside) the robot container. This eliminates the need
for `--privileged` mode.

```bash
# On the host machine
pip install remake-sdk[agent]
python -m remake_agent

# Options
python -m remake_agent --port 8785 --runtime docker
python -m remake_agent --config ~/.remake/agent.yml
```

See `architecture/v2/HOST_AGENT_ARCHITECTURE.md` for details.

## CLI

```bash
# Robot pairing
remake pair
remake unpair
remake status

# App management
remake app install <app-id> --image <image>
remake app launch <app-id> --local [--backend agent|podman|auto]
remake app stop <app-id> --local
remake app list --local
remake app logs <app-id>

# Runtime daemon
remake runtime start [--backend agent|podman|auto] [--agent-url URL]
remake runtime stop
remake runtime status
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=remake_sdk
```

## Subpackages

| Package | Purpose |
|---------|---------|
| `remake_sdk.platform` | Robot ↔ Platform communication |
| `remake_sdk.socketio` | Robot ↔ App communication (Socket.IO) |
| `remake_sdk.runtime` | App lifecycle, container backends |
| `remake_sdk.common` | Shared types and utilities |
| `remake_agent` | Host Agent server (host-side) |
