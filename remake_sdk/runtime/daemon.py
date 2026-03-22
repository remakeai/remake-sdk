"""
Runtime Daemon - Main process that manages the robot.

The daemon:
1. Connects to platform (WebSocket) to receive commands
2. Exposes REST API for CLI communication
3. Manages app lifecycle via AppManager
"""

import asyncio
import signal
import logging
import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from .app_manager import AppManager
from .app_registry import AppRegistry
from .api import RuntimeAPI

logger = logging.getLogger(__name__)


@dataclass
class RuntimeConfig:
    """Runtime configuration."""
    api_host: str = "127.0.0.1"
    api_port: int = 8787
    platform_url: Optional[str] = None
    robot_id: Optional[str] = None
    robot_secret: Optional[str] = None
    connect_to_platform: bool = True
    pid_file: Path = Path("/tmp/remake-runtime.pid")


class RuntimeDaemon:
    """
    Main runtime daemon.

    Manages:
    - Platform connection (WebSocket)
    - REST API server
    - App lifecycle
    """

    def __init__(self, config: Optional[RuntimeConfig] = None):
        self.config = config or RuntimeConfig()

        # Core components
        self.registry = AppRegistry()
        self.app_manager = AppManager(self.registry)
        self.api = RuntimeAPI(
            self.app_manager,
            self.registry,
            host=self.config.api_host,
            port=self.config.api_port
        )

        # Platform client (lazy loaded)
        self._platform_client = None

        # State
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Start the runtime daemon."""
        logger.info("Starting runtime daemon...")

        # Write PID file
        self._write_pid_file()

        # Start REST API
        self.api.start()
        logger.info(f"REST API: {self.api.url}")

        # Connect to platform if configured
        if self.config.connect_to_platform and self.config.robot_id:
            await self._connect_to_platform()

        self._running = True
        logger.info("Runtime daemon started")

        # Wait for shutdown
        await self._shutdown_event.wait()

    async def stop(self):
        """Stop the runtime daemon gracefully."""
        logger.info("Stopping runtime daemon...")

        self._running = False

        # Disconnect from platform
        if self._platform_client:
            await self._platform_client.disconnect()

        # Stop API server
        self.api.stop()

        # Remove PID file
        self._remove_pid_file()

        # Signal shutdown complete
        self._shutdown_event.set()

        logger.info("Runtime daemon stopped")

    def request_shutdown(self):
        """Request daemon shutdown (can be called from signal handler)."""
        asyncio.get_event_loop().call_soon_threadsafe(self._shutdown_event.set)

    async def _connect_to_platform(self):
        """Connect to platform and set up command handlers."""
        try:
            from ..platform import PlatformClient, PlatformConfig
            from ..platform.config import get_robot_credentials, get_platform_url
            from ..common.types import AppCommand

            # Get credentials
            robot_id = self.config.robot_id
            robot_secret = self.config.robot_secret

            if not robot_id or not robot_secret:
                robot_id, robot_secret = get_robot_credentials()

            if not robot_id or not robot_secret:
                logger.warning("No platform credentials configured, skipping platform connection")
                return

            platform_url = self.config.platform_url or get_platform_url() or "https://api.remake.ai"

            config = PlatformConfig(
                platform_url=platform_url,
                robot_id=robot_id,
                robot_secret=robot_secret,
                reconnect=True
            )

            self._platform_client = PlatformClient(config)

            # Set up command handlers
            @self._platform_client.on_app_command
            def handle_app_command(cmd: AppCommand):
                logger.info(f"Platform command: {cmd.action} {cmd.app_id}")
                asyncio.create_task(self._handle_platform_command(cmd))

            # Connect
            logger.info(f"Connecting to platform: {platform_url}")
            connected = await self._platform_client.connect(timeout=15.0)

            if connected:
                logger.info(f"Connected to platform as {robot_id}")
                # Start background task to keep connection alive
                asyncio.create_task(self._platform_client.run())
            else:
                logger.error("Failed to connect to platform")

        except ImportError:
            logger.warning("Platform SDK not available, skipping platform connection")
        except Exception as e:
            logger.error(f"Failed to connect to platform: {e}")

    async def _handle_platform_command(self, cmd):
        """Handle command from platform."""
        from ..common.types import AppCommand

        try:
            if cmd.action == "install":
                result = self.app_manager.install(
                    app_id=cmd.app_id,
                    version=cmd.app_version or "latest",
                    container_image=cmd.container_image,
                    entitlements=cmd.entitlements,
                    source="platform"
                )
                # Send response
                await self._send_install_response(cmd.cmd_id, result.success, result.error)

            elif cmd.action == "uninstall":
                result = self.app_manager.uninstall(cmd.app_id)
                await self._send_uninstall_response(cmd.cmd_id, result.success, result.error)

            elif cmd.action == "launch":
                success, container_id, message = self.app_manager.launch(
                    app_id=cmd.app_id,
                    container_image=cmd.container_image,
                    entitlements=cmd.entitlements
                )
                await self._send_launch_response(cmd.cmd_id, success, message)

            elif cmd.action == "stop":
                success, message = self.app_manager.stop(cmd.app_id)
                await self._send_stop_response(cmd.cmd_id, success, message)

            else:
                logger.warning(f"Unknown command action: {cmd.action}")

        except Exception as e:
            logger.error(f"Error handling command: {e}")

    async def _send_install_response(self, cmd_id: str, success: bool, error: Optional[str]):
        """Send install response to platform."""
        if self._platform_client and self._platform_client._sio:
            await self._platform_client._sio.emit(
                "manage_device_assets_response",
                {"cmd_id": cmd_id, "success": success, "error_message": error},
                namespace="/robot-control"
            )

    async def _send_uninstall_response(self, cmd_id: str, success: bool, error: Optional[str]):
        """Send uninstall response to platform."""
        if self._platform_client and self._platform_client._sio:
            await self._platform_client._sio.emit(
                "manage_device_assets_response",
                {"cmd_id": cmd_id, "success": success, "error_message": error},
                namespace="/robot-control"
            )

    async def _send_launch_response(self, cmd_id: str, success: bool, error: Optional[str]):
        """Send launch response to platform."""
        if self._platform_client and self._platform_client._sio:
            await self._platform_client._sio.emit(
                "launch_app_response",
                {"cmd_id": cmd_id, "success": success, "error_message": error},
                namespace="/robot-control"
            )

    async def _send_stop_response(self, cmd_id: str, success: bool, error: Optional[str]):
        """Send stop response to platform."""
        if self._platform_client and self._platform_client._sio:
            await self._platform_client._sio.emit(
                "stop_app_response",
                {"cmd_id": cmd_id, "success": success, "error_message": error},
                namespace="/robot-control"
            )

    def _write_pid_file(self):
        """Write PID to file for tracking."""
        try:
            self.config.pid_file.write_text(str(os.getpid()))
        except Exception as e:
            logger.warning(f"Failed to write PID file: {e}")

    def _remove_pid_file(self):
        """Remove PID file."""
        try:
            if self.config.pid_file.exists():
                self.config.pid_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove PID file: {e}")

    @classmethod
    def is_running(cls, pid_file: Path = Path("/tmp/remake-runtime.pid")) -> bool:
        """Check if runtime is already running."""
        if not pid_file.exists():
            return False

        try:
            pid = int(pid_file.read_text().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            # PID file exists but process doesn't
            return False

    @classmethod
    def get_pid(cls, pid_file: Path = Path("/tmp/remake-runtime.pid")) -> Optional[int]:
        """Get PID of running runtime."""
        if not pid_file.exists():
            return None

        try:
            return int(pid_file.read_text().strip())
        except (ValueError, OSError):
            return None


def run_daemon(config: Optional[RuntimeConfig] = None):
    """Run the runtime daemon (blocking)."""
    daemon = RuntimeDaemon(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Set up signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, daemon.request_shutdown)

    try:
        loop.run_until_complete(daemon.start())
    finally:
        loop.close()
