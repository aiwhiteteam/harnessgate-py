<!-- TODO: Add logo/banner image -->
<!-- <p align="center"><img src="docs/assets/banner.png" alt="HarnessGate" width="600" /></p> -->

<h1 align="center">HarnessGate (Python)</h1>

<p align="center">
  <strong>Connect any AI agent runtime to any messaging platform.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" /></a>
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-brightgreen" alt="Python" />
</p>

---

## Why HarnessGate?

Existing chatbot frameworks run their **own agent loop** — they call LLM APIs, parse tool calls, execute tools locally, and manage context. When you connect them to a managed agent runtime like Claude Managed Agents, they have to **bypass their entire infrastructure** just to pipe messages through.

HarnessGate takes a different approach: **no local agent loop.** It's a pure bridge that delegates all intelligence to the provider runtime. The gateway just routes messages between platforms and the agent.

This means:
- Claude Managed Agents features work out of the box (tool confirmation, custom tools, multi-agent threads, extended thinking)
- Any future agent runtime plugs in with 4 methods
- No competing agent loops, no bypassed infrastructure, no wasted abstractions

```
[Telegram] [Discord] [Slack] [WhatsApp] [Teams] [Web UI]
     |         |        |       |          |       |
     +----+----+----+---+-------+----------+------+
          |         |
     PlatformAdapter ABC (per platform)
          |         |
          +----+----+
               |
          Bridge (orchestrator)
          SessionStore + StreamManager
               |
        Provider ABC
               |
    +----------+----------+
    | Claude   | Custom   |
    | Managed  | (your    |
    | Agents   |  class)  |
    +----------+----------+
```

## Features

- **Provider-agnostic** — Claude Managed Agents or bring your own
- **6 platform adapters** — Telegram, Discord, Slack, WhatsApp, Teams, Web UI
- **Multi-app** — run multiple bot instances per platform, each mapped to a different agent
- **Session management** — automatic session creation, in-memory persistence, multi-turn conversations
- **Buffer-then-send** — accumulates agent responses, sends as one message per turn
- **Auto-split** — respects per-platform message length limits
- **Fully async** — built on asyncio with `async`/`await` throughout

## Quick Start

```bash
pip install harnessgate
```

```python
import asyncio
from harnessgate import Bridge, BridgeConfig
from harnessgate.providers import ClaudeProvider
from harnessgate.platforms import TelegramAdapter

async def main():
    provider = ClaudeProvider(api_key="sk-ant-...")
    bridge = Bridge(
        provider=provider,
        config=BridgeConfig(platforms={"telegram": {"enabled": True}}),
    )

    # Route users to agents
    async def resolve_user(sender, platform, message):
        return {
            "user_id": sender.id,
            "agent_id": "agent_01XXXX",
            "environment_id": "env_01XXXX",
        }

    bridge.set_user_resolver(resolve_user)
    bridge.add_platform(TelegramAdapter())

    await bridge.connect("telegram", {"bot_token": "123:ABC..."})
    await bridge.start()

asyncio.run(main())
```

## Platform Adapters

| Platform | Library | Max text | Markdown | Threads | Typing | Attachments |
|----------|---------|----------|----------|---------|--------|-------------|
| Telegram | aiogram 3.x | 4096 | Yes | Yes | Yes | Yes |
| Discord | discord.py | 2000 | Yes | Yes | Yes | Yes |
| Slack | slack-bolt | 4000 | Yes | Yes | No | Yes |
| WhatsApp | Cloud API (aiohttp) | 4096 | No | No | No | Yes |
| Teams | Bot Framework SDK | 28000 | Yes | Yes | Yes | Yes |
| Web | Built-in (aiohttp) | 100000 | Yes | No | Yes | No |

## Platform Setup Guides

Detailed setup instructions for each platform, including SaaS multi-tenant distribution:

