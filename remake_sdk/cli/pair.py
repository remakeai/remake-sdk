"""
Pairing commands: remake pair, remake unpair
"""

import click
import asyncio
import sys

from ..platform import PairingClient, PairingStatus
from ..platform.config import (
    PlatformConfig,
    save_config,
    load_config,
    set_robot_credentials,
    clear_credentials,
    get_robot_credentials,
    get_platform_url,
)


@click.command()
@click.option(
    "--email", "-e",
    prompt="User email",
    help="Email address of the Remake.ai account to pair with"
)
@click.option(
    "--name", "-n",
    default="Robot",
    help="Display name for this robot"
)
@click.option(
    "--platform", "-p",
    default=None,
    help="Platform URL (default: https://api.remake.ai)"
)
@click.option(
    "--timeout", "-t",
    default=300,
    help="Timeout in seconds to wait for approval (default: 300)"
)
@click.pass_context
def pair(ctx, email, name, platform, timeout):
    """
    Pair this robot with the Remake.ai platform.

    Sends a pairing request to the specified user's account.
    The user must approve the request in the Remake.ai app or web UI.

    \b
    Examples:
        remake pair --email user@example.com
        remake pair --email user@example.com --name "Kitchen Robot"
        remake pair --email user@example.com --platform https://staging.remake.ai
    """
    # Check if already paired
    existing = get_robot_credentials()
    if existing[0] and existing[1]:
        click.echo(f"Already paired as robot: {existing[0]}")
        if not click.confirm("Re-pair with new credentials?"):
            return

    # Determine platform URL
    platform_url = platform or get_platform_url() or "https://api.remake.ai"

    click.echo(f"Platform: {platform_url}")
    click.echo(f"Robot name: {name}")
    click.echo()

    async def do_pair():
        def on_status(status: PairingStatus, message: str):
            if status == PairingStatus.PENDING:
                click.echo("Waiting for approval...")
                click.echo("Please approve this robot in the Remake.ai app or web UI.")
            elif status == PairingStatus.PAIRED:
                click.echo("Pairing approved!")
            elif status == PairingStatus.REJECTED:
                click.echo("Pairing was rejected by user.", err=True)

        try:
            async with PairingClient(platform_url, on_status_change=on_status) as client:
                click.echo("Connecting to platform...")

                result = await client.request_pairing(
                    user_email=email,
                    robot_name=name,
                    timeout=timeout
                )

                if result.success:
                    # Save credentials
                    set_robot_credentials(result.robot_id, result.robot_secret)

                    # Also save platform URL if custom
                    if platform:
                        config = load_config()
                        config["platform_url"] = platform_url
                        save_config(config)

                    click.echo()
                    click.echo(click.style("Pairing successful!", fg="green", bold=True))
                    click.echo(f"Robot ID: {result.robot_id}")
                    click.echo()
                    click.echo("You can now use 'remake connect' to connect to the platform.")
                    return True
                else:
                    click.echo()
                    click.echo(click.style(f"Pairing failed: {result.message}", fg="red"), err=True)
                    return False

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            return False

    success = asyncio.run(do_pair())
    if not success:
        sys.exit(1)


@click.command()
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.option("--local-only", is_flag=True, help="Only clear local credentials (don't notify platform)")
@click.option("--platform", "-p", default=None, help="Platform URL override")
@click.pass_context
def unpair(ctx, force, local_only, platform):
    """
    Remove pairing with the Remake.ai platform.

    By default, this notifies the platform to delete the robot record,
    then clears local credentials. Use --local-only to only clear
    local credentials without notifying the platform.

    \b
    Examples:
        remake unpair
        remake unpair --force
        remake unpair --local-only  # Offline mode
    """
    robot_id, robot_secret = get_robot_credentials()

    if not robot_id:
        click.echo("Robot is not paired.")
        return

    click.echo(f"Current robot ID: {robot_id}")

    if not force:
        if not click.confirm("Remove pairing credentials?"):
            click.echo("Cancelled.")
            return

    # Notify platform (unless local-only)
    if not local_only and robot_secret:
        platform_url = platform or get_platform_url() or "https://api.remake.ai"
        click.echo(f"Notifying platform ({platform_url})...")

        try:
            import requests
            resp = requests.delete(
                f"{platform_url}/api/cli/unpair",
                json={"robot_id": robot_id},
                timeout=30
            )
            if resp.status_code == 200:
                click.echo("Platform notified - robot record deleted.")
            elif resp.status_code == 404:
                click.echo("Robot not found on platform (may already be removed).")
            else:
                click.echo(f"Warning: Platform returned {resp.status_code}", err=True)
        except Exception as e:
            click.echo(f"Warning: Could not notify platform: {e}", err=True)
            click.echo("Continuing with local credential removal...")

    clear_credentials()
    click.echo(click.style("Pairing removed.", fg="yellow"))
    click.echo("Use 'remake pair' to pair with a new account.")
