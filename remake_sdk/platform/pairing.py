"""
Pairing Client - Robot pairing flow via Socket.IO.

Handles the pairing process for a new robot:
1. Connect to platform (unauthenticated)
2. Request pairing with user email
3. Wait for user approval
4. Receive and store credentials
5. Authenticate with new credentials

Example:
    from remake_sdk.platform import PairingClient

    pairing = PairingClient("http://localhost:5000")

    # Request pairing
    result = await pairing.request_pairing(
        user_email="user@example.com",
        robot_name="My Robot"
    )

    if result.success:
        print(f"Paired! Robot ID: {result.robot_id}")
        # Save credentials
        save_credentials(result.robot_id, result.robot_secret)
"""

import asyncio
import logging
import uuid
from typing import Optional, Callable
from dataclasses import dataclass

import socketio

from ..common.types import PairingStatus, PairingCredentials

logger = logging.getLogger(__name__)


class PairingError(Exception):
    """Pairing operation failed."""
    pass


class PairingTimeoutError(PairingError):
    """Pairing approval timed out."""
    pass


class PairingRejectedError(PairingError):
    """User rejected the pairing request."""
    pass


@dataclass
class PairingResult:
    """Result of a pairing operation."""
    success: bool
    status: PairingStatus
    robot_id: Optional[str] = None
    robot_secret: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None

    @property
    def credentials(self) -> Optional[PairingCredentials]:
        """Get credentials if pairing succeeded."""
        if self.success and self.robot_id and self.robot_secret:
            return PairingCredentials(
                robot_id=self.robot_id,
                robot_secret=self.robot_secret
            )
        return None


