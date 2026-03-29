"""
App Manager - Manage app containers via pluggable backends.

Supports:
- PodmanBackend: Local Podman subprocess calls
- HostAgentBackend: HTTP calls to the Host Agent
- Auto-detection: tries Host Agent first, falls back to Podman
"""

import logging
import subprocess
from typing import Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

from .app_registry import AppRegistry, InstalledApp, PortMapping

logger = logging.getLogger(__name__)


@dataclass
class InstallResult:
    """Result of an app installation."""
    success: bool
    app_id: str
    version: Optional[str] = None
    container_image: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class ContainerStatus:
    """Status of a running container."""
    app_id: str
    container_id: str
    status: str  # "running", "exited", "created"
    image: str
    started_at: Optional[str] = None


class AppManager:
    """
    Manages app lifecycle using a pluggable container backend.

    Handles:
    - Installing apps (pulling container images)
    - Uninstalling apps (removing images)
    - Launching apps (running containers)
    - Stopping apps (stopping containers)
    - Checking app status

    Backend selection (runtime.backend config):
    - "agent": Always use the Host Agent
    - "podman": Always use local Podman
    - "auto": Try Host Agent first, fall back to Podman (default)
    """

    DEFAULT_REGISTRY = "registry.remake.ai/apps"

    def __init__(
        self,
        registry: Optional[AppRegistry] = None,
        backend: str = "auto",
        agent_url: Optional[str] = None,
    ):
        """
        Args:
            registry: App registry for tracking installed apps
            backend: Backend selection - "agent", "podman", or "auto"
            agent_url: Host Agent URL (for "agent" or "auto" backend)
        """
        self.registry = registry or AppRegistry()
        self._backend_name = backend
        self._agent_url = agent_url
        self._backend = None  # Lazy-resolved

    @property
    def backend(self):
        """Resolve and cache the container backend."""
        if self._backend is None:
            self._backend = self._resolve_backend()
        return self._backend

    def _resolve_backend(self):
        """Select container backend with auto-detection."""
        from .backends.podman import PodmanBackend
        from .backends.agent_client import HostAgentBackend

        configured = self._backend_name

        if configured == "agent":
            agent_url = self._agent_url or HostAgentBackend.DEFAULT_AGENT_URL if hasattr(HostAgentBackend, 'DEFAULT_AGENT_URL') else self._agent_url
            backend = HostAgentBackend(agent_url) if agent_url else HostAgentBackend()
            if not backend.is_available():
                raise RuntimeError(
                    f"Host Agent not reachable at {backend.agent_url}. "
                    "Start the agent with: python -m remake_agent"
                )
            logger.info(f"Using Host Agent backend at {backend.agent_url}")
            return backend

        if configured == "podman":
            backend = PodmanBackend()
            if not backend.is_available():
                raise RuntimeError(
                    "Podman is not installed or not accessible. "
                    "Install with: apt-get install podman"
                )
            logger.info("Using Podman backend")
            return backend

        # Auto-detect: try Host Agent first, fall back to Podman
        if self._agent_url:
            agent_backend = HostAgentBackend(self._agent_url)
            if agent_backend.is_available():
                logger.info(f"Host Agent detected at {self._agent_url}, using agent backend")
                return agent_backend

        podman_backend = PodmanBackend()
        if podman_backend.is_available():
            logger.info("Podman detected, using podman backend")
            return podman_backend

        raise RuntimeError(
            "No container backend available. "
            "Either start the Host Agent or install Podman."
        )

    @property
    def backend_name(self) -> str:
        """Return the name of the active backend."""
        from .backends.podman import PodmanBackend
        from .backends.agent_client import HostAgentBackend
        b = self.backend
        if isinstance(b, HostAgentBackend):
            return "agent"
        if isinstance(b, PodmanBackend):
            return "podman"
        return "unknown"

    def install(
        self,
        app_id: str,
        version: str = "latest",
        container_image: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        entitlements: Optional[List[str]] = None,
        source: str = "local",
        manifest: Optional[dict] = None
    ) -> InstallResult:
        """
        Install an app by pulling its container image.

        Args:
            app_id: App identifier (e.g., "com.funrobots.chase-game")
            version: Version tag (default: "latest")
            container_image: Full image URL (if not using default registry)
            name: Display name
            description: App description
            entitlements: List of required permissions
            source: "local" or "platform"
            manifest: Full manifest dict (ports, environment, etc.)

        Returns:
            InstallResult with success status
        """
        if not container_image:
            container_image = f"{self.DEFAULT_REGISTRY}/{app_id}:{version}"

        logger.info(f"Installing app {app_id} from {container_image}")

        # Pull the image if it doesn't exist locally
        if not self.backend.image_exists(container_image):
            success, error = self.backend.pull(container_image)
            if not success:
                return InstallResult(
                    success=False,
                    app_id=app_id,
                    container_image=container_image,
                    error="pull_failed",
                    message=error
                )
        else:
            logger.info(f"Image {container_image} already exists")

        # Extract ports and environment from manifest
        ports = None
        environment = None
        if manifest:
            if not name:
                name = manifest.get("name")
            if not description:
                description = manifest.get("description")
            if not entitlements:
                entitlements = manifest.get("capabilities") or manifest.get("entitlements")

            if manifest.get("ports"):
                ports = [
                    PortMapping(
                        container=p.get("container"),
                        host=p.get("host", p.get("container")),
                        protocol=p.get("protocol", "tcp"),
                        description=p.get("description"),
                    )
                    for p in manifest["ports"]
                ]

            environment = manifest.get("environment")

        # Register the app
        app = InstalledApp(
            app_id=app_id,
            version=version,
            container_image=container_image,
            name=name or app_id,
            description=description,
            entitlements=entitlements,
            installed_at=datetime.utcnow().isoformat(),
            source=source,
            ports=ports,
            environment=environment,
        )
        self.registry.add(app)

        logger.info(f"App {app_id} installed successfully")
        return InstallResult(
            success=True,
            app_id=app_id,
            version=version,
            container_image=container_image,
            message="App installed successfully"
        )

    def uninstall(self, app_id: str, remove_image: bool = True) -> InstallResult:
        """
        Uninstall an app.

        Args:
            app_id: App identifier
            remove_image: Also remove the container image

        Returns:
            InstallResult with success status
        """
        app = self.registry.get(app_id)
        if not app:
            return InstallResult(
                success=False,
                app_id=app_id,
                error="not_installed",
                message=f"App {app_id} is not installed"
            )

        # Stop any running containers first
        self.stop(app_id, force=True)

        # Remove the image
        if remove_image:
            self.backend.remove_image(app.container_image)

        # Remove from registry
        self.registry.remove(app_id)

        return InstallResult(
            success=True,
            app_id=app_id,
            message="App uninstalled successfully"
        )

    def launch(
        self,
        app_id: str,
        container_image: Optional[str] = None,
        entitlements: Optional[List[str]] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Launch an app container.

        Args:
            app_id: App identifier (also used as container name)
            container_image: Override container image
            entitlements: List of entitlements (for capability mapping)

        Returns:
            Tuple of (success, container_id or error, message)
        """
        app = self.registry.get(app_id)
        if not app and not container_image:
            return False, "not_installed", f"App {app_id} is not installed"

        image = container_image or app.container_image

        return self.backend.run(
            app_id=app_id,
            image=image,
        )

    def stop(self, app_id: str, force: bool = False) -> Tuple[bool, str]:
        """
        Stop a running app container.

        Args:
            app_id: App identifier (container name)
            force: Use SIGKILL instead of SIGTERM

        Returns:
            Tuple of (success, message)
        """
        return self.backend.stop(app_id, force=force)

    def status(self, app_id: str) -> Optional[ContainerStatus]:
        """Get status of a running app container."""
        return self.backend.status(app_id)

    def list_running(self) -> List[ContainerStatus]:
        """List all running app containers."""
        return self.backend.list_running()
