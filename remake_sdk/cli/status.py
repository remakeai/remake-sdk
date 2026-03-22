"""
Status command: remake status
"""

import click
import json

from ..platform.config import (
    get_robot_credentials,
    get_platform_url,
    load_config,
)


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status(ctx, as_json):
    """
    Show robot and platform connection status.

    Displays the current pairing status, credentials, and configuration.

    \b
    Examples:
        remake status
        remake status --json
    """
    robot_id, robot_secret = get_robot_credentials()
    platform_url = get_platform_url() or "https://api.remake.ai"
    config = load_config()

    status_data = {
        "paired": bool(robot_id and robot_secret),
        "robot_id": robot_id,
        "platform_url": platform_url,
        "config_file": config.get("_config_file", "~/.config/remake/config.yml"),
    }

    if as_json:
        click.echo(json.dumps(status_data, indent=2))
        return

    click.echo("Remake Robot Status")
    click.echo("=" * 40)
    click.echo()

    if robot_id:
        click.echo(f"  Robot ID:     {robot_id}")
        click.echo(f"  Platform:     {platform_url}")
        click.echo(f"  Paired:       {click.style('Yes', fg='green')}")

        if robot_secret:
            # Show partial secret for debugging
            click.echo(f"  Credentials:  {click.style('Configured', fg='green')}")
        else:
            click.echo(f"  Credentials:  {click.style('Missing secret', fg='red')}")
    else:
        click.echo(f"  Paired:       {click.style('No', fg='yellow')}")
        click.echo(f"  Platform:     {platform_url}")
        click.echo()
        click.echo("  Run 'remake pair' to pair with the platform.")

    click.echo()
