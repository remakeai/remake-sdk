"""
Socket.IO SDK - Robot-to-app communication.

This module handles communication between the robot runtime and apps:
- Socket.IO server for app connections
- Message handling per ROBOT_APP_API.md
- Entitlement enforcement

Example:
    from remake_sdk.socketio import AppServer

    server = AppServer(socket_path="/var/run/remake/robot.sock")

    @server.on_move_cmd
    def handle_move(cmd):
        publish_to_ros2(cmd)

    await server.start()
"""

# TODO: Implement in Phase 3
# from .server import AppServer
# from .messages import MoveCmd, StopCmd, NavigateCmd

__all__ = []
