# Web UI Setup

## Prerequisites

- Your HarnessGate project set up with `harnessgate` installed

## 1. Connect to HarnessGate

The Web adapter runs an HTTP server with a built-in chat UI. No external platform setup needed.

```python
import asyncio
import os
from harnessgate import Bridge, WebAdapter
from harnessgate.providers import ClaudeProvider

provider = ClaudeProvider(os.environ["ANTHROPIC_API_KEY"])
bridge = Bridge(provider, default_agent_id="your-agent-id", default_environment_id="your-env-id")

bridge.add_platform(WebAdapter())

async def main():
    await bridge.start({"web": {"port": 3000}})

asyncio.run(main())
```

## 2. Test

1. Open `http://localhost:3000` in your browser
2. Enter a user ID or token when prompted
3. Start chatting

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Chat UI (HTML) |
| `GET` | `/health` | Health check (`{ status: "ok", clients: N }`) |
| `GET` | `/stream?token=USER_ID` | SSE stream for receiving messages |
| `POST` | `/message` | Send a message (`{ text: "..." }`) |

### Authentication

Messages require a user identity via one of:
- `Authorization: Bearer <userId>` header
- `?token=<userId>` query parameter

## Custom Frontend

To build your own frontend instead of the built-in chat UI:

```javascript
// Connect to SSE stream
const eventSource = new EventSource("/stream?token=my-user-id");
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "message") console.log("Bot:", data.text);
  if (data.type === "typing") console.log("Bot is typing...");
};

// Send a message
fetch("/message", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer my-user-id",
  },
  body: JSON.stringify({ text: "Hello!" }),
});
```

## Production Deployment

For production, put the Web adapter behind a reverse proxy (nginx, Cloudflare, etc.) that handles:
- HTTPS termination
- Authentication (replace the simple token with your auth system)
- Rate limiting

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PORT` | Server port (default: 3000) |