class PairingClient:
    """
    Socket.IO client for robot pairing.

    This client handles the pairing flow for new robots that don't
    yet have credentials.

    Args:
        platform_url: URL of the platform server (e.g., "http://localhost:5000")
        on_status_change: Optional callback for status updates

    Example:
        async with PairingClient("http://localhost:5000") as client:
            result = await client.request_pairing("user@example.com", "My Robot")
            if result.success:
                print(f"Robot ID: {result.robot_id}")
    """

    NAMESPACE = "/robot-control"
    DEFAULT_TIMEOUT = 300  # 5 minutes

    def __init__(
        self,
        platform_url: str,
        on_status_change: Optional[Callable[[PairingStatus, str], None]] = None
    ):
        self._platform_url = platform_url.rstrip('/')
        self._on_status_change = on_status_change

        # Socket.IO client
        self._sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=1,
            reconnection_delay_max=10,
            logger=False,
            engineio_logger=False,
        )

        # State
        self._connected = False
        self._pairing_result: Optional[PairingResult] = None
        self._pairing_complete = asyncio.Event()
        self._credentials: Optional[PairingCredentials] = None

        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self._sio.on("connect", namespace=self.NAMESPACE)
        async def on_connect():
            logger.info(f"Connected to {self._platform_url}")
            self._connected = True

        @self._sio.on("disconnect", namespace=self.NAMESPACE)
        async def on_disconnect():
            logger.info("Disconnected from platform")
            self._connected = False

        @self._sio.on("pair_response", namespace=self.NAMESPACE)
        async def on_pair_response(data):
            """Handle initial pairing response."""
            status = data.get("status")
            logger.info(f"Pairing response: {status}")

            if status == "pending":
                self._notify_status(PairingStatus.PENDING, "Waiting for user approval")
            elif status == "failed":
                error = data.get("error", "unknown")
                message = data.get("message", "Pairing failed")
                self._pairing_result = PairingResult(
                    success=False,
                    status=PairingStatus.FAILED,
                    error=error,
                    message=message
                )
                self._pairing_complete.set()

        @self._sio.on("pair_status_event", namespace=self.NAMESPACE)
        async def on_pair_status(data):
            """Handle pairing status update (approval/rejection/credentials)."""
            status = data.get("status")
            logger.info(f"Pairing status event: {status}")

            if status == "paired":
                # Success - we have credentials
                robot_id = data.get("robot_id")
                robot_secret = data.get("robot_secret")

                if robot_id and robot_secret:
                    self._credentials = PairingCredentials(
                        robot_id=robot_id,
                        robot_secret=robot_secret
                    )
                    self._pairing_result = PairingResult(
                        success=True,
                        status=PairingStatus.PAIRED,
                        robot_id=robot_id,
                        robot_secret=robot_secret,
                        message="Pairing successful"
                    )
                    self._notify_status(PairingStatus.PAIRED, "Pairing successful")
                else:
                    self._pairing_result = PairingResult(
                        success=False,
                        status=PairingStatus.FAILED,
                        error="missing_credentials",
                        message="Server did not provide credentials"
                    )

                self._pairing_complete.set()

            elif status == "rejected" or status == "denied":
                self._pairing_result = PairingResult(
                    success=False,
                    status=PairingStatus.REJECTED,
                    error="rejected",
                    message="User rejected the pairing request"
                )
                self._notify_status(PairingStatus.REJECTED, "Pairing rejected by user")
                self._pairing_complete.set()

            elif status == "expired":
                self._pairing_result = PairingResult(
                    success=False,
                    status=PairingStatus.EXPIRED,
                    error="expired",
                    message="Pairing request expired"
                )
                self._notify_status(PairingStatus.EXPIRED, "Pairing request expired")
                self._pairing_complete.set()

        @self._sio.on("pairing_approved", namespace=self.NAMESPACE)
        async def on_pairing_approved(data):
            """Alternative event name for approval."""
            # Some implementations use this event name
            await on_pair_status({"status": "paired", **data})

        @self._sio.on("pairing_denied", namespace=self.NAMESPACE)
        async def on_pairing_denied(data):
            """Alternative event name for rejection."""
            await on_pair_status({"status": "rejected", **data})

        @self._sio.on("get_pairing_status_response", namespace=self.NAMESPACE)
        async def on_status_response(data):
            """Handle polling response for pairing status."""
            status = data.get("status")
            logger.debug(f"Pairing status poll: {status}")

            if status == "approved" or status == "paired":
                robot_id = data.get("robot_id")
                robot_secret = data.get("robot_secret")

                if robot_id and robot_secret:
                    self._credentials = PairingCredentials(
                        robot_id=robot_id,
                        robot_secret=robot_secret
                    )
                    self._pairing_result = PairingResult(
                        success=True,
                        status=PairingStatus.PAIRED,
                        robot_id=robot_id,
                        robot_secret=robot_secret
                    )
                    self._pairing_complete.set()

            elif status == "rejected" or status == "denied":
                self._pairing_result = PairingResult(
                    success=False,
                    status=PairingStatus.REJECTED,
                    error="rejected",
                    message="User rejected the pairing request"
                )
                self._pairing_complete.set()

        @self._sio.on("connect_error", namespace=self.NAMESPACE)
        async def on_connect_error(data):
            logger.error(f"Connection error: {data}")

    def _notify_status(self, status: PairingStatus, message: str):
        """Notify status change callback."""
        if self._on_status_change:
            try:
                self._on_status_change(status, message)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")

    async def connect(self, timeout: float = 15.0) -> bool:
        """
        Connect to the platform server.

        Args:
            timeout: Connection timeout in seconds.

        Returns:
            True if connected successfully.

        Raises:
            PairingError: If connection fails.
        """
        try:
            await asyncio.wait_for(
                self._sio.connect(
                    self._platform_url,
                    namespaces=[self.NAMESPACE],
                    transports=["websocket"],
                ),
                timeout=timeout
            )
            return True
        except asyncio.TimeoutError:
            raise PairingError("Connection timeout")
        except Exception as e:
            raise PairingError(f"Connection failed: {e}")

    async def disconnect(self):
        """Disconnect from the platform."""
        if self._sio.connected:
            await self._sio.disconnect()

    async def request_pairing(
        self,
        user_email: str,
        robot_name: str = "Robot",
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = 3.0
    ) -> PairingResult:
        """
        Request pairing with a user account.

        This method:
        1. Sends a pairing request to the platform
        2. Waits for user approval (or timeout)
        3. Returns credentials on success

        Args:
            user_email: Email of the user to pair with.
            robot_name: Display name for the robot.
            timeout: Maximum time to wait for approval (seconds).
            poll_interval: How often to poll for status (seconds).

        Returns:
            PairingResult with credentials on success.

        Raises:
            PairingError: If not connected.
            PairingTimeoutError: If approval times out.
            PairingRejectedError: If user rejects the request.
        """
        if not self._sio.connected:
            raise PairingError("Not connected. Call connect() first.")

        # Reset state
        self._pairing_result = None
        self._pairing_complete.clear()
        self._credentials = None

        # Send pairing request
        cmd_id = str(uuid.uuid4())
        logger.info(f"Requesting pairing with {user_email} as '{robot_name}'")

        await self._sio.emit("pair_cmd", {
            "cmd_id": cmd_id,
            "method": "approval",
            "username": user_email,
            "robot_name": robot_name
        }, namespace=self.NAMESPACE)

        # Wait for result with polling
        start_time = asyncio.get_event_loop().time()

        while True:
            try:
                remaining = timeout - (asyncio.get_event_loop().time() - start_time)
                if remaining <= 0:
                    break

                wait_time = min(poll_interval, remaining)
                await asyncio.wait_for(
                    self._pairing_complete.wait(),
                    timeout=wait_time
                )

                # Got a result
                if self._pairing_result:
                    return self._pairing_result

            except asyncio.TimeoutError:
                # Poll for status
                if self._sio.connected:
                    await self._sio.emit("get_pairing_status", {
                        "cmd_id": str(uuid.uuid4()),
                        "username": user_email
                    }, namespace=self.NAMESPACE)

        # Timeout
        return PairingResult(
            success=False,
            status=PairingStatus.EXPIRED,
            error="timeout",
            message=f"Pairing approval timed out after {timeout} seconds"
        )

    @property
    def credentials(self) -> Optional[PairingCredentials]:
        """Get credentials if pairing succeeded."""
        return self._credentials

    @property
    def is_connected(self) -> bool:
        """Check if connected to platform."""
        return self._connected

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
