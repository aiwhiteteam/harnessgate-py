"""Example: HarnessGate with Web UI.

Install:
    pip install harnessgate

Required env vars:
    ANTHROPIC_API_KEY — your Anthropic API key
"""

import asyncio
import os

from harnessgate import Bridge, BridgeConfig
from harnessgate.providers import ClaudeProvider
from harnessgate.platforms import WebAdapter

provider = ClaudeProvider(os.environ["ANTHROPIC_API_KEY"])

config = BridgeConfig(
    provider={"type": "claude"},
    platforms={"web": {"port": 3000}},
)

bridge = Bridge(provider, config)


async def resolve_user(sender, _platform, _message):
    return {
        "user_id": sender.id,
        "agent_id": os.environ.get("AGENT_ID", "agent_01XXXX"),
        "environment_id": os.environ.get("ENVIRONMENT_ID", "env_01XXXX"),
    }


bridge.set_user_resolver(resolve_user)
bridge.add_platform(WebAdapter())


async def main():
    await bridge.start()
    print("HarnessGate running — open http://localhost:3000")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
