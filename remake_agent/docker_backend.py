"""
Docker backend for the Host Agent.

Manages containers using the Docker SDK (docker-py).
Falls back to subprocess calls if the Docker SDK is not available.
"""

import logging
import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Try to import Docker SDK; fall back to subprocess
try:
    import docker
    HAS_DOCKER_SDK = True
except ImportError:
    HAS_DOCKER_SDK = False
    logger.info("Docker SDK not available, using subprocess fallback")


class DockerBackend:
    """
    Manages Docker containers for the Host Agent.

    Uses the Docker SDK when available, falls back to
    subprocess calls to the docker/podman CLI.
    """

    def __init__(self, runtime: str = "docker", network: str = "remake-net",
                 data_root: str = "~/.remake",
                 default_memory: str = "256m", default_cpus: str = "1.0"):
        self.runtime = runtime  # "docker" or "podman"
        self.network = network
        self.data_root = os.path.expanduser(data_root)
        self.default_memory = default_memory
        self.default_cpus = default_cpus
        self._client = None

        if HAS_DOCKER_SDK and runtime == "docker":
            try:
                self._client = docker.from_env()
                self._client.ping()
                logger.info("Connected to Docker daemon via SDK")
            except Exception as e:
                logger.warning(f"Docker SDK connection failed ({e}), using subprocess")
                self._client = None

    def _cmd(self) -> str:
        """Get the container runtime command."""
        return self.runtime

    def ensure_network(self):
        """Create the shared network if it doesn't exist."""
        if self._client:
            try:
                self._client.networks.get(self.network)
                logger.info(f"Network {self.network} already exists")
            except docker.errors.NotFound:
                self._client.networks.create(self.network, driver="bridge")
                logger.info(f"Created network {self.network}")
            return

        # Subprocess fallback
        result = subprocess.run(
            [self._cmd(), "network", "inspect", self.network],
            capture_output=True
        )
        if result.returncode != 0:
            subprocess.run(
                [self._cmd(), "network", "create", self.network],
                capture_output=True, check=True
            )
            logger.info(f"Created network {self.network}")

    def ensure_app_dirs(self, app_id: str):
        """Create data/cache directories for an app."""
        app_dir = Path(self.data_root) / "apps" / app_id
        (app_dir / "data").mkdir(parents=True, exist_ok=True)
        (app_dir / "cache").mkdir(parents=True, exist_ok=True)

        shared_dir = Path(self.data_root) / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)

        return {
            "data": str(app_dir / "data"),
            "cache": str(app_dir / "cache"),
            "shared": str(shared_dir),
        }

    def remove_app_dirs(self, app_id: str):
        """Remove data directories for an app."""
        app_dir = Path(self.data_root) / "apps" / app_id
        if app_dir.exists():
            shutil.rmtree(app_dir, ignore_errors=True)

    def pull(self, image: str) -> Dict[str, Any]:
        """Pull a container image."""
        if self._client:
            try:
                self._client.images.pull(image)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}

        result = subprocess.run(
            [self._cmd(), "pull", image],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"success": True}
        return {"success": False, "error": result.stderr.strip()}

    def image_exists(self, image: str) -> bool:
        """Check if an image exists locally."""
        if self._client:
            try:
                self._client.images.get(image)
                return True
            except Exception:
                return False

        result = subprocess.run(
            [self._cmd(), "image", "inspect", image],
            capture_output=True
        )
        return result.returncode == 0

    def remove_image(self, image: str) -> bool:
        """Remove a container image."""
        if self._client:
            try:
                self._client.images.remove(image, force=True)
                return True
            except Exception:
                return False

        result = subprocess.run(
            [self._cmd(), "rmi", "-f", image],
            capture_output=True
        )
        return result.returncode == 0

    def create_container(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create and start a container."""
        app_id = config["app_id"]
        image = config["image"]

        # Stop existing container if running
        self.stop_container(app_id, force=True)

        # Ensure app directories exist
        dirs = self.ensure_app_dirs(app_id)

        # Build volume config: merge user-provided with defaults
        volumes = list(config.get("volumes", []))
        # Add default app data volumes if not already mapped
        container_paths = {v["container"] for v in volumes}
        if "/app/data" not in container_paths:
            volumes.append({"host": dirs["data"], "container": "/app/data", "mode": "rw"})
        if "/app/cache" not in container_paths:
            volumes.append({"host": dirs["cache"], "container": "/app/cache", "mode": "rw"})
        if "/app/shared" not in container_paths:
            volumes.append({"host": dirs["shared"], "container": "/app/shared", "mode": "ro"})

        # Build environment
        environment = dict(config.get("environment", {}))
        environment.setdefault("REMAKE_APP_ID", app_id)
        environment.setdefault("REMAKE_DATA_DIR", "/app/data")
        environment.setdefault("REMAKE_CACHE_DIR", "/app/cache")
        environment.setdefault("REMAKE_SHARED_DIR", "/app/shared")

        # Network
        network = config.get("network", self.network)

        # Resource limits
        resources = config.get("resources", {})
        memory = resources.get("memory", self.default_memory)
        cpus = resources.get("cpus", self.default_cpus)

        # Labels
        labels = dict(config.get("labels", {}))
        labels["remake.app_id"] = app_id
        labels["remake.managed"] = "true"

        # Ports
        ports = config.get("ports", [])

        if self._client:
            return self._create_with_sdk(
                app_id, image, network, ports, environment, volumes,
                memory, cpus, labels
            )

        return self._create_with_subprocess(
            app_id, image, network, ports, environment, volumes,
            memory, cpus, labels
        )

    def _create_with_sdk(self, app_id, image, network, ports, environment,
                         volumes, memory, cpus, labels) -> Dict[str, Any]:
        """Create container using Docker SDK."""
        try:
            # Build port bindings
            port_bindings = {}
            exposed_ports = {}
            for p in ports:
                container_port = f"{p['container']}/tcp"
                exposed_ports[container_port] = {}
                port_bindings[container_port] = ("0.0.0.0", p.get("host", p["container"]))

            # Build volume bindings
            binds = []
            for v in volumes:
                mode = v.get("mode", "rw")
                binds.append(f"{v['host']}:{v['container']}:{mode}")

            # Parse memory limit
            mem_limit = memory
            if memory.endswith("m"):
                mem_limit = int(memory[:-1]) * 1024 * 1024
            elif memory.endswith("g"):
                mem_limit = int(memory[:-1]) * 1024 * 1024 * 1024

            container = self._client.containers.run(
                image,
                name=app_id,
                detach=True,
                auto_remove=True,
                network=network,
                ports=port_bindings if port_bindings else None,
                environment=environment,
                volumes=binds if binds else None,
                labels=labels,
                mem_limit=mem_limit,
                nano_cpus=int(float(cpus) * 1e9),
            )

            return {
                "success": True,
                "container_id": container.short_id,
                "message": "App launched successfully",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "launch_failed",
                "message": str(e),
            }

    def _create_with_subprocess(self, app_id, image, network, ports,
                                environment, volumes, memory, cpus,
                                labels) -> Dict[str, Any]:
        """Create container using subprocess."""
        cmd = [self._cmd(), "run", "-d", "--rm", "--name", app_id]

        # Network
        if network:
            cmd.extend(["--network", network])

        # Ports
        for p in ports:
            host_port = p.get("host", p["container"])
            cmd.extend(["-p", f"{host_port}:{p['container']}"])

        # Environment
        for key, value in environment.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Volumes
        for v in volumes:
            mode = v.get("mode", "rw")
            cmd.extend(["-v", f"{v['host']}:{v['container']}:{mode}"])

        # Resource limits
        if memory:
            cmd.extend(["--memory", memory])
        if cpus:
            cmd.extend(["--cpus", cpus])

        # Labels
        for key, value in labels.items():
            cmd.extend(["--label", f"{key}={value}"])

        cmd.append(image)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return {
                    "success": False,
                    "error": "launch_failed",
                    "message": result.stderr.strip(),
                }
            return {
                "success": True,
                "container_id": result.stdout.strip()[:12],
                "message": "App launched successfully",
            }
        except Exception as e:
            return {"success": False, "error": "exception", "message": str(e)}

    def stop_container(self, app_id: str, force: bool = False) -> Dict[str, Any]:
        """Stop a container."""
        if self._client:
            try:
                container = self._client.containers.get(app_id)
                if force:
                    container.kill()
                else:
                    container.stop(timeout=10)
                return {"success": True, "message": "App stopped"}
            except docker.errors.NotFound:
                return {"success": True, "message": "App was not running"}
            except Exception as e:
                return {"success": False, "message": str(e)}

        action = "kill" if force else "stop"
        result = subprocess.run(
            [self._cmd(), action, app_id],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return {"success": True, "message": "App stopped"}
        if "no such container" in result.stderr.lower() or "not found" in result.stderr.lower():
            return {"success": True, "message": "App was not running"}
        return {"success": False, "message": result.stderr.strip()}

    def remove_container(self, app_id: str) -> Dict[str, Any]:
        """Remove a stopped container."""
        if self._client:
            try:
                container = self._client.containers.get(app_id)
                container.remove(force=True)
                return {"success": True}
            except docker.errors.NotFound:
                return {"success": True, "message": "Container not found"}
            except Exception as e:
                return {"success": False, "message": str(e)}

        result = subprocess.run(
            [self._cmd(), "rm", "-f", app_id],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 or "no such container" in result.stderr.lower():
            return {"success": True}
        return {"success": False, "message": result.stderr.strip()}

    def get_container(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Get container info."""
        if self._client:
            try:
                c = self._client.containers.get(app_id)
                return {
                    "app_id": app_id,
                    "container_id": c.short_id,
                    "status": c.status,
                    "image": str(c.image.tags[0]) if c.image.tags else str(c.image.short_id),
                    "started_at": c.attrs.get("State", {}).get("StartedAt", ""),
                }
            except Exception:
                return None

        result = subprocess.run(
            [self._cmd(), "inspect", "--format",
             "{{.Id}}|{{.State.Status}}|{{.Config.Image}}|{{.State.StartedAt}}",
             app_id],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split("|")
        if len(parts) >= 4:
            return {
                "app_id": app_id,
                "container_id": parts[0][:12],
                "status": parts[1],
                "image": parts[2],
                "started_at": parts[3][:19].replace("T", " ") if parts[3] else None,
            }
        return None

    def list_containers(self) -> List[Dict[str, Any]]:
        """List all running remake-managed containers."""
        if self._client:
            try:
                containers = self._client.containers.list(
                    filters={"label": "remake.managed=true"}
                )
                return [
                    {
                        "app_id": c.labels.get("remake.app_id", c.name),
                        "container_id": c.short_id,
                        "status": c.status,
                        "image": str(c.image.tags[0]) if c.image.tags else str(c.image.short_id),
                        "started_at": c.attrs.get("State", {}).get("StartedAt", ""),
                    }
                    for c in containers
                ]
            except Exception:
                return []

        result = subprocess.run(
            [self._cmd(), "ps", "--format",
             "{{.Names}}|{{.ID}}|{{.Status}}|{{.Image}}",
             "--filter", "label=remake.managed=true"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                containers.append({
                    "app_id": parts[0],
                    "container_id": parts[1][:12],
                    "status": parts[2],
                    "image": parts[3],
                })
        return containers

    def get_logs(self, app_id: str, tail: int = 100) -> Optional[str]:
        """Get container logs."""
        if self._client:
            try:
                container = self._client.containers.get(app_id)
                return container.logs(tail=tail).decode("utf-8", errors="replace")
            except Exception:
                return None

        result = subprocess.run(
            [self._cmd(), "logs", "--tail", str(tail), app_id],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout + result.stderr
        return None

    def cleanup_all(self):
        """Stop all remake-managed containers (for graceful shutdown)."""
        containers = self.list_containers()
        for c in containers:
            app_id = c["app_id"]
            logger.info(f"Stopping {app_id}...")
            self.stop_container(app_id, force=False)
