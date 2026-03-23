"""
Robot Client - App-side SDK for communicating with robot runtime.

Apps use this client to:
- Connect to the robot runtime via Unix socket
- Send commands (move, stop, navigate, etc.)
- Receive sensor data and events
- Log events back to the runtime
"""

import os
import asyncio
import logging
import time
from typing import Optional, Callable, List, Dict, Any, Set
from dataclasses import dataclass, field

import socketio

logger = logging.getLogger(__name__)


@dataclass
class RobotInfo:
    """Information about the connected robot."""
    robot_id: str
    firmware_version: str
    capabilities: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WelcomeData:
    """Data received in welcome message."""
    robot_id: str
    firmware_version: str
    granted_capabilities: List[str]
    capabilities: Dict[str, Any]
    limits: Dict[str, Any]
    state: Dict[str, Any]


class RobotClient:
    """
    Client for apps to communicate with the robot runtime.

    Example:
        client = RobotClient()
        await client.connect()

        # Send a log event
        await client.log("App started", level="info")

        # Move the robot
        await client.move(linear_x=0.5)

        # Subscribe to battery updates
        @client.on_battery
        def handle_battery(data):
            print(f"Battery: {data['level']}%")

        await client.run()
    """

    def __init__(
        self,
        socket_url: Optional[str] = None,
        app_id: Optional[str] = None,
        app_version: Optional[str] = None,
    ):
        """
        Initialize the robot client.

        Args:
            socket_url: URL of robot runtime. Defaults to env var or localhost.
            app_id: App identifier. Defaults to REMAKE_APP_ID env var.
            app_version: App version. Defaults to REMAKE_APP_VERSION env var.
        """
        self.socket_url = socket_url or os.environ.get(
            "REMAKE_ROBOT_URL", "http://localhost:8788"
        )
        self.app_id = app_id or os.environ.get("REMAKE_APP_ID", "unknown-app")
        self.app_version = app_version or os.environ.get("REMAKE_APP_VERSION", "0.0.0")

        # Socket.IO client
        self._sio = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,
        )

        # State
        self._connected = False
        self._welcomed = False
        self._robot_info: Optional[RobotInfo] = None
        self._granted_capabilities: List[str] = []
        self._robot_state: Dict[str, Any] = {}

        # Event for welcome completion
        self._welcome_event = asyncio.Event()

        # Handlers
        self._battery_handlers: List[Callable] = []
        self._pose_handlers: List[Callable] = []
        self._scan_handlers: List[Callable] = []
        self._event_handlers: Dict[str, List[Callable]] = {}

        # Register Socket.IO handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self._sio.on("connect")
        async def on_connect():
            logger.info(f"Connected to robot runtime at {self.socket_url}")
            self._connected = True

            # Send hello (per ROBOT_APP_API.md)
            await self._sio.emit("hello", {
                "app_id": self.app_id,
                "app_version": self.app_version,
                "api_version": "2.0.0",
            })

        @self._sio.on("disconnect")
        async def on_disconnect():
            logger.info("Disconnected from robot runtime")
            self._connected = False
            self._welcomed = False

        @self._sio.on("welcome")
        async def on_welcome(data):
            logger.info(f"Welcome received from robot {data.get('robot_id')}")
            self._welcomed = True
            self._robot_info = RobotInfo(
                robot_id=data.get("robot_id", "unknown"),
                firmware_version=data.get("firmware_version", "unknown"),
                capabilities=data.get("capabilities", {}),
                limits=data.get("limits", {}),
            )
            self._granted_capabilities = data.get("granted_capabilities", [])
            self._robot_state = data.get("state", {})
            self._welcome_event.set()

        @self._sio.on("battery_data")
        async def on_battery(data):
            for handler in self._battery_handlers:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Error in battery handler: {e}")

        @self._sio.on("pose_data")
        async def on_pose(data):
            for handler in self._pose_handlers:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Error in pose handler: {e}")

        @self._sio.on("scan_data")
        async def on_scan(data):
            for handler in self._scan_handlers:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Error in scan handler: {e}")

        @self._sio.on("error")
        async def on_error(data):
            logger.error(f"Robot error: {data}")

    async def connect(self, timeout: float = 10.0) -> bool:
        """
        Connect to the robot runtime.

        Args:
            timeout: Connection timeout in seconds.

        Returns:
            True if connected and welcomed.
        """
        self._welcome_event.clear()

        try:
            await self._sio.connect(self.socket_url)
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

        # Wait for welcome
        try:
            await asyncio.wait_for(self._welcome_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for welcome")
            await self._sio.disconnect()
            return False

    async def disconnect(self):
        """Disconnect from the robot runtime."""
        if self._connected:
            # Send goodbye
            await self._sio.emit("goodbye", {
                "reason": "app_exit",
            })
            await self._sio.disconnect()

    async def run(self):
        """Run the client event loop."""
        await self._sio.wait()

    # --- Commands ---

    async def move(
        self,
        linear_x: float = 0.0,
        angular_z: float = 0.0,
        duration_ms: int = 0,
        cmd_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a move command (per ROBOT_APP_API.md).

        Args:
            linear_x: Forward velocity (m/s).
            angular_z: Angular velocity (rad/s).
            duration_ms: How long to maintain velocity (0 = until next command).
            cmd_id: Optional command ID for tracking.

        Returns:
            Acknowledgment from robot.
        """
        cmd_id = cmd_id or f"move-{int(time.time() * 1000)}"

        await self._sio.emit("move_cmd", {
            "cmd_id": cmd_id,
            "linear_x": linear_x,
            "angular_z": angular_z,
            "duration_ms": duration_ms,
        })

        return {"cmd_id": cmd_id, "sent": True}

    async def stop(self, cmd_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a stop command."""
        cmd_id = cmd_id or f"stop-{int(time.time() * 1000)}"

        await self._sio.emit("stop_cmd", {
            "cmd_id": cmd_id,
        })

        return {"cmd_id": cmd_id, "sent": True}

    async def log(
        self,
        message: str,
        level: str = "info",
        data: Optional[Dict[str, Any]] = None,
    ):
        """
        Send a log event to the robot runtime.

        Args:
            message: Log message.
            level: Log level (debug, info, warning, error).
            data: Optional additional data.
        """
        await self._sio.emit("app_log", {
            "timestamp": int(time.time() * 1000),
            "level": level,
            "message": message,
            "data": data or {},
        })

    async def subscribe(
        self,
        data_types: Optional[List[str]] = None,
        sensor: Optional[str] = None,
        rate_hz: float = 1.0,
        cmd_id: Optional[str] = None,
    ):
        """
        Subscribe to sensor data (per API_SENSOR_DATA.md subscribe_to_data_cmd).

        Args:
            data_types: List of data types to subscribe to (e.g., ["battery_data", "pose_data"]).
            sensor: Single sensor shorthand (e.g., "battery" -> "battery_data").
            rate_hz: Desired update rate (hint to server).
            cmd_id: Optional command ID.
        """
        cmd_id = cmd_id or f"sub-{int(time.time() * 1000)}"

        # Build subscribe list
        subscribe_list = []
        if data_types:
            subscribe_list = data_types
        elif sensor:
            # Convert shorthand to full name
            subscribe_list = [f"{sensor}_data" if not sensor.endswith("_data") else sensor]

        await self._sio.emit("subscribe_to_data_cmd", {
            "cmd_id": cmd_id,
            "subscribe": subscribe_list,
            # Simplified - full spec supports batch and notify configs
        })

    async def unsubscribe(self, sensor: str, cmd_id: Optional[str] = None):
        """Unsubscribe from sensor data."""
        cmd_id = cmd_id or f"unsub-{int(time.time() * 1000)}"
        data_type = f"{sensor}_data" if not sensor.endswith("_data") else sensor

        await self._sio.emit("unsubscribe_data_cmd", {
            "cmd_id": cmd_id,
            "unsubscribe": [data_type],
        })

    # --- Event Handlers ---

    def on_battery(self, handler: Callable):
        """Register handler for battery data."""
        self._battery_handlers.append(handler)
        return handler

    def on_pose(self, handler: Callable):
        """Register handler for pose data."""
        self._pose_handlers.append(handler)
        return handler

    def on_scan(self, handler: Callable):
        """Register handler for lidar scan data."""
        self._scan_handlers.append(handler)
        return handler

    # --- Properties ---

    @property
    def is_connected(self) -> bool:
        """Check if connected to robot."""
        return self._connected and self._welcomed

    @property
    def robot_id(self) -> Optional[str]:
        """Get connected robot ID."""
        return self._robot_info.robot_id if self._robot_info else None

    @property
    def granted_capabilities(self) -> List[str]:
        """Get granted capabilities."""
        return self._granted_capabilities

    @property
    def robot_state(self) -> Dict[str, Any]:
        """Get initial robot state."""
        return self._robot_state
