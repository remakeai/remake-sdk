"""
Mock Robot Server - For testing apps without a real robot.

Provides a simple Socket.IO server that simulates robot behavior:
- Accepts app connections
- Responds to commands
- Sends periodic sensor data
"""

import asyncio
import logging
import time
import random
from typing import Dict, Any, Set

import socketio
from aiohttp import web

logger = logging.getLogger(__name__)


class MockRobotServer:
    """
    Mock robot server for testing apps.

    Example:
        server = MockRobotServer(port=8788)
        await server.start()
        # Apps can now connect to http://localhost:8788
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8788,
        robot_id: str = "mock-robot-001",
    ):
        self.host = host
        self.port = port
        self.robot_id = robot_id

        # Socket.IO server
        self._sio = socketio.AsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins="*",
        )
        self._app = web.Application()
        self._sio.attach(self._app)

        # Connected apps
        self._connected_apps: Dict[str, Dict[str, Any]] = {}
        self._subscriptions: Dict[str, Set[str]] = {}  # sensor -> set of sids

        # Simulated state
        self._battery_level = 85
        self._pose = {"x": 0.0, "y": 0.0, "theta": 0.0}
        self._velocity = {"linear_x": 0.0, "angular_z": 0.0}

        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self._sio.on("connect")
        async def on_connect(sid, environ):
            logger.info(f"App connected: {sid}")

        @self._sio.on("disconnect")
        async def on_disconnect(sid):
            logger.info(f"App disconnected: {sid}")
            if sid in self._connected_apps:
                app_id = self._connected_apps[sid].get("app_id")
                logger.info(f"  App ID: {app_id}")
                del self._connected_apps[sid]
            # Remove from subscriptions
            for sensor in self._subscriptions:
                self._subscriptions[sensor].discard(sid)

        @self._sio.on("hello")
        async def on_hello(sid, data):
            app_id = data.get("app_id", "unknown")
            app_version = data.get("app_version", "0.0.0")
            api_version = data.get("api_version", "2.0.0")
            logger.info(f"Hello from {app_id} v{app_version} (API {api_version})")

            self._connected_apps[sid] = {
                "app_id": app_id,
                "app_version": app_version,
                "api_version": api_version,
                "connected_at": time.time(),
            }

            # Send welcome (per ROBOT_APP_API.md)
            await self._sio.emit("welcome", {
                "robot_id": self.robot_id,
                "firmware_version": "mock-2.0.0",
                "api_version": "2.0.0",
                "granted_capabilities": ["movement", "audio_playback"],
                "denied_capabilities": [],
                "capabilities": {
                    "movement": True,
                    "navigation": False,
                    "camera": False,
                    "audio_playback": True,
                },
                "limits": {
                    "max_linear_speed": 0.5,
                    "max_angular_speed": 1.5,
                },
                "robot_state": {
                    "battery_level": self._battery_level,
                    "charging": False,
                    "docked": False,
                },
            }, room=sid)

        @self._sio.on("goodbye")
        async def on_goodbye(sid, data):
            reason = data.get("reason", "unknown")
            app_info = self._connected_apps.get(sid, {})
            logger.info(f"Goodbye from {app_info.get('app_id')}: {reason}")

        @self._sio.on("move_cmd")
        async def on_move_cmd(sid, data):
            cmd_id = data.get("cmd_id")
            linear_x = data.get("linear_x", 0.0)
            angular_z = data.get("angular_z", 0.0)

            app_info = self._connected_apps.get(sid, {})
            logger.info(f"[{app_info.get('app_id')}] move_cmd: linear={linear_x}, angular={angular_z}")

            # Update simulated velocity
            self._velocity["linear_x"] = linear_x
            self._velocity["angular_z"] = angular_z

            # Send ack
            await self._sio.emit("move_ack", {
                "cmd_id": cmd_id,
                "status": "ok",
            }, room=sid)

        @self._sio.on("stop_cmd")
        async def on_stop_cmd(sid, data):
            cmd_id = data.get("cmd_id")

            app_info = self._connected_apps.get(sid, {})
            logger.info(f"[{app_info.get('app_id')}] stop_cmd")

            self._velocity["linear_x"] = 0.0
            self._velocity["angular_z"] = 0.0

            await self._sio.emit("stop_ack", {
                "cmd_id": cmd_id,
                "status": "ok",
            }, room=sid)

        @self._sio.on("app_log")
        async def on_app_log(sid, data):
            app_info = self._connected_apps.get(sid, {})
            app_id = app_info.get("app_id", "unknown")
            level = data.get("level", "info")
            message = data.get("message", "")

            # Log the app's log
            log_prefix = f"[APP:{app_id}]"
            if level == "debug":
                logger.debug(f"{log_prefix} {message}")
            elif level == "info":
                logger.info(f"{log_prefix} {message}")
            elif level == "warning":
                logger.warning(f"{log_prefix} {message}")
            elif level == "error":
                logger.error(f"{log_prefix} {message}")

        @self._sio.on("subscribe_to_data_cmd")
        async def on_subscribe(sid, data):
            cmd_id = data.get("cmd_id")
            subscribe_list = data.get("subscribe", [])

            app_info = self._connected_apps.get(sid, {})

            for data_type in subscribe_list:
                # Normalize: "battery" -> "battery_data"
                key = data_type if data_type.endswith("_data") else f"{data_type}_data"
                if key not in self._subscriptions:
                    self._subscriptions[key] = set()
                self._subscriptions[key].add(sid)
                logger.info(f"[{app_info.get('app_id')}] subscribed to {key}")

            # Send response
            await self._sio.emit("subscribe_to_data_response", {
                "cmd_id": cmd_id,
                "success": True,
            }, room=sid)

        @self._sio.on("unsubscribe_data_cmd")
        async def on_unsubscribe(sid, data):
            unsubscribe_list = data.get("unsubscribe", [])
            for data_type in unsubscribe_list:
                key = data_type if data_type.endswith("_data") else f"{data_type}_data"
                if key in self._subscriptions:
                    self._subscriptions[key].discard(sid)

    async def _sensor_loop(self):
        """Send periodic sensor data to subscribers."""
        while True:
            await asyncio.sleep(1.0)

            # Update simulated pose based on velocity
            dt = 1.0
            self._pose["x"] += self._velocity["linear_x"] * dt
            self._pose["theta"] += self._velocity["angular_z"] * dt

            # Simulate battery drain
            if random.random() < 0.1:
                self._battery_level = max(0, self._battery_level - 1)

            timestamp = int(time.time() * 1000)

            # Send battery_data (per API_SENSOR_DATA.md)
            if "battery_data" in self._subscriptions:
                for sid in self._subscriptions["battery_data"]:
                    await self._sio.emit("battery_data", {
                        "level": self._battery_level,
                        "charging": False,
                        "timestamp": timestamp,
                    }, room=sid)

            # Send pose_data (per API_SENSOR_DATA.md)
            if "pose_data" in self._subscriptions:
                for sid in self._subscriptions["pose_data"]:
                    await self._sio.emit("pose_data", {
                        "x": self._pose["x"],
                        "y": self._pose["y"],
                        "theta": self._pose["theta"],
                        "timestamp": timestamp,
                    }, room=sid)

    async def start(self):
        """Start the mock server."""
        logger.info(f"Starting mock robot server on http://{self.host}:{self.port}")

        # Start sensor loop
        asyncio.create_task(self._sensor_loop())

        # Start web server
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        logger.info(f"Mock robot server running. Apps can connect to http://{self.host}:{self.port}")

    async def stop(self):
        """Stop the mock server."""
        logger.info("Stopping mock robot server")


async def run_mock_server(host: str = "127.0.0.1", port: int = 8788):
    """Run the mock server (convenience function)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    server = MockRobotServer(host=host, port=port)
    await server.start()

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await server.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mock Robot Server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8788,
                        help="Port (default: 8788)")
    args = parser.parse_args()

    asyncio.run(run_mock_server(host=args.host, port=args.port))
