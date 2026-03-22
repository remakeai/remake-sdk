"""Shared types for the Remake SDK."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ConnectionState(Enum):
    """Connection state for platform or app connections."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class AppCommand:
    """Command received from platform to manage an app."""
    action: str  # "install", "uninstall", "launch", "stop", "revoke"
    app_id: str
    app_version: Optional[str] = None
    container_image: Optional[str] = None
    entitlements: List[str] = field(default_factory=list)
    purchase_token: Optional[str] = None
    cmd_id: Optional[str] = None


class PairingStatus(Enum):
    """Status of a pairing request."""
    PENDING = "pending"
    APPROVED = "approved"
    PAIRED = "paired"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass
class PairingResult:
    """Result of a pairing operation."""
    success: bool
    robot_id: Optional[str] = None
    robot_secret: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class PairingCredentials:
    """Credentials received after successful pairing."""
    robot_id: str
    robot_secret: str


@dataclass
class RobotStatus:
    """Robot status information."""
    robot_id: str
    status: str  # "idle", "running", "error", "offline"
    running_app_id: Optional[str] = None
    battery_level: Optional[int] = None
    error_message: Optional[str] = None
    last_seen: Optional[datetime] = None
