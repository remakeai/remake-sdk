#!/usr/bin/env python3
"""
Robot Chat App - Sample app demonstrating robot SDK communication.

This app demonstrates:
1. Connecting to the robot runtime via Socket.IO
2. Sending log events
3. Subscribing to sensor data (battery, pose)
4. Sending movement commands
5. Graceful shutdown
"""

import asyncio
import signal
import sys
import os
import logging

# Add SDK to path for local development (when running from examples/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from remake_sdk.socketio import RobotClient

# App metadata
APP_ID = "com.example.robot-chat"
VERSION = "1.0.0"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class RobotChatApp:
    """Sample app that chats with the robot."""

    def __init__(self):
        self.client = RobotClient(
            app_id=APP_ID,
            app_version=VERSION,
        )
        self.running = True
        self.battery_level = 100
        self.pose = {"x": 0, "y": 0, "theta": 0}

    async def start(self):
        """Start the app."""
        logger.info(f"Robot Chat App v{VERSION}")
        logger.info(f"App ID: {APP_ID}")
        logger.info("")

        # Connect to robot
        logger.info("Connecting to robot runtime...")
        connected = await self.client.connect(timeout=10.0)

        if not connected:
            logger.error("Failed to connect to robot!")
            logger.error("Make sure the mock server is running:")
            logger.error("  python -m remake_sdk.socketio.mock_server")
            return False

        logger.info(f"Connected to robot: {self.client.robot_id}")
        logger.info(f"Granted capabilities: {self.client.granted_capabilities}")
        logger.info("")

        # Register event handlers
        self._setup_handlers()

        # Subscribe to sensor data (using subscribe_to_data_cmd format)
        await self.client.subscribe(sensor="battery")
        await self.client.subscribe(sensor="pose")

        # Send initial log
        await self.client.log("App started successfully!", level="info")

        return True

    def _setup_handlers(self):
        """Set up event handlers."""

        @self.client.on_battery
        def handle_battery(data):
            self.battery_level = data.get("level", 0)
            charging = data.get("charging", False)
            status = "charging" if charging else "discharging"
            logger.info(f"Battery: {self.battery_level}% ({status})")

            # Log warning if low
            if self.battery_level < 20:
                asyncio.create_task(
                    self.client.log(f"Low battery: {self.battery_level}%", level="warning")
                )

        @self.client.on_pose
        def handle_pose(data):
            self.pose = {
                "x": data.get("x", 0),
                "y": data.get("y", 0),
                "theta": data.get("theta", 0),
            }
            logger.debug(f"Pose: x={self.pose['x']:.2f}, y={self.pose['y']:.2f}, theta={self.pose['theta']:.2f}")

    async def run_demo(self):
        """Run a demo sequence."""
        logger.info("Starting demo sequence...")
        logger.info("-" * 40)

        # Demo 1: Log events
        await self.client.log("Demo: Testing log events", level="info")
        await asyncio.sleep(1)

        # Demo 2: Movement commands
        logger.info("Demo: Sending move command (forward)...")
        await self.client.log("Moving forward", level="debug", data={"linear_x": 0.3})
        await self.client.move(linear_x=0.3)
        await asyncio.sleep(3)

        logger.info("Demo: Sending move command (rotate)...")
        await self.client.log("Rotating", level="debug", data={"angular_z": 0.5})
        await self.client.move(angular_z=0.5)
        await asyncio.sleep(2)

        logger.info("Demo: Sending stop command...")
        await self.client.stop()
        await asyncio.sleep(1)

        # Demo 3: Report status
        await self.client.log(
            "Demo complete",
            level="info",
            data={
                "final_pose": self.pose,
                "battery": self.battery_level,
            }
        )

        logger.info("-" * 40)
        logger.info("Demo sequence complete!")
        logger.info("")

    async def run(self):
        """Run the app main loop."""
        logger.info("App is running. Press Ctrl+C to stop.")
        logger.info("")

        counter = 0
        while self.running:
            counter += 1

            # Periodic status log every 10 seconds
            if counter % 10 == 0:
                await self.client.log(
                    f"Heartbeat #{counter // 10}",
                    level="debug",
                    data={
                        "battery": self.battery_level,
                        "pose": self.pose,
                    }
                )

            await asyncio.sleep(1)

    async def stop(self):
        """Stop the app gracefully."""
        logger.info("Stopping app...")
        self.running = False

        await self.client.log("App shutting down", level="info")
        await self.client.disconnect()

        logger.info("App stopped.")


async def main():
    """Main entry point."""
    app = RobotChatApp()

    # Handle signals
    loop = asyncio.get_event_loop()

    def signal_handler():
        asyncio.create_task(app.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Start app
    if not await app.start():
        sys.exit(1)

    # Run demo
    await app.run_demo()

    # Run main loop
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
