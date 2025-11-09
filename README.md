# Discord Mute Monitor Bot

Automatically disconnects users from voice channels after they've been muted for a specified duration. Users actively sending TTS messages are exempt.

## Features

- Tracks server mute and self-mute status
- Configurable timeout duration (default: 30 minutes)
- TTS activity exemption (users sending TTS messages won't be disconnected)
- Admin slash commands to check status and adjust settings
- Periodic checks (default every 1 second; configurable)

## Setup

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and name it
3. Go to "Bot" section and click "Add Bot"
4. Enable these Privileged Gateway Intents:
   - Server Members Intent
   - Message Content Intent
5. Copy the bot token (you'll need this later)
6. Go to "OAuth2" > "URL Generator"
   - Select scopes: `bot`
   - Select permissions: `Move Members`, `Read Messages/View Channels`, `Send Messages`
7. Use the generated URL to invite the bot to your server

### 2. Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DISCORD_TOKEN="your_bot_token_here"
export MUTE_TIMEOUT_MINUTES="30"           # optional; default 30
export CHECK_INTERVAL_SECONDS="1"          # optional; default 1
# Optional: set TEST_GUILD_ID for faster slash command sync during testing
# export TEST_GUILD_ID="123456789012345678"

# Run the bot
python mute_monitor_bot.py
```

## Bot Commands (Slash)

- `/set-timeout <minutes>` — Set mute timeout (admin only)
- `/set-interval <seconds>` — Set check interval in seconds (admin only)
- `/mute-status` — View currently tracked muted users (ephemeral)

## Deploy to Google Cloud Platform (Free Tier)

### Prerequisites

- Google Cloud account ([sign up here](https://cloud.google.com/free))
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed locally

### Option 1: GCP Compute Engine (Recommended for 24/7 bots)

The e2-micro instance is **always free** in these regions:

- us-west1 (Oregon)
- us-central1 (Iowa)
- us-east1 (South Carolina)

**Free tier limits:**

- 1 e2-micro instance per month
- 30 GB standard persistent disk
- 1 GB network egress (except to China/Australia)

#### Step-by-step deployment:

```bash
# 1. Set up GCP project
gcloud projects create discord-bot-project --name="Discord Bot"
gcloud config set project discord-bot-project

# 2. Enable required APIs
gcloud services enable compute.googleapis.com
gcloud services enable containerregistry.googleapis.com

# 3. Create a VM instance (use free tier eligible regions)
gcloud compute instances create discord-mute-bot \
    --zone=us-west1-b \
    --machine-type=e2-micro \
    --image-family=debian-11 \
    --image-project=debian-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-standard \
    --tags=discord-bot

# 4. SSH into the instance
gcloud compute ssh discord-mute-bot --zone=us-west1-b

# 5. On the VM, install Docker
sudo apt-get update
sudo apt-get install -y docker.io git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

# 6. Clone or upload your bot files
# Option A: Use git
git clone https://github.com/your-repo/discord-mute-bot.git
cd discord-mute-bot

# Option B: Create files manually
mkdir discord-bot && cd discord-bot
nano mute_monitor_bot.py  # Paste the bot code
nano requirements.txt     # Paste requirements
nano Dockerfile          # Paste Dockerfile

# 7. Build Docker image
sudo docker build -t discord-mute-bot .

# 8. Create systemd service for auto-restart
sudo nano /etc/systemd/system/discord-bot.service
```

Paste this into the service file:

```ini
[Unit]
Description=Discord Mute Monitor Bot
After=docker.service
Requires=docker.service

[Service]
Type=simple
Environment="DISCORD_TOKEN=YOUR_BOT_TOKEN_HERE"
Environment="MUTE_TIMEOUT_MINUTES=30"
ExecStart=/usr/bin/docker run --rm --name discord-bot \
    -e DISCORD_TOKEN=$DISCORD_TOKEN \
    -e MUTE_TIMEOUT_MINUTES=$MUTE_TIMEOUT_MINUTES \
    discord-mute-bot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 9. Start the service
sudo systemctl daemon-reload
sudo systemctl enable discord-bot.service
sudo systemctl start discord-bot.service

# 10. Check status
sudo systemctl status discord-bot.service
sudo docker logs -f discord-bot
```

### Option 2: Cloud Run (Request-based, not ideal for 24/7)

Cloud Run is designed for request-based services and may sleep when inactive. For a Discord bot, use Compute Engine instead.

## Environment Variables

- `DISCORD_TOKEN` — Your Discord bot token (required)
- `MUTE_TIMEOUT_MINUTES` — Minutes before disconnecting muted users (default: 30)
- `CHECK_INTERVAL_SECONDS` — Seconds between checks (default: 1)
- `TEST_GUILD_ID` — Guild ID to sync slash commands to for faster availability (optional)

## Monitoring & Maintenance

```bash
# View logs
sudo journalctl -u discord-bot.service -f

# Restart bot
sudo systemctl restart discord-bot.service

# Update bot
cd discord-bot
git pull  # or update files manually
sudo docker build -t discord-mute-bot .
sudo systemctl restart discord-bot.service

# Stop bot
sudo systemctl stop discord-bot.service
```

## Cost Considerations

**Free tier (e2-micro in eligible regions):**

- VM: FREE (1 instance)
- Disk: FREE (30 GB standard)
- Egress: FREE (1 GB/month)

**If you exceed free tier:**

- Additional instances: ~$7/month per e2-micro
- Additional egress: $0.12/GB after 1 GB

The Discord bot uses minimal resources and should stay within free tier limits.

## Troubleshooting

**Bot not responding:**

- Check bot is online: `sudo systemctl status discord-bot.service`
- View logs: `sudo docker logs discord-bot`
- Verify bot has correct permissions in Discord server

**Permission errors:**

- Ensure bot has "Move Members" permission
- Check role hierarchy (bot role must be above users it manages)

**High memory usage:**

- e2-micro has limited RAM (1 GB)
- Monitor with: `free -h` and `docker stats`
- Restart bot if needed: `sudo systemctl restart discord-bot.service`

## Security Notes

- Never commit your Discord token to version control
- Use environment variables or GCP Secret Manager for tokens
- Restrict SSH access to your GCP instance
- Keep system and packages updated

## License

MIT License - Feel free to modify and use as needed.
