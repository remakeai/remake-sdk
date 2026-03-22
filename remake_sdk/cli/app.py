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
@click.pass_context
def launch(ctx, app_id, local, platform, timeout, image):
    """
    Launch an app on the robot.

    By default, sends a launch request to the platform. Use --local
    to launch the app directly using Podman without contacting the
    cloud (useful for offline operation or development).

    \b
    Examples:
        remake app launch com.funrobots.chase-game
        remake app launch com.example.myapp --local
        remake app launch myapp --local --image localhost/myapp:dev
    """
    if local:
        launch_local(app_id, image)
    else:
        launch_via_platform(app_id, platform, timeout)


def launch_local(app_id: str, image: str = None):
    """Launch app locally using Podman."""
    import subprocess

    click.echo(f"Launching app locally: {app_id}")

    # Determine container image
    container_image = image
    if not container_image:
        # Try to get from registry or use convention
        try:
            from ..runtime.app_registry import AppRegistry
            registry = AppRegistry()
            app_info = registry.get(app_id)
            if app_info:
                container_image = app_info.container_image
        except:
            pass

        if not container_image:
            container_image = f"registry.remake.ai/apps/{app_id}:latest"

    click.echo(f"Using container: {container_image}")

    try:
        # Stop existing container if running
        subprocess.run(
            ["podman", "stop", app_id],
            capture_output=True,
            timeout=10
        )
        subprocess.run(
            ["podman", "rm", app_id],
            capture_output=True,
            timeout=10
        )

        # Start container
        click.echo(f"Starting container {app_id}...")
        result = subprocess.run(
            ["podman", "run", "-d", "--rm", "--name", app_id, container_image],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            click.echo(f"Error: {result.stderr.strip()}", err=True)
            sys.exit(1)

        container_id = result.stdout.strip()[:12]
        click.echo(click.style("App launched!", fg="green"))
        click.echo(f"Container ID: {container_id}")
        click.echo()
        click.echo(f"View logs: remake app logs {app_id}")
        click.echo(f"Stop app:  remake app stop {app_id} --local")

    except FileNotFoundError:
        click.echo("Podman is not installed.", err=True)
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
@click.argument("app_id")
@click.option("--local", "-l", is_flag=True, help="Stop locally without contacting platform")
@click.option("--platform", "-p", default=None, help="Platform URL override")
@click.option("--timeout", "-t", default=30, help="Timeout in seconds")
@click.option("--force", "-f", is_flag=True, help="Force stop (kill container)")
@click.pass_context
def stop(ctx, app_id, local, platform, timeout, force):
    """
    Stop a running app on the robot.

    By default, sends a stop request to the platform. Use --local
    to stop the app directly using Podman without contacting the cloud.

    \b
    Examples:
        remake app stop com.funrobots.chase-game
        remake app stop myapp --local
        remake app stop myapp --local --force
    """
    if local:
        stop_local(app_id, force)
    else:
        stop_via_platform(app_id, platform, timeout)


def stop_local(app_id: str, force: bool = False):
    """Stop app locally using Podman."""
    import subprocess

    click.echo(f"Stopping app locally: {app_id}")

    try:
        cmd = ["podman", "kill" if force else "stop", app_id]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            click.echo(click.style("App stopped!", fg="green"))
        elif "no such container" in result.stderr.lower():
            click.echo(f"App {app_id} is not running.")
        else:
            click.echo(f"Error: {result.stderr.strip()}", err=True)
            sys.exit(1)

    except FileNotFoundError:
        click.echo("Podman is not installed.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


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
        # Use subprocess for reliability (Podman SDK has socket issues)
        result = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}|{{.ID}}|{{.Status}}|{{.Image}}"],
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
                apps.append({
                    "app_id": parts[0],
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
            click.echo(f"    Container: {app_info['container_id']}")
            click.echo(f"    Image:     {app_info['image']}")
            click.echo(f"    Status:    {click.style(app_info['status'], fg='green')}")

        click.echo()
        click.echo(f"Total: {len(apps)} app(s) running")
        click.echo()
        click.echo("Commands:")
        click.echo(f"  View logs:  remake app logs <app_id>")
        click.echo(f"  Stop app:   remake app stop <app_id> --local")

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
@click.pass_context
def install(ctx, app_id, version, image):
    """
    Install an app by pulling its container image.

    If runtime is running, uses the runtime API.
    Otherwise, operates directly via Podman.

    \b
    Examples:
        remake app install com.funrobots.chase-game
        remake app install com.funrobots.chase-game --version 1.2.0
        remake app install myapp --image localhost/myapp:dev
    """
    import requests

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
                    "source": "local"
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
            source="local"
        )

        if result.success:
            click.echo(click.style("App installed!", fg="green"))
            click.echo(f"Image: {result.container_image}")
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
