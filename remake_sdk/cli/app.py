"""
App commands: remake app install|uninstall|launch|stop|status|list|logs
"""

import click
import asyncio
import sys
import json

from ..platform import PlatformClient, PlatformConfig, ConnectionState
from ..platform.config import get_robot_credentials, get_platform_url
from ..common.types import AppCommand


@click.group()
@click.pass_context
def app(ctx):
    """
    App management commands.

    \b
    Commands:
        install   - Install an app
        uninstall - Remove an app
        launch    - Launch an app on the robot
        stop      - Stop a running app
        status    - Show running apps
        list      - List installed apps
        logs      - View app logs
    """
    pass


@app.command()
@click.argument("app_id")
@click.option("--local", "-l", is_flag=True, help="Launch locally without contacting platform")
@click.option("--platform", "-p", default=None, help="Platform URL override")
@click.option("--timeout", "-t", default=30, help="Timeout in seconds")
@click.option("--image", default=None, help="Container image override (for --local)")
@click.option("--port", "ports", multiple=True, help="Port mapping (e.g., --port 8080:8080)")
@click.option("--network-host", is_flag=True, help="Use host network (exposes all ports)")
@click.option("--env", "-e", "env_vars", multiple=True, help="Environment variable (e.g., -e KEY=value)")
@click.option("--backend", type=click.Choice(["agent", "podman", "auto"]), default=None,
              help="Container backend (for --local)")
@click.option("--agent-url", default=None, help="Host Agent URL (implies --backend agent)")
@click.pass_context
def launch(ctx, app_id, local, platform, timeout, image, ports, network_host, env_vars, backend, agent_url):
    """
    Launch an app on the robot.

    By default, sends a launch request to the platform. Use --local
    to launch the app directly without contacting the cloud.

    Port mappings are read from the app manifest automatically.
    Use --port to override or --network-host to expose all ports.

    \b
    Examples:
        remake app launch com.funrobots.chase-game
        remake app launch com.example.myapp --local
        remake app launch myapp --local --image localhost/myapp:dev
        remake app launch myapp --local --port 8080:8080
        remake app launch myapp --local --network-host
        remake app launch myapp --local --backend agent
    """
    # --agent-url implies --backend agent
    if agent_url and not backend:
        backend = "agent"

    # Parse environment variables
    env_dict = {}
    for env in env_vars:
        if '=' in env:
            key, value = env.split('=', 1)
            env_dict[key] = value

    # Parse port mappings
    port_list = list(ports) if ports else None

    if local:
        launch_local(app_id, image, ports=port_list, network_host=network_host,
                     env_vars=env_dict, backend=backend, agent_url=agent_url)
    else:
        launch_via_platform(app_id, platform, timeout)


