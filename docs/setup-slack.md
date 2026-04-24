# Slack Setup

## Prerequisites

- A Slack workspace where you're an admin (or can request app approval)
- Your HarnessGate project set up with `harnessgate` installed

## 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name your app and select a workspace → **Create App**

## 2. Enable Socket Mode

Socket Mode lets your bot connect via WebSocket (no public URL needed):

1. Go to **Settings** → **Socket Mode** → toggle **Enable Socket Mode**
2. Create an **App-Level Token** with `connections:write` scope → copy it (this is your `appToken`)

## 3. Add Bot Scopes

1. Go to **Features** → **OAuth & Permissions**
2. Under **Bot Token Scopes**, add:
   - `chat:write` — send messages
   - `channels:history` — read channel messages
   - `groups:history` — read private channel messages
   - `im:history` — read DMs
   - `mpim:history` — read group DMs
   - `channels:read` — list channels
   - `im:read` — list DMs

## 4. Enable Events

1. Go to **Features** → **Event Subscriptions** → toggle **Enable Events**
2. Under **Subscribe to bot events**, add:
   - `message.channels` — messages in public channels
   - `message.groups` — messages in private channels
   - `message.im` — direct messages
   - `message.mpim` — group DMs

## 5. Install to Workspace

1. Go to **Settings** → **Install App** → **Install to Workspace** → **Allow**
2. Copy the **Bot User OAuth Token** (starts with `xoxb-`) — this is your `botToken`

## 6. Connect to HarnessGate

```python
import asyncio
import os
from harnessgate import Bridge, SlackAdapter
from harnessgate.providers import ClaudeProvider

provider = ClaudeProvider(os.environ["ANTHROPIC_API_KEY"])
bridge = Bridge(provider, default_agent_id="your-agent-id", default_environment_id="your-env-id")

bridge.add_platform(SlackAdapter())

async def main():
    await bridge.start({
        "slack": {
            "botToken": os.environ["SLACK_BOT_TOKEN"],
            "appToken": os.environ["SLACK_APP_TOKEN"],
        }
    })

asyncio.run(main())
```

## 7. Test

1. In Slack, invite the bot to a channel: `/invite @YourBot`
2. Send a message — the bot should respond
3. For DMs, find the bot under **Apps** in the sidebar

## SaaS Distribution

To let other Slack workspaces install your app:

1. Go to **Settings** → **Manage Distribution**
2. Complete the checklist (app name, description, icons, redirect URLs)
3. Click **Activate Public Distribution**
4. Share your **Install Link** — workspace admins click it to add your app
5. Optionally, submit to the [Slack App Directory](https://slack.com/apps) for public listing

Each installation gives you a unique `botToken` per workspace. Use `connect()` to register multiple workspaces:

```python
slack = SlackAdapter()
bridge.add_platform(slack)
# Each customer's workspace
await slack.connect({"botToken": customer1_token, "appToken": app_level_token}, ctx)
await slack.connect({"botToken": customer2_token, "appToken": app_level_token}, ctx)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | App-Level Token (`xapp-...`) |
