"""Example: HarnessGate with Telegram.

Install:
    pip install harnessgate

Required env vars:
    ANTHROPIC_API_KEY    — your Anthropic API key
    TELEGRAM_BOT_TOKEN   — your Telegram bot token
"""

import asyncio
import os

from harnessgate import Bridge, BridgeConfig
from harnessgate.providers import ClaudeProvider
from harnessgate.platforms import TelegramAdapter

provider = ClaudeProvider(os.environ["ANTHROPIC_API_KEY"])

bridge = Bridge(provider, BridgeConfig(provider={"type": "claude"}))
bridge.add_platform(TelegramAdapter())


async def resolve_user(sender, _platform, _message):
    return {
        "user_id": sender.id,
        "agent_id": os.environ.get("AGENT_ID", "agent_01XXXX"),
        "environment_id": os.environ.get("ENVIRONMENT_ID", "env_01XXXX"),
    }


bridge.set_user_resolver(resolve_user)


async def main():
    await bridge.connect("telegram", {"botToken": os.environ["TELEGRAM_BOT_TOKEN"]})
    print("HarnessGate running — Telegram bot is listening")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