def launch_local(app_id: str, image: str = None, ports: list = None,
                  network_host: bool = False, env_vars: dict = None,
                  backend: str = None, agent_url: str = None):
    """Launch app locally using the configured container backend."""
    from ..runtime.app_manager import AppManager
    from ..runtime.app_registry import AppRegistry

    click.echo(f"Launching app locally: {app_id}")

    # Resolve backend from config if not specified via CLI
    if backend is None:
        try:
            from ..platform.config import load_config
            cfg = load_config()
            backend = cfg.get("runtime", {}).get("backend", "auto")
            if agent_url is None:
                agent_url = cfg.get("runtime", {}).get("agent_url")
        except Exception:
            backend = "auto"

    # Determine container image and get app config from registry
    container_image = image
    app_ports = ports or []
    app_env = env_vars or {}

    try:
        registry = AppRegistry()
        if not container_image:
            app_info = registry.get(app_id)
            if app_info:
                container_image = app_info.container_image
                if not app_ports and app_info.ports:
                    app_ports = app_info.ports
                if app_info.environment:
                    app_env = {**app_info.environment, **app_env}
    except Exception:
        pass

    if not container_image:
        container_image = f"registry.remake.ai/apps/{app_id}:latest"

    click.echo(f"Using container: {container_image}")

    try:
        manager = AppManager(registry=registry, backend=backend, agent_url=agent_url)
        click.echo(f"Backend: {manager.backend_name}")

        # Build port config
        port_config = None
        if not network_host and app_ports:
            port_config = []
            for p in app_ports:
                if hasattr(p, 'container'):
                    port_config.append({"host": p.host, "container": p.container})
                elif isinstance(p, dict):
                    port_config.append({"host": p.get("host", p.get("container")), "container": p["container"]})
                elif isinstance(p, str) and ":" in p:
                    parts = p.split(":")
                    port_config.append({"host": int(parts[0]), "container": int(parts[1])})

        # Build network config
        network = "host" if network_host else None

        click.echo(f"Starting container {app_id}...")
        if port_config:
            port_list = [str(p["host"]) for p in port_config]
            click.echo(f"Exposing ports: {', '.join(port_list)}")

        success, result, message = manager.backend.run(
            app_id=app_id,
            image=container_image,
            ports=port_config,
            environment=app_env or None,
            network=network,
        )

        if not success:
            click.echo(click.style(f"Error: {message or result}", fg="red"), err=True)
            sys.exit(1)

        click.echo(click.style("App launched!", fg="green"))
        click.echo(f"Container ID: {result}")

        if port_config:
            click.echo()
            for p in port_config:
                click.echo(f"  http://localhost:{p['host']}")

        click.echo()
        click.echo(f"View logs: remake app logs {app_id}")
        click.echo(f"Stop app:  remake app stop {app_id}")

    except RuntimeError as e:
        click.echo(click.style(str(e), fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def launch_via_platform(app_id: str, platform: str, timeout: int):
    """Launch app via platform API."""
    robot_id, robot_secret = get_robot_credentials()

    if not robot_id or not robot_secret:
        click.echo("Robot is not paired. Run 'remake pair' first.", err=True)
        click.echo("Or use --local to launch without platform connection.")
        sys.exit(1)

    platform_url = platform or get_platform_url() or "https://api.remake.ai"

    click.echo(f"Launching app: {app_id}")
    click.echo(f"Platform: {platform_url}")
    click.echo()

    async def do_launch():
        config = PlatformConfig(
            platform_url=platform_url,
            robot_id=robot_id,
            robot_secret=robot_secret,
            reconnect=False,
        )

        client = PlatformClient(config)

        @client.on_state_change
        def on_state(state: ConnectionState):
            if state == ConnectionState.AUTHENTICATED:
                click.echo("Connected and authenticated")

        try:
            click.echo("Connecting...")
            connected = await client.connect(timeout=15.0)
            if not connected:
                click.echo("Failed to connect to platform.", err=True)
                return False

            click.echo(f"Requesting launch of {app_id}...")

            import requests
            resp = requests.post(
                f"{platform_url}/api/v2/robots/{robot_id}/apps/{app_id}/launch",
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )

            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    click.echo(click.style("Launch command sent!", fg="green"))
                    click.echo(f"Command ID: {result.get('cmd_id')}")
                    return True
                else:
                    click.echo(click.style(f"Launch failed: {result.get('message')}", fg="red"), err=True)
                    return False
            else:
                click.echo(click.style(f"API error: {resp.status_code}", fg="red"), err=True)
                try:
                    error = resp.json()
                    click.echo(f"  {error.get('message', resp.text)}", err=True)
                except:
                    click.echo(f"  {resp.text}", err=True)
                return False

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            return False
        finally:
            await client.disconnect()

    success = asyncio.run(do_launch())
    if not success:
        sys.exit(1)


@app.command()
@click.argument("app_id", required=False)
@click.option("--local", "-l", is_flag=True, help="Stop locally without contacting platform")
@click.option("--platform", "-p", default=None, help="Platform URL override")
@click.option("--timeout", "-t", default=30, help="Timeout in seconds")
@click.option("--force", "-f", is_flag=True, help="Force stop (kill container)")
@click.option("--all", "-a", "stop_all", is_flag=True, help="Stop all running apps")
@click.option("--backend", type=click.Choice(["agent", "podman", "auto"]), default=None,
              help="Container backend (for --local)")
@click.option("--agent-url", default=None, help="Host Agent URL (implies --backend agent)")
@click.pass_context
def stop(ctx, app_id, local, platform, timeout, force, stop_all, backend, agent_url):
    """
    Stop a running app on the robot.

    If APP_ID is not specified, stops all running apps (or prompts if multiple).
    Auto-detects local mode when robot is not paired with platform.

    \b
    Examples:
        remake app stop                           # Stop all running apps
        remake app stop com.funrobots.chase-game
        remake app stop --all                     # Stop all without prompting
        remake app stop myapp --force             # Force kill
    """
    # Auto-detect local mode:
    # 1. If no APP_ID specified and local containers exist, use local mode
    # 2. If robot not paired with platform, use local mode
    if not local:
        if not app_id:
            # No APP_ID - check if there are local containers to stop
            running = get_running_apps()
            if running:
                local = True
            else:
                click.echo("No apps currently running.")
                return
        else:
            # APP_ID specified - use local mode if not paired
            robot_id, robot_secret = get_robot_credentials()
            if not robot_id or not robot_secret:
                local = True

    # --agent-url implies --backend agent
    if agent_url and not backend:
        backend = "agent"

    if local:
        stop_local(app_id, force, stop_all, backend=backend, agent_url=agent_url)
    else:
        stop_via_platform(app_id, platform, timeout)


def _get_manager(backend: str = None, agent_url: str = None):
    """Create an AppManager with the given backend config."""
    from ..runtime.app_manager import AppManager

    if backend is None:
        try:
            from ..platform.config import load_config
            cfg = load_config()
            backend = cfg.get("runtime", {}).get("backend", "auto")
            if agent_url is None:
                agent_url = cfg.get("runtime", {}).get("agent_url")
        except Exception:
            backend = "auto"

    return AppManager(backend=backend, agent_url=agent_url)


def get_running_apps(backend: str = None, agent_url: str = None):
    """Get list of running app containers."""
    try:
        manager = _get_manager(backend, agent_url)
        return [c.app_id for c in manager.list_running()]
    except Exception:
        return []


def stop_local(app_id: str = None, force: bool = False, stop_all: bool = False,
               backend: str = None, agent_url: str = None):
    """Stop app locally using the configured container backend."""
    # If no app_id specified, find running apps
    if not app_id:
        running = get_running_apps(backend=backend, agent_url=agent_url)

        if not running:
            click.echo("No apps currently running.")
            return

        if len(running) == 1:
            app_id = running[0]
            click.echo(f"Found running app: {app_id}")
        elif stop_all:
            click.echo(f"Stopping {len(running)} app(s)...")
            for name in running:
                _stop_container(name, force, backend=backend, agent_url=agent_url)
            return
        else:
            click.echo("Multiple apps running:")
            for i, name in enumerate(running, 1):
                click.echo(f"  {i}. {name}")
            click.echo()
            click.echo("Specify an APP_ID or use --all to stop all apps.")
            return

    _stop_container(app_id, force, backend=backend, agent_url=agent_url)


def _stop_container(app_id: str, force: bool = False,
                    backend: str = None, agent_url: str = None):
    """Stop a single container."""
    click.echo(f"Stopping: {app_id}")

    try:
        manager = _get_manager(backend, agent_url)
        success, message = manager.stop(app_id, force=force)

        if success:
            click.echo(click.style(f"  Stopped {app_id}", fg="green"))
        else:
            click.echo(f"  Error: {message}", err=True)

    except RuntimeError as e:
        click.echo(click.style(str(e), fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


def stop_via_platform(app_id: str, platform: str, timeout: int):
    """Stop app via platform API."""
    robot_id, robot_secret = get_robot_credentials()

    if not robot_id or not robot_secret:
        click.echo("Robot is not paired. Run 'remake pair' first.", err=True)
        click.echo("Or use --local to stop without platform connection.")
        sys.exit(1)

    platform_url = platform or get_platform_url() or "https://api.remake.ai"

    click.echo(f"Stopping app: {app_id}")

    async def do_stop():
        config = PlatformConfig(
            platform_url=platform_url,
            robot_id=robot_id,
            robot_secret=robot_secret,
            reconnect=False,
        )

        client = PlatformClient(config)

        try:
            connected = await client.connect(timeout=15.0)
            if not connected:
                click.echo("Failed to connect to platform.", err=True)
                return False

            import requests
            resp = requests.post(
                f"{platform_url}/api/v2/robots/{robot_id}/apps/{app_id}/stop",
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )

            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    click.echo(click.style("Stop command sent!", fg="green"))
                    click.echo(f"Command ID: {result.get('cmd_id')}")
                    return True
                else:
                    click.echo(click.style(f"Stop failed: {result.get('message')}", fg="red"), err=True)
                    return False
            else:
                click.echo(click.style(f"API error: {resp.status_code}", fg="red"), err=True)
                return False

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            return False
        finally:
            await client.disconnect()

    success = asyncio.run(do_stop())
    if not success:
        sys.exit(1)


@app.command()
@click.argument("app_id")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--tail", "-n", default=100, help="Number of lines to show")
@click.pass_context
def logs(ctx, app_id, follow, tail):
    """
    View logs from a running app.

    Shows container logs for the specified app.

    \b
    Examples:
        remake app logs com.funrobots.chase-game
        remake app logs myapp --follow
        remake app logs myapp --tail 50
    """
    import subprocess

    try:
        cmd = ["podman", "logs", "--tail", str(tail)]
        if follow:
            cmd.append("-f")
        cmd.append(app_id)

        if follow:
            click.echo(f"Following logs for {app_id}... (Ctrl+C to exit)")
            click.echo("-" * 40)
            # Run interactively for follow mode
            subprocess.run(cmd)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                if "no such container" in result.stderr.lower():
                    click.echo(f"App {app_id} not found.", err=True)
                else:
                    click.echo(f"Error: {result.stderr.strip()}", err=True)
                sys.exit(1)
            click.echo(result.stdout)

    except KeyboardInterrupt:
        click.echo("\nStopped following logs.")
    except FileNotFoundError:
        click.echo("Podman is not installed.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status(ctx, as_json):
    """
    Show currently running app(s).

    Displays the status of app containers currently running on the robot.

    \b
    Examples:
        remake app status
        remake app status --json
    """
    import subprocess

    try:
        # Get container info including labels for full APP_ID
        result = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}|{{.ID}}|{{.Status}}|{{.Image}}|{{.Labels}}"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            click.echo(f"Podman error: {result.stderr}", err=True)
            sys.exit(1)

        apps = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                container_name = parts[0]
                labels = parts[4] if len(parts) > 4 else ""

                # Extract APP_ID from label if present, otherwise use container name
                app_id = container_name
                if "remake.app_id=" in labels:
                    for label in labels.split(","):
                        if label.startswith("remake.app_id="):
                            app_id = label.split("=", 1)[1]
                            break

                apps.append({
                    "app_id": app_id,
                    "container_name": container_name,
                    "container_id": parts[1][:12],
                    "status": parts[2],
                    "image": parts[3],
                })

        if as_json:
            click.echo(json.dumps({"running": apps, "count": len(apps)}, indent=2))
            return

        if not apps:
            click.echo("No apps currently running.")
            return

        click.echo("Running Apps")
        click.echo("=" * 70)

        for app_info in apps:
            click.echo()
            click.echo(f"  {click.style(app_info['app_id'], bold=True)}")
            click.echo(f"    Container: {app_info['container_id']} ({app_info['container_name']})")
            click.echo(f"    Image:     {app_info['image']}")
            click.echo(f"    Status:    {click.style(app_info['status'], fg='green')}")

        click.echo()
        click.echo(f"Total: {len(apps)} app(s) running")
        click.echo()
        click.echo("Commands:")
        click.echo(f"  View logs:  remake app logs <app_id>")
        click.echo(f"  Stop app:   remake app stop [app_id]")

    except FileNotFoundError:
        click.echo("Podman is not installed.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command("list")
@click.option("--local", "-l", is_flag=True, help="List locally running apps (via Podman)")
@click.option("--platform", "-p", default=None, help="Platform URL override")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def list_apps(ctx, local, platform, as_json):
    """
    List apps on the robot.

    By default, queries the platform for installed apps.
    Use --local to list currently running containers.

    \b
    Examples:
        remake app list
        remake app list --local
        remake app list --json
    """
    if local:
        list_local_apps(as_json)
    else:
        list_platform_apps(platform, as_json)


def list_local_apps(as_json: bool):
    """List locally installed apps from registry."""
    # First, try to get from app registry
    try:
        from ..runtime.app_registry import AppRegistry
        registry = AppRegistry()
        installed = registry.list_all()

        if as_json:
            click.echo(json.dumps({"apps": [app.to_dict() for app in installed]}, indent=2))
            return

        if not installed:
            click.echo("No apps installed locally.")
            click.echo()
            click.echo("Install an app with:")
            click.echo("  remake app install <app-id>")
            return

        click.echo("Locally Installed Apps")
        click.echo("=" * 70)

        for app in installed:
            click.echo()
            click.echo(f"  {click.style(app.app_id, bold=True)}")
            click.echo(f"    Version:  {app.version}")
            click.echo(f"    Image:    {app.container_image}")
            click.echo(f"    Source:   {app.source}")
            if app.ports:
                port_strs = [str(p.host) if hasattr(p, 'host') else str(p.get('host')) for p in app.ports]
                click.echo(f"    Ports:    {', '.join(port_strs)}")
            click.echo(f"    Installed: {app.installed_at[:19] if app.installed_at else 'unknown'}")

        click.echo()
        click.echo(f"Total: {len(installed)} app(s) installed")

    except Exception as e:
        click.echo(f"Error reading app registry: {e}", err=True)
        sys.exit(1)


def list_platform_apps(platform: str, as_json: bool):
    """List apps from platform."""
    robot_id, robot_secret = get_robot_credentials()

    if not robot_id or not robot_secret:
        click.echo("Robot is not paired. Run 'remake pair' first.", err=True)
        click.echo("Or use --local to list running containers.")
        sys.exit(1)

    platform_url = platform or get_platform_url() or "https://api.remake.ai"

    import requests

    try:
        resp = requests.get(
            f"{platform_url}/api/v2/robots/{robot_id}/apps",
            timeout=30
        )

        if resp.status_code != 200:
            click.echo(f"API error: {resp.status_code}", err=True)
            sys.exit(1)

        data = resp.json()

        if as_json:
            click.echo(json.dumps(data, indent=2))
            return

        apps = data.get("apps", [])

        if not apps:
            click.echo("No apps installed.")
            return

        click.echo("Installed Apps")
        click.echo("=" * 60)

        for app in apps:
            click.echo()
            click.echo(f"  {click.style(app['app_id'], bold=True)}")
            if app.get('name'):
                click.echo(f"    Name:      {app['name']}")
            if app.get('version'):
                click.echo(f"    Version:   {app['version']}")
            if app.get('container_image'):
                click.echo(f"    Container: {app['container_image']}")

        click.echo()
        click.echo(f"Total: {len(apps)} app(s)")

    except requests.RequestException as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# Runtime API URL
RUNTIME_API_URL = "http://127.0.0.1:8787"


def is_runtime_running() -> bool:
    """Check if runtime is running."""
    import requests
    try:
        resp = requests.get(f"{RUNTIME_API_URL}/health", timeout=1)
        return resp.status_code == 200
    except:
        return False


@app.command()
@click.argument("app_id")
@click.option("--version", "-v", default="latest", help="App version (default: latest)")
@click.option("--image", default=None, help="Container image URL (overrides default registry)")
@click.option("--manifest", "-m", default=None, type=click.Path(exists=True), help="Path to manifest.json file")
@click.pass_context
def install(ctx, app_id, version, image, manifest):
    """
    Install an app by pulling its container image.

    If runtime is running, uses the runtime API.
    Otherwise, operates directly via Podman.

    Use --manifest to specify a manifest.json file containing
    port mappings, environment variables, and other settings.

    \b
    Examples:
        remake app install com.funrobots.chase-game
        remake app install com.funrobots.chase-game --version 1.2.0
        remake app install myapp --image localhost/myapp:dev
        remake app install myapp --image localhost/myapp:dev --manifest ./manifest.json
    """
    import requests

    # Load manifest if provided
    manifest_data = None
    if manifest:
        try:
            with open(manifest) as f:
                manifest_data = json.load(f)
            click.echo(f"Loaded manifest from {manifest}")
            # Use manifest values as defaults
            if not version or version == "latest":
                version = manifest_data.get("version", version)
        except Exception as e:
            click.echo(f"Warning: Could not load manifest: {e}", err=True)

    click.echo(f"Installing app: {app_id}")
    if version != "latest":
        click.echo(f"Version: {version}")

    # Try runtime API first
    if is_runtime_running():
        click.echo("Using runtime API...")
        try:
            resp = requests.post(
                f"{RUNTIME_API_URL}/apps/install",
                json={
                    "app_id": app_id,
                    "version": version,
                    "container_image": image,
                    "source": "local",
                    "manifest": manifest_data,
                },
                timeout=300  # 5 min for large images
            )

            result = resp.json()
            if result.get("success"):
                click.echo(click.style("App installed!", fg="green"))
                click.echo(f"Image: {result.get('container_image')}")
            else:
                click.echo(click.style(f"Install failed: {result.get('message')}", fg="red"), err=True)
                sys.exit(1)
            return

        except requests.RequestException as e:
            click.echo(f"Runtime API error: {e}", err=True)
            click.echo("Falling back to direct installation...")

    # Direct installation via AppManager
    click.echo("Installing directly via Podman...")

    try:
        from ..runtime.app_manager import AppManager

        manager = AppManager()
        result = manager.install(
            app_id=app_id,
            version=version,
            container_image=image,
            source="local",
            manifest=manifest_data,
        )

        if result.success:
            click.echo(click.style("App installed!", fg="green"))
            click.echo(f"Image: {result.container_image}")
            if manifest_data and manifest_data.get("ports"):
                click.echo(f"Ports: {', '.join(str(p.get('host', p.get('container'))) for p in manifest_data['ports'])}")
        else:
            click.echo(click.style(f"Install failed: {result.message}", fg="red"), err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command()
@click.argument("app_id")
@click.option("--keep-image", is_flag=True, help="Keep the container image")
@click.pass_context
def uninstall(ctx, app_id, keep_image):
    """
    Uninstall an app.

    Removes the app from registry and optionally removes the container image.

    \b
    Examples:
        remake app uninstall com.funrobots.chase-game
        remake app uninstall com.funrobots.chase-game --keep-image
    """
    import requests

    click.echo(f"Uninstalling app: {app_id}")

    # Try runtime API first
    if is_runtime_running():
        click.echo("Using runtime API...")
        try:
            resp = requests.delete(
                f"{RUNTIME_API_URL}/apps/{app_id}",
                timeout=60
            )

            result = resp.json()
            if result.get("success"):
                click.echo(click.style("App uninstalled!", fg="green"))
            else:
                click.echo(click.style(f"Uninstall failed: {result.get('message')}", fg="red"), err=True)
                sys.exit(1)
            return

        except requests.RequestException as e:
            click.echo(f"Runtime API error: {e}", err=True)
            click.echo("Falling back to direct uninstallation...")

    # Direct uninstallation via AppManager
    click.echo("Uninstalling directly...")

    try:
        from ..runtime.app_manager import AppManager

        manager = AppManager()
        result = manager.uninstall(app_id, remove_image=not keep_image)

        if result.success:
            click.echo(click.style("App uninstalled!", fg="green"))
        else:
            click.echo(click.style(f"Uninstall failed: {result.message}", fg="red"), err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# Valid capability names that apps can request
VALID_CAPABILITIES = {
    "movement",
    "navigation",
    "camera",
    "audio_playback",
    "audio_capture",
    "sensors",
    "mapping",
    "localization",
    "network",
    "storage",
}

# Patterns that might indicate secrets
SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[a-zA-Z0-9]{16,}',
    r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']?[^\s"\']{8,}',
    r'(?i)(aws[_-]?access|aws[_-]?secret)',
    r'(?i)(private[_-]?key|priv[_-]?key)',
    r'(?i)bearer\s+[a-zA-Z0-9\-_.]+',
]

# Files that commonly contain secrets
SECRET_FILES = [
    '.env',
    '.env.local',
    '.env.production',
    'credentials.json',
    'secrets.json',
    'config.secret.json',
    '*.pem',
    '*.key',
    'id_rsa',
    'id_ed25519',
]


@app.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--fix", is_flag=True, help="Auto-fix simple issues (not yet implemented)")
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
@click.pass_context
def lint(ctx, path, fix, strict):
    """
    Validate app manifest and structure.

    Checks manifest.json, Dockerfile, capabilities, and file structure.
    Can lint a directory (app source).

    \b
    Examples:
        remake app lint ./my-app/
        remake app lint .
        remake app lint --strict
    """
    import os
    import re
    from pathlib import Path

    app_path = Path(path).resolve()

    click.echo(f"Linting app: {app_path}")
    click.echo()

    errors = []
    warnings = []

    def error(msg):
        errors.append(msg)
        click.echo(click.style(f"  ERROR: {msg}", fg="red"))

    def warn(msg):
        warnings.append(msg)
        click.echo(click.style(f"  WARN:  {msg}", fg="yellow"))

    def ok(msg):
        click.echo(click.style(f"  OK:    {msg}", fg="green"))

    def info(msg):
        click.echo(f"  INFO:  {msg}")

    # 1. Check manifest.json
    click.echo("Checking manifest.json...")
    manifest_path = app_path / "manifest.json"
    manifest = None

    if not manifest_path.exists():
        error("manifest.json not found")
    else:
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            ok("manifest.json is valid JSON")
        except json.JSONDecodeError as e:
            error(f"manifest.json is invalid JSON: {e}")

    # 2. Validate manifest fields
    if manifest:
        click.echo("Checking manifest fields...")

        # Required fields (id or app_id accepted)
        if "id" not in manifest and "app_id" not in manifest:
            error("Missing required field: id (or app_id)")
        else:
            ok(f"Has required field: {'id' if 'id' in manifest else 'app_id'}")

        for field in ["name", "version"]:
            if field not in manifest:
                error(f"Missing required field: {field}")
            else:
                ok(f"Has required field: {field}")

        # Validate app ID format
        app_id = manifest.get("id") or manifest.get("app_id", "")
        if app_id:
            if not re.match(r'^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$', app_id):
                warn(f"App ID '{app_id}' should be reverse-domain format (e.g., com.example.myapp)")
            else:
                ok(f"App ID format valid: {app_id}")

        # Validate version format
        version = manifest.get("version", "")
        if version:
            if not re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$', version):
                warn(f"Version '{version}' should be semver format (e.g., 1.0.0)")
            else:
                ok(f"Version format valid: {version}")

        # Validate capabilities
        capabilities = manifest.get("capabilities", [])
        if capabilities:
            click.echo("Checking capabilities...")
            for cap in capabilities:
                if cap in VALID_CAPABILITIES:
                    ok(f"Valid capability: {cap}")
                else:
                    warn(f"Unknown capability: {cap} (valid: {', '.join(sorted(VALID_CAPABILITIES))})")

        # Validate ports
        ports = manifest.get("ports", [])
        if ports:
            click.echo("Checking port mappings...")
            for port in ports:
                container_port = port.get("container")
                host_port = port.get("host", container_port)

                if not container_port:
                    error("Port mapping missing 'container' field")
                elif not isinstance(container_port, int) or container_port < 1 or container_port > 65535:
                    error(f"Invalid container port: {container_port}")
                elif host_port and (not isinstance(host_port, int) or host_port < 1 or host_port > 65535):
                    error(f"Invalid host port: {host_port}")
                else:
                    ok(f"Port mapping: {host_port}:{container_port}")

                # Warn about privileged ports
                if host_port and host_port < 1024:
                    warn(f"Port {host_port} is privileged (requires root)")

    # 3. Check Dockerfile
    click.echo("Checking Dockerfile...")
    dockerfile_path = app_path / "Dockerfile"

    if not dockerfile_path.exists():
        error("Dockerfile not found")
    else:
        ok("Dockerfile present")

        # Check Dockerfile contents
        with open(dockerfile_path) as f:
            dockerfile = f.read()

        # Check for EXPOSE
        if manifest and manifest.get("ports"):
            for port in manifest["ports"]:
                container_port = port.get("container")
                if container_port and f"EXPOSE {container_port}" not in dockerfile:
                    warn(f"Dockerfile should EXPOSE {container_port} (declared in manifest)")

        # Check for CMD or ENTRYPOINT
        if "CMD " not in dockerfile and "ENTRYPOINT " not in dockerfile:
            warn("Dockerfile has no CMD or ENTRYPOINT")
        else:
            ok("Dockerfile has CMD or ENTRYPOINT")

    # 4. Check for app entry point
    click.echo("Checking app structure...")
    entry_points = ["app.py", "main.py", "src/main.py", "src/app.py"]
    found_entry = None
    for entry in entry_points:
        if (app_path / entry).exists():
            found_entry = entry
            break

    if found_entry:
        ok(f"Entry point found: {found_entry}")
    else:
        info("No standard entry point (app.py, main.py) - check Dockerfile CMD")

    # 5. Check for secrets
    click.echo("Checking for secrets...")
    secrets_found = False

    # Check for secret files
    for pattern in SECRET_FILES:
        if '*' in pattern:
            matches = list(app_path.glob(pattern))
        else:
            matches = [app_path / pattern] if (app_path / pattern).exists() else []

        for match in matches:
            if match.exists():
                warn(f"Potential secret file: {match.name} (should not be in container)")
                secrets_found = True

    # Check .dockerignore
    dockerignore_path = app_path / ".dockerignore"
    if dockerignore_path.exists():
        ok(".dockerignore present")
        with open(dockerignore_path) as f:
            dockerignore = f.read()
        if ".env" not in dockerignore:
            warn(".dockerignore should exclude .env files")
    else:
        warn("No .dockerignore file (secrets might leak into image)")

    # Scan Python files for hardcoded secrets
    for py_file in app_path.glob("**/*.py"):
        if ".venv" in str(py_file) or "node_modules" in str(py_file):
            continue
        try:
            with open(py_file) as f:
                content = f.read()
            for pattern in SECRET_PATTERNS:
                if re.search(pattern, content):
                    warn(f"Potential hardcoded secret in {py_file.relative_to(app_path)}")
                    secrets_found = True
                    break
        except Exception:
            pass

    if not secrets_found:
        ok("No obvious secrets found")

    # 6. Check README
    click.echo("Checking documentation...")
    readme_files = ["README.md", "README.txt", "README"]
    has_readme = any((app_path / r).exists() for r in readme_files)
    if has_readme:
        ok("README present")
    else:
        info("No README file (optional but recommended)")

    # Summary
    click.echo()
    click.echo("=" * 50)

    if errors:
        click.echo(click.style(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)", fg="red", bold=True))
        sys.exit(1)
    elif warnings and strict:
        click.echo(click.style(f"FAILED (strict): {len(warnings)} warning(s)", fg="yellow", bold=True))
        sys.exit(1)
    elif warnings:
        click.echo(click.style(f"PASSED with {len(warnings)} warning(s)", fg="yellow", bold=True))
    else:
        click.echo(click.style("PASSED: All checks passed", fg="green", bold=True))


@app.command()
@click.argument("app_id")
@click.option("--url-only", is_flag=True, help="Show URL without opening browser")
@click.option("--port", "-p", type=int, default=None, help="Specify port (if app exposes multiple)")
@click.pass_context
def ui(ctx, app_id, url_only, port):
    """
    Open app's web UI in browser.

    Finds the app's exposed port and opens the web interface.
    If the app exposes multiple ports, use --port to specify which one.

    \b
    Examples:
        remake app ui com.example.app-dashboard
        remake app ui com.example.app-dashboard --url-only
        remake app ui myapp --port 8080
    """
    import subprocess
    import webbrowser

    # First check if app is running
    running_apps = get_running_apps()

    # Find matching app (exact match or partial)
    matching = None
    for name in running_apps:
        if name == app_id or app_id in name:
            matching = name
            break

    if not matching:
        click.echo(f"App '{app_id}' is not running.", err=True)
        click.echo()
        click.echo("Running apps:")
        if running_apps:
            for name in running_apps:
                click.echo(f"  - {name}")
        else:
            click.echo("  (none)")
        sys.exit(1)

    # Get port info
    app_port = port
    port_description = None

    if not app_port:
        # Try to get port from registry
        try:
            from ..runtime.app_registry import AppRegistry
            registry = AppRegistry()
            app_info = registry.get(matching)
            if app_info and app_info.ports:
                if len(app_info.ports) == 1:
                    p = app_info.ports[0]
                    app_port = p.host if hasattr(p, 'host') else p.get('host')
                    port_description = p.description if hasattr(p, 'description') else p.get('description')
                elif len(app_info.ports) > 1:
                    click.echo("App exposes multiple ports:")
                    for p in app_info.ports:
                        host_port = p.host if hasattr(p, 'host') else p.get('host')
                        desc = p.description if hasattr(p, 'description') else p.get('description', '')
                        click.echo(f"  - {host_port}: {desc}" if desc else f"  - {host_port}")
                    click.echo()
                    click.echo("Use --port to specify which one.")
                    sys.exit(1)
        except Exception:
            pass

    if not app_port:
        # Try to get from container port bindings
        try:
            result = subprocess.run(
                ["podman", "inspect", matching, "--format", "{{json .HostConfig.PortBindings}}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                import json as json_module
                bindings = json_module.loads(result.stdout.strip())
                if bindings:
                    # Get first port
                    for container_port, host_bindings in bindings.items():
                        if host_bindings:
                            app_port = int(host_bindings[0].get('HostPort', 0))
                            if app_port:
                                break
        except Exception:
            pass

    if not app_port:
        # Try common ports
        common_ports = [8080, 3000, 5000, 80, 443]
        click.echo("No port information found. Trying common ports...")

        import socket
        for test_port in common_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex(('localhost', test_port))
                sock.close()
                if result == 0:
                    app_port = test_port
                    click.echo(f"Found open port: {app_port}")
                    break
            except Exception:
                pass

    if not app_port:
        click.echo("Could not determine app's web port.", err=True)
        click.echo()
        click.echo("Specify the port manually:")
        click.echo(f"  remake app ui {app_id} --port 8080")
        sys.exit(1)

    # Build URL
    url = f"http://localhost:{app_port}"

    if url_only:
        click.echo(url)
    else:
        if port_description:
            click.echo(f"Opening {port_description}...")
        else:
            click.echo(f"Opening {url}...")

        try:
            webbrowser.open(url)
            click.echo(click.style(f"Opened {url} in browser", fg="green"))
        except Exception as e:
            click.echo(f"Could not open browser: {e}", err=True)
            click.echo(f"Open manually: {url}")
            sys.exit(1)
