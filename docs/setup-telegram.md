# Telegram Setup

## Prerequisites

- A Telegram account
- Your HarnessGate project set up with `harnessgate` installed

## 1. Create a Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Choose a display name (e.g., "My AI Assistant")
4. Choose a username ending in `bot` (e.g., `my_ai_assistant_bot`)
5. BotFather replies with your **bot token** — save it

Optional settings via BotFather:
- `/setdescription` — what users see before starting a chat
- `/setabouttext` — shown in the bot's profile
- `/setuserpic` — bot avatar
- `/setcommands` — slash commands users see in the menu

## 2. Configure Group Privacy (if needed)

By default, bots only receive messages that mention them or start with `/` in groups. To receive all messages:

1. Message @BotFather
2. Send `/setprivacy`
3. Select your bot
4. Choose **Disable**

## 3. Connect to HarnessGate

```python
import asyncio
import os
from harnessgate import Bridge, TelegramAdapter
from harnessgate.providers import ClaudeProvider

provider = ClaudeProvider(os.environ["ANTHROPIC_API_KEY"])
bridge = Bridge(provider)

async def resolve_user(sender, platform, message):
    return {
        "user_id": sender.id,
        "agent_id": "your-agent-id",
        "environment_id": "your-env-id",
    }

bridge.set_user_resolver(resolve_user)

bridge.add_platform(TelegramAdapter())

async def main():
    # Single bot
    await bridge.start({"telegram": {"botToken": os.environ["TELEGRAM_BOT_TOKEN"]}})

    # Or multi-instance: connect additional bots dynamically
    telegram = TelegramAdapter()
    bridge.add_platform(telegram)
    app_id = await telegram.connect({"botToken": "another-bot-token"}, ctx)

asyncio.run(main())
```

## 4. Test

1. Open Telegram and search for your bot's username
2. Click **Start**
3. Send a message — you should get a response from your agent

## SaaS Distribution

Telegram bots are globally accessible — anyone can message them by username. For a SaaS product:

- **Single shared bot**: All users message the same bot. Use `UserResolver` to route users to different agents or apply per-user auth.
- **Per-customer bots**: Each customer creates their own bot via BotFather and provides the token. Use `connect()` to register multiple bots at runtime.

There is no app store or approval process. Bots are public by default.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
