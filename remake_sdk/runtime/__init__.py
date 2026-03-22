"""
Remake Runtime - Core daemon for robot management.

The runtime:
- Connects to platform (WebSocket) to receive commands
- Exposes REST API for CLI communication
- Manages app lifecycle (install, launch, stop)
- Tracks installed apps in local registry
"""

from .daemon import RuntimeDaemon
from .app_manager import AppManager
from .app_registry import AppRegistry

__all__ = ["RuntimeDaemon", "AppManager", "AppRegistry"]
