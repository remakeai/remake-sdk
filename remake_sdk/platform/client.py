"""
Platform Client - Robot-to-platform communication via Socket.IO.

Handles:
- Challenge-response authentication (HMAC-SHA256)
- Receiving app commands from platform
- Status reporting
- Heartbeat/ping

Based on v1 kaiaai-cli/websocket_client.py, adapted for v2 architecture.
"""

import time
import hmac
import hashlib
import asyncio
import logging
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass

import socketio

from .config import PlatformConfig, get_robot_credentials, get_platform_url
from ..common.types import ConnectionState, AppCommand

logger = logging.getLogger(__name__)


class PlatformError(Exception):
    """Base exception for platform errors."""
    pass


class AuthenticationError(PlatformError):
    """Authentication failed."""
    pass


class ConnectionError(PlatformError):
    """Connection failed."""
    pass


@dataclass
class PingResult:
    """Result of a ping operation."""
    rtt_ms: float
    t1: float  # Client send time
    t2: float  # Server receive time
    t3: float  # Server send time
    t4: float  # Client receive time


class PlatformClient:
    """
    Socket.IO client for robot-to-platform communication.

    Implements the v2 Robot Management API:
    - Challenge-response authentication
    - App command handling (install, launch, stop)
    - Status reporting
    - Heartbeat

    Example:
        config = PlatformConfig.from_file()
        client = PlatformClient(config)

        @client.on_app_command
        def handle_command(cmd: AppCommand):
            if cmd.action == "launch":
                launch_container(cmd.app_id, cmd.container_image)

        await client.connect()
        await client.run()
    """

    NAMESPACE = "/robot-control"

    def __init__(self, config: Optional[PlatformConfig] = None):
        """
        Initialize the platform client.

        Args:
            config: Platform configuration. If None, loads from file.
        """
        if config is None:
            config = PlatformConfig.from_file()

        self.config = config
        self._platform_url = config.platform_url.rstrip('/')
        self._robot_id = config.robot_id
        self._robot_secret = config.robot_secret

        if not self._robot_id or not self._robot_secret:
            raise ValueError("Robot credentials not configured. Run 'remake pair' first.")

        # Socket.IO client
        self._sio = socketio.AsyncClient(
            reconnection=config.reconnect,
            reconnection_attempts=0,  # Infinite
            reconnection_delay=config.reconnect_delay,
            reconnection_delay_max=config.reconnect_max_delay,
            logger=False,
            engineio_logger=False,
        )

        # State
        self._state = ConnectionState.DISCONNECTED
        self._authenticated = False
        self._running = False
        self._last_rtt_ms: Optional[float] = None

        # Event for auth completion
        self._auth_complete = asyncio.Event()
        self._auth_success = False
        self._auth_error: Optional[str] = None

        # Handlers
        self._app_command_handlers: List[Callable[[AppCommand], None]] = []
        self._state_handlers: List[Callable[[ConnectionState], None]] = []
        self._error_handlers: List[Callable[[str], None]] = []

        # Register Socket.IO event handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self._sio.on("connect", namespace=self.NAMESPACE)
        async def on_connect():
            logger.info(f"Connected to {self._platform_url}")
            self._set_state(ConnectionState.CONNECTED)

            # Start authentication
            self._set_state(ConnectionState.AUTHENTICATING)
            logger.debug("Sending authenticate_cmd...")
            await self._sio.emit(
                "authenticate_cmd",
                {"robot_id": self._robot_id},
                namespace=self.NAMESPACE,
            )

        @self._sio.on("disconnect", namespace=self.NAMESPACE)
        async def on_disconnect():
            logger.info("Disconnected from platform")
            self._authenticated = False
            self._set_state(ConnectionState.DISCONNECTED)

        @self._sio.on("authenticate_challenge", namespace=self.NAMESPACE)
        async def on_auth_challenge(data):
            """Handle authentication challenge - compute HMAC signature."""
            if data.get("success") is False:
                self._auth_success = False
                self._auth_error = data.get("message", "Authentication failed")
                logger.error(f"Auth challenge failed: {self._auth_error}")
                self._auth_complete.set()
                return

            nonce = data.get("nonce")
            if not nonce:
                self._auth_success = False
                self._auth_error = "No nonce in challenge"
                self._auth_complete.set()
                return

            logger.debug("Computing signature...")

            # HMAC-SHA256(nonce, robot_secret)
            signature = hmac.new(
                self._robot_secret.encode(),
                nonce.encode(),
                hashlib.sha256,
            ).hexdigest()

            await self._sio.emit(
                "authenticate_response",
                {"signature": signature},
                namespace=self.NAMESPACE,
            )

        @self._sio.on("authenticate_result", namespace=self.NAMESPACE)
        async def on_auth_result(data):
            """Handle authentication result."""
            if data.get("success"):
                self._authenticated = True
                self._auth_success = True
                self._set_state(ConnectionState.AUTHENTICATED)
                logger.info(f"Authenticated as {self._robot_id}")

                # Start heartbeat
                asyncio.create_task(self._heartbeat_loop())
            else:
                self._auth_success = False
                self._auth_error = data.get("message", "Authentication failed")
                self._set_state(ConnectionState.ERROR)
                logger.error(f"Authentication failed: {self._auth_error}")

            self._auth_complete.set()

        @self._sio.on("ping_response", namespace=self.NAMESPACE)
        async def on_ping_response(data):
            """Handle ping response for RTT calculation."""
            t4 = time.time()
            t1 = data.get("t1", t4)
            t2 = data.get("t2", t4)
            t3 = data.get("t3", t4)

            # RTT = (t4 - t1) - (t3 - t2)
            self._last_rtt_ms = ((t4 - t1) - (t3 - t2)) * 1000
            logger.debug(f"RTT: {self._last_rtt_ms:.1f}ms")

        # App command handlers (v1 generic format)
        @self._sio.on("app_command", namespace=self.NAMESPACE)
        async def on_app_command(data):
            """Handle app command from platform (v1 format)."""
            if not self._authenticated:
                return

            cmd = AppCommand(
                action=data.get("action"),
                app_id=data.get("app_id"),
                app_version=data.get("app_version"),
                container_image=data.get("container_image"),
                entitlements=data.get("entitlements", []),
                purchase_token=data.get("purchase_token"),
                cmd_id=data.get("cmd_id"),
            )

            logger.info(f"App command: {cmd.action} {cmd.app_id}")
            self._dispatch_app_command(cmd)

        # v2 App Lifecycle Commands
        @self._sio.on("launch_app_cmd", namespace=self.NAMESPACE)
        async def on_launch_app_cmd(data):
            """Handle v2 launch app command."""
            if not self._authenticated:
                return

            cmd = AppCommand(
                action="launch",
                app_id=data.get("app_id"),
                app_version=data.get("app_version"),
                container_image=data.get("container_image"),
                entitlements=data.get("entitlements", []),
                purchase_token=data.get("purchase_token"),
                cmd_id=data.get("cmd_id"),
            )

            logger.info(f"v2 launch_app_cmd: {cmd.app_id}")
            self._dispatch_app_command(cmd)

        @self._sio.on("stop_app_cmd", namespace=self.NAMESPACE)
        async def on_stop_app_cmd(data):
            """Handle v2 stop app command."""
            if not self._authenticated:
                return

            cmd = AppCommand(
                action="stop",
                app_id=data.get("app_id"),
                cmd_id=data.get("cmd_id"),
            )

            logger.info(f"v2 stop_app_cmd: {cmd.app_id}")
            self._dispatch_app_command(cmd)

        @self._sio.on("manage_device_assets_cmd", namespace=self.NAMESPACE)
        async def on_manage_assets_cmd(data):
            """Handle v2 device assets command (install/uninstall)."""
            if not self._authenticated:
                return

            cmd = AppCommand(
                action=data.get("action"),  # 'install', 'uninstall', 'update'
                app_id=data.get("asset_id"),
                app_version=data.get("version"),
                container_image=data.get("download_url"),
                cmd_id=data.get("cmd_id"),
            )

            logger.info(f"v2 manage_device_assets_cmd: {cmd.action} {cmd.app_id}")
            self._dispatch_app_command(cmd)

        @self._sio.on("unpaired", namespace=self.NAMESPACE)
        async def on_unpaired(data):
            """Handle unpaired notification."""
            logger.warning("Robot has been unpaired from platform")
            self._running = False
            await self._sio.disconnect()

        @self._sio.on("connect_error", namespace=self.NAMESPACE)
        async def on_connect_error(data):
            logger.error(f"Connection error: {data}")
            self._set_state(ConnectionState.ERROR)

    def _set_state(self, state: ConnectionState):
        """Update connection state and notify handlers."""
        self._state = state
        for handler in self._state_handlers:
            try:
                handler(state)
            except Exception as e:
                logger.error(f"Error in state handler: {e}")

    def _dispatch_app_command(self, cmd: AppCommand):
        """Dispatch app command to registered handlers."""
        for handler in self._app_command_handlers:
            try:
                handler(cmd)
            except Exception as e:
                logger.error(f"Error in app command handler: {e}")

    async def connect(self, timeout: float = 15.0) -> bool:
        """
        Connect to platform and authenticate.

        Args:
            timeout: Authentication timeout in seconds.

        Returns:
            True if connected and authenticated successfully.

        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If authentication fails.
        """
        self._set_state(ConnectionState.CONNECTING)
        self._auth_complete.clear()

        try:
            await self._sio.connect(
                self._platform_url,
                namespaces=[self.NAMESPACE],
                transports=["websocket"],
            )
        except Exception as e:
            self._set_state(ConnectionState.ERROR)
            raise ConnectionError(f"Failed to connect: {e}")

        # Wait for authentication
        try:
            await asyncio.wait_for(self._auth_complete.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self._sio.disconnect()
            raise AuthenticationError("Authentication timeout")

        if not self._auth_success:
            await self._sio.disconnect()
            raise AuthenticationError(self._auth_error or "Authentication failed")

        return True

    async def disconnect(self):
        """Disconnect from platform."""
        self._running = False
        if self._sio.connected:
            await self._sio.disconnect()
        self._set_state(ConnectionState.DISCONNECTED)

    async def run(self):
        """
        Run the client event loop.

        This blocks until disconnect() is called or connection is lost.
        """
        self._running = True
        try:
            await self._sio.wait()
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    async def _heartbeat_loop(self):
        """Send periodic heartbeat pings."""
        while self._running and self._authenticated:
            await asyncio.sleep(self.config.heartbeat_interval)
            if self._running and self._authenticated:
                t1 = time.time()
                await self._sio.emit(
                    "ping_cmd",
                    {"t1": t1},
                    namespace=self.NAMESPACE,
                )

    async def report_status(
        self,
        status: str,
        running_app_id: Optional[str] = None,
        battery_level: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        """
        Report robot status to platform.

        Args:
            status: Robot status ("idle", "running", "error").
            running_app_id: ID of currently running app, if any.
            battery_level: Battery percentage (0-100).
            error_message: Error message if status is "error".
        """
        if not self._authenticated:
            raise PlatformError("Not authenticated")

        await self._sio.emit(
            "robot_status_update",
            {
                "status": status,
                "running_app_id": running_app_id,
                "battery_level": battery_level,
                "error_message": error_message,
            },
            namespace=self.NAMESPACE,
        )

    async def report_app_exited(
        self,
        app_id: str,
        exit_code: int,
        error_message: Optional[str] = None,
    ):
        """
        Report that an app has exited.

        Args:
            app_id: ID of the app that exited.
            exit_code: Exit code (0 = success).
            error_message: Error message if exit_code != 0.
        """
        if not self._authenticated:
            raise PlatformError("Not authenticated")

        await self._sio.emit(
            "app_exited_event",
            {
                "app_id": app_id,
                "exit_code": exit_code,
                "error_message": error_message,
            },
            namespace=self.NAMESPACE,
        )

    def on_app_command(self, handler: Callable[[AppCommand], None]):
        """
        Register handler for app commands.

        Args:
            handler: Function to call when app command is received.

        Example:
            @client.on_app_command
            def handle_command(cmd: AppCommand):
                if cmd.action == "launch":
                    launch_app(cmd)
        """
        self._app_command_handlers.append(handler)
        return handler

    def on_state_change(self, handler: Callable[[ConnectionState], None]):
        """Register handler for connection state changes."""
        self._state_handlers.append(handler)
        return handler

    def on_error(self, handler: Callable[[str], None]):
        """Register handler for errors."""
        self._error_handlers.append(handler)
        return handler

    @property
    def is_connected(self) -> bool:
        """Check if connected to platform."""
        return self._sio.connected

    @property
    def is_authenticated(self) -> bool:
        """Check if authenticated with platform."""
        return self._authenticated

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def rtt_ms(self) -> Optional[float]:
        """Get last measured RTT in milliseconds."""
        return self._last_rtt_ms


# Convenience function for simple usage
async def connect_to_platform(
    platform_url: Optional[str] = None,
    robot_id: Optional[str] = None,
    robot_secret: Optional[str] = None,
) -> PlatformClient:
    """
    Convenience function to connect to platform.

    Uses config file values if arguments not provided.

    Args:
        platform_url: Platform API URL.
        robot_id: Robot ID.
        robot_secret: Robot secret.

    Returns:
        Connected and authenticated PlatformClient.
    """
    if robot_id is None or robot_secret is None:
        saved_id, saved_secret = get_robot_credentials()
        robot_id = robot_id or saved_id
        robot_secret = robot_secret or saved_secret

    config = PlatformConfig(
        platform_url=platform_url or get_platform_url(),
        robot_id=robot_id,
        robot_secret=robot_secret,
    )

    client = PlatformClient(config)
    await client.connect()
    return client
