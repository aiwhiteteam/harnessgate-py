# Microsoft Teams Setup

## Prerequisites

- An [Azure account](https://portal.azure.com) (free tier works)
- A Microsoft 365 tenant for testing (free developer tenant available via [Microsoft 365 Developer Program](https://developer.microsoft.com/en-us/microsoft-365/dev-program))
- A publicly accessible HTTPS URL for the bot endpoint (use ngrok for development)

## 1. Register an Azure Bot

1. Go to [Azure Portal](https://portal.azure.com)
2. Search for **Azure Bot** → **Create**
3. Fill in:
   - **Bot handle**: a unique name
   - **Subscription**: your Azure subscription
   - **Resource group**: create new or use existing
   - **Type of App**: **Multi Tenant** (required for SaaS)
   - **Creation type**: **Create new Microsoft App ID**
4. Click **Review + Create** → **Create**
5. Once deployed, go to the resource

## 2. Get Your Credentials

1. In your Azure Bot → **Configuration**
2. Copy the **Microsoft App ID** (this is your `appId`)
3. Click **Manage Password** → **New client secret** → copy the **Value** (this is your `appPassword`)
   - Save this immediately — you can't view it again

## 3. Configure the Messaging Endpoint

1. In Azure Bot → **Configuration**
2. Set **Messaging endpoint** to `https://your-server.com/api/messages`
3. Click **Apply**

For local development:
```bash
ngrok http 3978
# Set messaging endpoint to https://xxxx.ngrok.io/api/messages
```

## 4. Enable Teams Channel

1. In Azure Bot → **Channels**
2. Click **Microsoft Teams** → **Apply**
3. Agree to the terms

## 5. Create a Teams App Manifest

Create a `manifest.json`:

```json
{
  "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
  "manifestVersion": "1.16",
  "version": "1.0.0",
  "id": "YOUR_APP_ID",
  "developer": {
    "name": "Your Company",
    "websiteUrl": "https://yoursite.com",
    "privacyUrl": "https://yoursite.com/privacy",
    "termsOfUseUrl": "https://yoursite.com/terms"
  },
  "name": {
    "short": "My AI Bot",
    "full": "My AI Assistant Bot"
  },
  "description": {
    "short": "AI-powered assistant",
    "full": "An AI assistant powered by Claude."
  },
  "icons": {
    "color": "color.png",
    "outline": "outline.png"
  },
  "accentColor": "#FFFFFF",
  "bots": [
    {
      "botId": "YOUR_APP_ID",
      "scopes": ["personal", "team", "groupChat"],
      "supportsFiles": false,
      "isNotificationOnly": false
    }
  ],
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": []
}
```

Package it as a zip with `manifest.json`, `color.png` (192x192), and `outline.png` (32x32 transparent).

## 6. Connect to HarnessGate

```python
import asyncio
import os
from harnessgate import Bridge, TeamsAdapter
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

bridge.add_platform(TeamsAdapter())

async def main():
    await bridge.start({
        "teams": {
            "appId": os.environ["TEAMS_APP_ID"],
            "appPassword": os.environ["TEAMS_APP_PASSWORD"],
            "port": 3978,
        }
    })

asyncio.run(main())
```

## 7. Test (Sideload)

1. Open Microsoft Teams
2. Go to **Apps** → **Manage your apps** → **Upload a custom app**
3. Upload your manifest zip
4. Click **Add** → start chatting with the bot

## SaaS Distribution

### For Other Organizations to Install Your Bot

Since you registered as **Multi Tenant**, other orgs can install your bot:

1. **Sideload** (testing): Send the manifest zip to the customer's Teams admin. They upload it in **Teams Admin Center** → **Manage apps** → **Upload**.

2. **Org App Catalog**: The customer's admin publishes your app to their org's internal catalog. Users find it under **Apps** → **Built for your org**.

3. **Teams App Store** (public): Submit your app to Microsoft for review:
   - Go to [Partner Center](https://partner.microsoft.com/en-us/dashboard/marketplace-offers/overview)
   - Create a new Teams app offer
   - Submit for validation (takes 1-2 weeks)
   - Once approved, anyone can find and install your bot from the Teams App Store

### How It Works for Customers

1. Admin approves the app (or user installs from App Store)
2. Users find the bot in Teams → click **Chat** → start messaging
3. All messages route to YOUR server → HarnessGate → your AI provider
4. Customer never manages any infrastructure

### Multi-Instance

```python
teams = TeamsAdapter()
bridge.add_platform(teams)
# Each Azure Bot registration (if you need separate identities per customer)
await teams.connect({"appId": bot1_app_id, "appPassword": bot1_password}, ctx)
await teams.connect({"appId": bot2_app_id, "appPassword": bot2_password}, ctx)
```

Most SaaS scenarios use a single multi-tenant bot registration — all customers share the same App ID.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TEAMS_APP_ID` | Microsoft App ID from Azure Bot |
| `TEAMS_APP_PASSWORD` | Client secret from Azure AD |
