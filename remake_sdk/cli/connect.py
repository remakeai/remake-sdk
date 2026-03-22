"""
Connect command: remake connect
"""

import click
import asyncio
import signal
import sys

from ..platform import PlatformClient, PlatformConfig, ConnectionState
from ..platform.config import get_robot_credentials, get_platform_url
from ..common.types import AppCommand


@click.command()
@click.option("--platform", "-p", default=None, help="Platform URL override")
@click.option("--foreground/--background", default=True, help="Run in foreground (default) or background")
@click.pass_context
def connect(ctx, platform, foreground):
    """
    Connect to the platform and listen for commands.

    This command connects the robot to the Remake.ai platform using
    stored credentials and waits for app commands (launch, stop, etc.).

    Press Ctrl+C to disconnect.

    \b
    Examples:
        remake connect
        remake connect --platform https://staging.remake.ai
    """
    robot_id, robot_secret = get_robot_credentials()

    if not robot_id or not robot_secret:
        click.echo("Robot is not paired. Run 'remake pair' first.", err=True)
        sys.exit(1)

    platform_url = platform or get_platform_url() or "https://api.remake.ai"

    click.echo(f"Connecting to {platform_url}...")
    click.echo(f"Robot ID: {robot_id}")
    click.echo()

    async def run_client():
        config = PlatformConfig(
            platform_url=platform_url,
            robot_id=robot_id,
            robot_secret=robot_secret,
            reconnect=True,
            reconnect_delay=1.0,
            reconnect_max_delay=30.0,
        )

        client = PlatformClient(config)

        @client.on_state_change
        def on_state(state: ConnectionState):
            if state == ConnectionState.CONNECTING:
                click.echo("Connecting...")
            elif state == ConnectionState.CONNECTED:
                click.echo("Connected to server")
            elif state == ConnectionState.AUTHENTICATING:
                click.echo("Authenticating...")
            elif state == ConnectionState.AUTHENTICATED:
                click.echo(click.style("Authenticated!", fg="green"))
                click.echo()
                click.echo("Listening for commands. Press Ctrl+C to disconnect.")
                click.echo("-" * 40)
            elif state == ConnectionState.RECONNECTING:
                click.echo("Reconnecting...")
            elif state == ConnectionState.DISCONNECTED:
                click.echo("Disconnected")
            elif state == ConnectionState.ERROR:
                click.echo(click.style("Connection error", fg="red"))

        @client.on_app_command
        def on_command(cmd: AppCommand):
            click.echo()
            click.echo(click.style(f"[Command] {cmd.action.upper()}", fg="cyan", bold=True))
            click.echo(f"  App ID:    {cmd.app_id}")
            if cmd.cmd_id:
                click.echo(f"  Cmd ID:    {cmd.cmd_id}")
            if cmd.container_image:
                click.echo(f"  Container: {cmd.container_image}")
            if cmd.entitlements:
                click.echo(f"  Entitlements: {', '.join(cmd.entitlements)}")

            # In a real implementation, this would trigger the Podman SDK
            # to actually launch/stop the container
            click.echo()

            # Send acknowledgment response
            asyncio.create_task(send_response(client, cmd))

        async def send_response(client, cmd: AppCommand):
            """Send response back to platform."""
            try:
                if cmd.action == "launch":
                    await client._sio.emit("launch_app_response", {
                        "cmd_id": cmd.cmd_id,
                        "success": True,
                    }, namespace="/robot-control")
                    click.echo(f"  -> Sent launch response (success)")
                elif cmd.action == "stop":
                    await client._sio.emit("stop_app_response", {
                        "cmd_id": cmd.cmd_id,
                        "success": True,
                    }, namespace="/robot-control")
                    click.echo(f"  -> Sent stop response (success)")
            except Exception as e:
                click.echo(f"  -> Failed to send response: {e}", err=True)

        # Handle shutdown
        shutdown_event = asyncio.Event()

        def handle_signal():
            click.echo("\nShutting down...")
            shutdown_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            connected = await client.connect(timeout=15.0)
            if not connected:
                click.echo("Failed to connect.", err=True)
                return False

            # Run until shutdown
            await shutdown_event.wait()

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            return False
        finally:
            await client.disconnect()
            click.echo("Disconnected.")

        return True

    try:
        success = asyncio.run(run_client())
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nInterrupted.")
