"""
Remake Host Agent - Manages app containers on the host.

The Host Agent runs outside the robot container and handles
container lifecycle on behalf of the robot's SDK/CLI.

Usage:
    python -m remake_agent
    python -m remake_agent --port 8785
    python -m remake_agent --config ~/.remake/agent.yml
"""

__version__ = "0.1.0"