- [Telegram Setup](docs/setup-telegram.md) — BotFather, privacy settings, multi-instance
- [Discord Setup](docs/setup-discord.md) — Developer Portal, intents, OAuth2 invite links
- [Slack Setup](docs/setup-slack.md) — Socket Mode, scopes, App Directory distribution
- [WhatsApp Setup](docs/setup-whatsapp.md) — Meta Business, webhook config, Embedded Signup
- [Teams Setup](docs/setup-teams.md) — Azure Bot, manifest, Teams App Store
- [Web Setup](docs/setup-web.md) — HTTP endpoints, SSE streaming

## Provider Setup

### Claude Managed Agents

```python
from harnessgate.providers import ClaudeProvider

provider = ClaudeProvider(
    api_key="sk-ant-...",
    default_agent_id="agent_01XXXX",
    default_environment_id="env_01XXXX",
)
```

Connects to [Claude Managed Agents](https://docs.anthropic.com/en/docs/managed-agents/overview). Full support for streaming, tool confirmation, custom tools, extended thinking, and multi-agent threads.

### Custom provider

Implement the `Provider` ABC:

```python
from harnessgate import Provider

class MyProvider(Provider):
    id = "my-provider"
    capabilities = ProviderCapabilities(
        interrupt=False,
        tool_confirmation=False,
        custom_tools=False,
        thinking=False,
    )

    async def create_session(self, opts): ...
    async def send_message(self, session_id, message): ...
    async def stream(self, session_id): ...  # AsyncIterator[ProviderEvent]
    async def destroy_session(self, session_id): ...
```

## Multi-Bot / appId

Every platform adapter supports running multiple app instances simultaneously. Each app connects to the platform and receives a platform-assigned `appId`.

```python
# Add multiple Telegram bots at runtime
support_id = await bridge.connect("telegram", {"bot_token": SUPPORT_TOKEN})
sales_id = await bridge.connect("telegram", {"bot_token": SALES_TOKEN})

# Route based on which bot received the message
async def resolve_user(sender, platform, message):
    agent_id = await db.get_agent_for_bot(message.app_id)
    return {"user_id": sender.id, "agent_id": agent_id, "environment_id": "env_01XXXX"}
```

### appId per platform

| Platform | Source | Example value |
|----------|--------|---------------|
| Telegram | `bot.id` | `"123456789"` |
| Discord | `client.application_id` | `"1098765432101234567"` |
| Slack | `auth_test().bot_id` | `"A0123456789"` |
| WhatsApp | WABA phone number ID | `"106540352267890"` |
| Teams | `activity.recipient.id` | `"28:abc123..."` |
| Web | N/A (single instance) | -- |

## Session Management

Each conversation context gets its own provider session:

| Context | Session scope | Example key |
|---------|--------------|-------------|
| DM | Per user | `telegram:direct:123:u:user99` |
| Group/Channel | Shared (all users) | `slack:group:ch1` |
| Thread | Per thread | `discord:thread:ch1:t:thread99` |

## Project Structure

```
harnessgate-py/
├── src/harnessgate/
│   ├── __init__.py             # Public API exports
│   ├── bridge.py               # Orchestrator
│   ├── messages.py             # InboundMessage, OutboundMessage, Sender, Attachment
│   ├── platform.py             # PlatformAdapter ABC
│   ├── provider.py             # Provider ABC + ProviderEvent types
│   ├── session.py              # SessionStore, MemorySessionStore
│   ├── stream.py               # StreamManager
│   ├── platforms/
│   │   ├── telegram.py         # aiogram 3.x
│   │   ├── discord.py          # discord.py
│   │   ├── slack.py            # slack-bolt
│   │   ├── whatsapp.py         # Cloud API (aiohttp)
│   │   ├── teams.py            # Bot Framework SDK
│   │   └── web.py              # Built-in HTTP + SSE
│   └── providers/
│       └── claude.py           # Claude Managed Agents
├── tests/                      # pytest test suite
├── docs/                       # Platform setup guides
├── examples/                   # Starter projects
└── pyproject.toml
```

## Requirements

- Python >= 3.11
- uv (recommended) or pip

## Development

```bash
uv sync
uv run pytest
uv run pyright     # type checking
```

## License

MIT
