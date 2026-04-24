# WhatsApp Business Cloud API Setup

## Prerequisites

- A [Meta Business Account](https://business.facebook.com/)
- A phone number to use with WhatsApp Business (cannot be currently registered on WhatsApp)
- A publicly accessible HTTPS URL for webhooks (use ngrok for development)

## 1. Create a Meta App

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps)
2. Click **Create App** → select **Business** type → **Next**
3. Name your app → select your Business Account → **Create App**

## 2. Add WhatsApp Product

1. In your app dashboard, find **WhatsApp** in the product list → **Set Up**
2. This creates a test phone number and temporary access token

## 3. Get Your Credentials

From the WhatsApp section of your app dashboard:

- **Phone Number ID**: Under **Getting Started** → your test number's ID
- **Access Token**: Click **Generate** for a temporary token (60-day), or create a **System User** in Business Settings for a permanent token
- **Verify Token**: You choose this — any string you want (used to verify your webhook)

### Permanent Access Token

For production, create a permanent token:

1. Go to [Business Settings](https://business.facebook.com/settings) → **Users** → **System Users**
2. Create a system user → assign the **WhatsApp Business** asset with `whatsapp_business_messaging` permission
3. Generate a token — this won't expire

## 4. Configure Webhook

1. In your app → **WhatsApp** → **Configuration**
2. Under **Webhook**, click **Edit**
3. Set **Callback URL** to `https://your-server.com/webhook`
4. Set **Verify Token** to the string you chose
5. Click **Verify and Save**
6. Subscribe to the `messages` webhook field

For local development:
```bash
ngrok http 3000
# Use the https URL ngrok gives you as the callback URL
```

## 5. Connect to HarnessGate

```python
import asyncio
import os
from harnessgate import Bridge, WhatsAppAdapter
from harnessgate.providers import ClaudeProvider

provider = ClaudeProvider(os.environ["ANTHROPIC_API_KEY"])
bridge = Bridge(provider, default_agent_id="your-agent-id", default_environment_id="your-env-id")

bridge.add_platform(WhatsAppAdapter())

async def main():
    await bridge.start({
        "whatsapp": {
            "phoneNumberId": os.environ["WHATSAPP_PHONE_NUMBER_ID"],
            "accessToken": os.environ["WHATSAPP_ACCESS_TOKEN"],
            "verifyToken": os.environ["WHATSAPP_VERIFY_TOKEN"],
            "port": 3000,
        }
    })

asyncio.run(main())
```

## 6. Test

1. From any WhatsApp account, send a message to your test phone number
2. The bot should respond via the WhatsApp Cloud API

## SaaS Distribution

For serving multiple customers' WhatsApp numbers:

### Option A: Embedded Signup (recommended)

Meta provides an [Embedded Signup](https://developers.facebook.com/docs/whatsapp/embedded-signup) flow where customers connect their WhatsApp number through your UI:

1. Customer clicks "Connect WhatsApp" in your app
2. They log in to Facebook and select their WhatsApp Business Account
3. You receive their phone number ID and access token via OAuth
4. Call `connect()` with their credentials

```python
whatsapp = WhatsAppAdapter()
bridge.add_platform(whatsapp)
# Each customer's phone number
await whatsapp.connect({
    "phoneNumberId": customer.phone_number_id,
    "accessToken": customer.access_token,
    "verifyToken": shared_verify_token,
}, ctx)
```

### Option B: Business Solution Provider (BSP)

Register as a [WhatsApp BSP](https://www.facebook.com/business/partner-directory) to manage customers' numbers at scale. This gives you API access to onboard numbers programmatically.

### Pricing

- First 1,000 service conversations/month: **free**
- After that: ~$0.005 per conversation (varies by country)
- One conversation = unlimited messages within a 24-hour window

## Environment Variables

| Variable | Description |
|----------|-------------|
| `WHATSAPP_PHONE_NUMBER_ID` | Phone Number ID from Meta dashboard |
| `WHATSAPP_ACCESS_TOKEN` | Permanent or temporary access token |
| `WHATSAPP_VERIFY_TOKEN` | Your chosen webhook verification string |
