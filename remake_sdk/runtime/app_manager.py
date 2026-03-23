"""
App Manager - Manage app containers via Podman.
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
    Manages app lifecycle using Podman.

    Handles:
    - Installing apps (pulling container images)
    - Uninstalling apps (removing images)
    - Launching apps (running containers)
    - Stopping apps (stopping containers)
    - Checking app status
    """

    # Default registry for remake apps
    DEFAULT_REGISTRY = "registry.remake.ai/apps"

    def __init__(self, registry: Optional[AppRegistry] = None):
        self.registry = registry or AppRegistry()
        self._podman_available = self._check_podman()

    def _check_podman(self) -> bool:
        """Check if podman is available."""
        try:
            result = subprocess.run(
                ["podman", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

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
        if not self._podman_available:
            return InstallResult(
                success=False,
                app_id=app_id,
                error="podman_not_available",
                message="Podman is not installed or not accessible"
            )

        # Determine container image
        if not container_image:
            container_image = f"{self.DEFAULT_REGISTRY}/{app_id}:{version}"

        logger.info(f"Installing app {app_id} from {container_image}")

        # Check if image already exists locally
        image_exists = False
        try:
            result = subprocess.run(
                ["podman", "image", "exists", container_image],
                capture_output=True,
                timeout=10
            )
            image_exists = result.returncode == 0
        except Exception:
            pass

        # Pull the image only if it doesn't exist locally
        if not image_exists:
            try:
                logger.info(f"Pulling image {container_image}...")
                result = subprocess.run(
                    ["podman", "pull", container_image],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout for large images
                )

                if result.returncode != 0:
                    logger.error(f"Failed to pull image: {result.stderr}")
                    return InstallResult(
                        success=False,
                        app_id=app_id,
                        container_image=container_image,
                        error="pull_failed",
                        message=f"Failed to pull image: {result.stderr.strip()}"
                    )

            except subprocess.TimeoutExpired:
                return InstallResult(
                    success=False,
                    app_id=app_id,
                    container_image=container_image,
                    error="timeout",
                    message="Image pull timed out"
                )
            except Exception as e:
                return InstallResult(
                    success=False,
                    app_id=app_id,
                    container_image=container_image,
                    error="exception",
                    message=str(e)
                )
        else:
            logger.info(f"Image {container_image} already exists locally")

        # Extract ports and environment from manifest
        ports = None
        environment = None
        if manifest:
            # Get name/description from manifest if not provided
            if not name:
                name = manifest.get("name")
            if not description:
                description = manifest.get("description")
            if not entitlements:
                entitlements = manifest.get("capabilities") or manifest.get("entitlements")

            # Parse ports
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

            # Get environment
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
        if remove_image and self._podman_available:
            try:
                subprocess.run(
                    ["podman", "rmi", "-f", app.container_image],
                    capture_output=True,
                    timeout=60
                )
            except Exception as e:
                logger.warning(f"Failed to remove image: {e}")

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
        if not self._podman_available:
            return False, "podman_not_available", "Podman is not installed"

        # Get app info
        app = self.registry.get(app_id)
        if not app and not container_image:
            return False, "not_installed", f"App {app_id} is not installed"

        image = container_image or app.container_image

        # Stop existing container if running
        self.stop(app_id, force=True)

        # Build run command
        cmd = [
            "podman", "run",
            "-d",  # Detached
            "--rm",  # Remove on exit
            "--name", app_id,
            # TODO: Map entitlements to capabilities/devices
        ]

        # Add the image
        cmd.append(image)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                return False, "launch_failed", result.stderr.strip()

            container_id = result.stdout.strip()[:12]
            return True, container_id, "App launched successfully"

        except Exception as e:
            return False, "exception", str(e)

    def stop(self, app_id: str, force: bool = False) -> Tuple[bool, str]:
        """
        Stop a running app container.

        Args:
            app_id: App identifier (container name)
            force: Use SIGKILL instead of SIGTERM

        Returns:
            Tuple of (success, message)
        """
        if not self._podman_available:
            return False, "Podman is not installed"

        cmd = ["podman", "kill" if force else "stop", app_id]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return True, "App stopped"
            elif "no such container" in result.stderr.lower():
                return True, "App was not running"
            else:
                return False, result.stderr.strip()

        except Exception as e:
            return False, str(e)

    def status(self, app_id: str) -> Optional[ContainerStatus]:
        """Get status of a running app container."""
        if not self._podman_available:
            return None

        try:
            result = subprocess.run(
                ["podman", "inspect", "--format",
                 "{{.Id}}|{{.State.Status}}|{{.Config.Image}}|{{.State.StartedAt}}",
                 app_id],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return None

            parts = result.stdout.strip().split("|")
            if len(parts) >= 4:
                return ContainerStatus(
                    app_id=app_id,
                    container_id=parts[0][:12],
                    status=parts[1],
                    image=parts[2],
                    started_at=parts[3][:19].replace("T", " ") if parts[3] else None
                )

        except Exception:
            pass

        return None

    def list_running(self) -> List[ContainerStatus]:
        """List all running app containers."""
        if not self._podman_available:
            return []

        try:
            result = subprocess.run(
                ["podman", "ps", "--format",
                 "{{.Names}}|{{.ID}}|{{.Status}}|{{.Image}}"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return []

            containers = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    containers.append(ContainerStatus(
                        app_id=parts[0],
                        container_id=parts[1][:12],
                        status=parts[2],
                        image=parts[3]
                    ))

            return containers

        except Exception:
            return []
