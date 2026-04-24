# CLAUDE.md — HarnessGate (Python)

## What is this project

HarnessGate is a universal gateway that connects AI agent runtimes (Claude Managed Agents, custom providers) to messaging platforms (Telegram, Discord, Slack, WhatsApp, Teams, Web UI). This is the Python implementation — a sibling repo to the Node.js version.

## Architecture

```
Platforms (inbound)  →  Bridge (orchestrator)  →  Provider (outbound to agent runtime)
                        SessionStore + StreamManager
```

- **Provider** (`src/harnessgate/provider.py`) — ABC for agent runtimes. Required methods: `create_session`, `send_message`, `stream`, `destroy_session`. Optional: `interrupt`, `confirm_tool`, `submit_tool_result`.
- **PlatformAdapter** (`src/harnessgate/platform.py`) — ABC for messaging platforms. Required: `start`, `stop`, `send`. Optional: `send_typing`, `connect`, `disconnect`, `active_connections`.
- **Bridge** (`src/harnessgate/bridge.py`) — orchestrator connecting platforms to providers. Manages session mapping, stream lifecycle, message buffering, and text splitting.
- **SessionStore** (`src/harnessgate/session.py`) — ABC for session persistence. Built-in: `MemorySessionStore`. Swappable via `bridge.set_session_store()`.
- **StreamManager** (`src/harnessgate/stream.py`) — manages one async stream per active session with exponential backoff and event deduplication.

### Platform adapters

| Adapter | File | Library | Max text |
|---------|------|---------|----------|
| Telegram | `src/harnessgate/platforms/telegram.py` | aiogram 3.x | 4096 |
| Discord | `src/harnessgate/platforms/discord.py` | discord.py | 2000 |
| Slack | `src/harnessgate/platforms/slack.py` | slack-bolt | 4000 |
| WhatsApp | `src/harnessgate/platforms/whatsapp.py` | Cloud API (aiohttp) | 4096 |
| Teams | `src/harnessgate/platforms/teams.py` | botbuilder | 28000 |
| Web | `src/harnessgate/platforms/web.py` | aiohttp | 100000 |

### Provider

- `ClaudeProvider` (`src/harnessgate/providers/claude.py`) — Claude Managed Agents API via `anthropic` SDK. Streaming, tool confirmation, custom tools, extended thinking.

## Session scoping

One conversation context = one provider session.

- **DM**: per-user session → key includes `u:userId`
- **Group/Channel**: shared session → key is just `platform:group:channelId`
- **Thread**: per-thread session → key includes `t:threadId`
- Optional: `app:appId` for multi-bot

Session key format: `platform:chat_type:channel_id[:app:app_id][:t:thread_id][:u:user_id][:a:agent_id][:s:session_id]`

## Multi-instance / appId

- **appId** — platform-assigned bot/app identity. Opaque to core.
- `PlatformAdapter` has optional `connect()`/`disconnect()`/`active_connections()` for multi-instance.
- `InboundMessage.app_id` carries the bot identity on every incoming message.
- `UserResolver` handles auth and bot→agent routing using `message.app_id`.

### appId per platform

| Platform | Source | Example value |
|----------|--------|---------------|
| Telegram | `bot.id` | `"123456789"` |
| Discord | `client.application_id` | `"1098765432101234567"` |
| Slack | `auth_test().bot_id` | `"A0123456789"` |
| WhatsApp | WABA phone number ID | `"106540352267890"` |
| Teams | `activity.recipient.id` | `"28:abc123..."` |
| Web | N/A (single instance) | -- |

## Project layout

```
src/harnessgate/
├── __init__.py             # Public API exports
├── bridge.py               # Orchestrator
├── messages.py             # InboundMessage, OutboundMessage, Sender, Attachment
├── platform.py             # PlatformAdapter ABC + PlatformCapabilities
├── provider.py             # Provider ABC + ProviderEvent types
├── session.py              # SessionStore ABC, MemorySessionStore
├── stream.py               # StreamManager
├── platforms/
│   ├── __init__.py         # Adapter exports
│   ├── telegram.py
│   ├── discord.py
│   ├── slack.py
│   ├── whatsapp.py
│   ├── teams.py
│   └── web.py
└── providers/
    ├── __init__.py
    └── claude.py
tests/
├── test_bridge.py          # split_text tests
├── test_session.py         # session key + store tests
├── test_stream.py          # stream manager tests
├── test_normalize_slack.py
├── test_normalize_teams.py
└── test_normalize_whatsapp.py
docs/                       # Platform setup guides (one per platform)
examples/                   # Starter projects
```

## Key design decisions

- **Fully async**: All adapters and providers use `async`/`await`. Platform adapters run via `asyncio.create_task()`.
- **Buffer-then-send**: agent message events are buffered until `status_idle`, then flushed as one message.
- **Dataclasses**: `InboundMessage`, `OutboundMessage`, `Sender`, `Attachment` are `@dataclass` with `__slots__`.
- **ABC pattern**: `PlatformAdapter` and `Provider` are abstract base classes. Optional methods have default no-op implementations.
- **Normalize functions**: Each platform adapter has a private `_normalize_*()` function that converts platform-specific objects to `InboundMessage`. These are pure functions, tested independently.
- **Multi-instance dict**: Each adapter stores instances in a dict keyed by `app_id` (e.g., `_bots`, `_clients`, `_apps`, `_instances`).

## Build, test & run

```bash
uv sync                  # install dependencies
uv run pytest            # run tests
uv run pyright           # type checking
```

## Conventions

- Python >= 3.11, asyncio throughout
- snake_case functions/variables, PascalCase classes
- `@dataclass(slots=True)` for data containers
- Platform files: `src/harnessgate/platforms/{name}.py`
- Tests in `tests/` directory: `test_normalize_{name}.py` for platform normalize tests
- Type hints everywhere, Pyright strict mode
- Build system: Hatchling via pyproject.toml
