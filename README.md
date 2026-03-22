# Remake SDK

Python SDK for Remake.ai robot platform.

## Installation

```bash
# Install full SDK
pip install remake-sdk[all]

# Or install specific subpackages
pip install remake-sdk[platform]   # Robot-to-platform communication
pip install remake-sdk[socketio]   # Robot-to-app communication
pip install remake-sdk[podman]     # Container management
pip install remake-sdk[mqtt]       # MQTT messaging
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
  mode: dev  # prod, dev, mock
  socket_path: /var/run/remake/robot.sock
```

```yaml
# credentials.yml (chmod 600)
robot_id: robot-abc123
robot_secret: your-secret
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
| `remake_sdk.socketio` | Robot ↔ App communication (Socket.IO server) |
| `remake_sdk.podman` | App container lifecycle management |
| `remake_sdk.common` | Shared types and utilities |

## License

MIT
