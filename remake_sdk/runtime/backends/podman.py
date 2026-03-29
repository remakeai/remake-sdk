"""
Podman container backend.

Manages app containers via local Podman subprocess calls.
"""

import logging
import subprocess
from typing import Optional, List, Tuple

from . import ContainerBackend
from ..app_manager import ContainerStatus

logger = logging.getLogger(__name__)


class PodmanBackend(ContainerBackend):
    """Container backend using local Podman."""

    def __init__(self):
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._check_podman()
        return self._available

    def _check_podman(self) -> bool:
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

    def pull(self, image: str) -> Tuple[bool, Optional[str]]:
        try:
            logger.info(f"Pulling image {image}...")
            result = subprocess.run(
                ["podman", "pull", image],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                return False, f"Failed to pull image: {result.stderr.strip()}"
            return True, None
        except subprocess.TimeoutExpired:
            return False, "Image pull timed out"
        except Exception as e:
            return False, str(e)

    def image_exists(self, image: str) -> bool:
        try:
            result = subprocess.run(
                ["podman", "image", "exists", image],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def remove_image(self, image: str) -> bool:
        try:
            result = subprocess.run(
                ["podman", "rmi", "-f", image],
                capture_output=True,
                timeout=60
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"Failed to remove image: {e}")
            return False

    def run(
        self,
        app_id: str,
        image: str,
        ports: Optional[List[dict]] = None,
        environment: Optional[dict] = None,
        volumes: Optional[List[dict]] = None,
        network: Optional[str] = None,
        resources: Optional[dict] = None,
        labels: Optional[dict] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        # Stop existing container if running
        self.stop(app_id, force=True)

        cmd = ["podman", "run", "-d", "--rm", "--name", app_id]

        # Labels
        cmd.extend(["--label", f"remake.app_id={app_id}"])
        cmd.extend(["--label", "remake.managed=true"])
        if labels:
            for key, value in labels.items():
                cmd.extend(["--label", f"{key}={value}"])

        # Network
        if network:
            cmd.extend(["--network", network])

        # Ports
        if ports:
            for p in ports:
                host_port = p.get("host", p.get("container"))
                container_port = p["container"]
                cmd.extend(["-p", f"{host_port}:{container_port}"])

        # Environment
        if environment:
            for key, value in environment.items():
                cmd.extend(["-e", f"{key}={value}"])

        # Volumes
        if volumes:
            for v in volumes:
                mode = v.get("mode", "rw")
                cmd.extend(["-v", f"{v['host']}:{v['container']}:{mode}"])

        # Resource limits
        if resources:
            if resources.get("memory"):
                cmd.extend(["--memory", resources["memory"]])
            if resources.get("cpus"):
                cmd.extend(["--cpus", resources["cpus"]])

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
        try:
            result = subprocess.run(
                ["podman", "ps", "--format",
                 "{{.Names}}|{{.ID}}|{{.Status}}|{{.Image}}",
                 "--filter", "label=remake.managed=true"],
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

    def logs(self, app_id: str, tail: int = 100) -> Optional[str]:
        try:
            result = subprocess.run(
                ["podman", "logs", "--tail", str(tail), app_id],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except Exception:
            return None
