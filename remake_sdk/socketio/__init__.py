"""
Socket.IO SDK - Robot-to-app communication.

This module handles communication between the robot runtime and apps:
- RobotClient: For apps to connect to and communicate with the robot
- MockRobotServer: For testing apps without a real robot

Example (App side):
    from remake_sdk.socketio import RobotClient

    client = RobotClient()
    await client.connect()

    await client.log("App started!")
    await client.move(linear_x=0.5)

    @client.on_battery
    def handle_battery(data):
        print(f"Battery: {data['level']}%")

    await client.run()

Example (Testing with mock server):
    from remake_sdk.socketio import MockRobotServer

    server = MockRobotServer(port=8788)
    await server.start()
    # Apps can now connect to http://localhost:8788
"""

from .client import RobotClient
from .mock_server import MockRobotServer, run_mock_server

__all__ = [
    "RobotClient",
    "MockRobotServer",
    "run_mock_server",
]
