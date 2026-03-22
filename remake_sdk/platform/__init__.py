"""
Platform SDK - Robot-to-platform communication.

This module handles communication between the robot and the Remake.ai platform:
- Pairing (new robots without credentials)
- Authentication (challenge-response)
- Receiving app commands (install, launch, stop)
- Status reporting

Example - Pairing a new robot:
    from remake_sdk.platform import PairingClient

    async with PairingClient("https://api.remake.ai") as client:
        result = await client.request_pairing("user@example.com", "My Robot")
        if result.success:
            save_credentials(result.robot_id, result.robot_secret)

Example - Authenticated robot:
    from remake_sdk.platform import PlatformClient, PlatformConfig

    config = PlatformConfig(
        platform_url="https://api.remake.ai",
        robot_id="robot-abc123",
        robot_secret="secret-xyz"
    )
    client = PlatformClient(config)

    @client.on_app_command
    def handle_command(cmd):
        print(f"Received: {cmd.action} for {cmd.app_id}")

    await client.connect()
    await client.run()
"""

from .config import (
    PlatformConfig,
    load_config,
    save_config,
    get_platform_url,
    get_robot_credentials,
    set_robot_credentials,
    clear_credentials,
)
from ..common.types import (
    ConnectionState,
    AppCommand,
    PairingResult,
    PairingStatus,
    PairingCredentials,
    RobotStatus,
)

# Lazy imports for clients (require python-socketio)
def __getattr__(name):
    if name == "PlatformClient":
        from .client import PlatformClient
        return PlatformClient
    if name == "PairingClient":
        from .pairing import PairingClient
        return PairingClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Clients
    "PlatformClient",
    "PairingClient",
    # Config
    "PlatformConfig",
    "load_config",
    "save_config",
    "get_platform_url",
    "get_robot_credentials",
    "set_robot_credentials",
    "clear_credentials",
    # Types
    "ConnectionState",
    "AppCommand",
    "PairingResult",
    "PairingStatus",
    "PairingCredentials",
    "RobotStatus",
]
