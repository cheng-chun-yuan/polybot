# PolyBot

A Telegram bot for tracking Polymarket traders in real-time. Get instant notifications when wallets you follow make trades.

## Features

- **Real-time Trade Alerts** - WebSocket connection to ENVIO indexer for instant notifications
- **Wallet Tracking** - Follow multiple wallets with custom labels
- **Insider Detection** - Detect new traders making unusually large first trades
- **Whale Tracking** - Get notified of all large trades across the platform
- **Flexible Filters** - Filter by trade size, buy/sell side
- **Pause/Resume** - Temporarily disable notifications without removing wallets

## Quick Start

### Prerequisites

Install [uv](https://docs.astral.sh/uv/) (fast Python package manager):

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 1. Create Your Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Setup

```bash
# Clone the repository
git clone https://github.com/cheng-chun-yuan/polybot.git
cd polybot

# Install dependencies (requires Python 3.11+ and uv)
uv sync

# Configure environment
cp .env.example .env
# Edit .env and add your TELEGRAM_BOT_TOKEN
```

### 3. Run

```bash
uv run python -m src.main
```

## Commands

### Wallet Tracking

| Command | Description |
|---------|-------------|
| `/track <address> [label]` | Start tracking a wallet |
| `/untrack <address>` | Remove wallet from watchlist |
| `/pause <address>` | Temporarily stop notifications |
| `/resume <address>` | Resume notifications |
| `/list` | View all tracked wallets with links |

### Alert Settings

| Command | Description |
|---------|-------------|
| `/settings` | View current filter settings |
| `/setmin <amount>` | Set minimum USD threshold (e.g., `/setmin 100`) |
| `/setside <BUY\|SELL\|BOTH>` | Filter by trade direction |
| `/insider [on\|off] [min_usd] [max_trades]` | Configure insider detection |
| `/whale [on\|off] [min_usd]` | Configure whale tracking |

### General

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and setup |
| `/help` | Show all commands |
| `/status` | Bot status and stats |

## Daily Use Guide

### Step 1: Start Tracking Wallets

Find interesting traders on [PolyOctant](https://polyoctant.com) or [Polymarket](https://polymarket.com) and add them:

```
/track 0x1234...5678 whale1
/track 0xabcd...efgh smart_money
```

### Step 2: Configure Filters

Set minimum trade size to avoid noise:
```
/setmin 500
```

Only see buys:
```
/setside BUY
```

### Step 3: Enable Special Alerts

**Insider Detection** - Get notified when new wallets make large first trades (potential insider info):
```
/insider on 5000 3
```
This alerts you when a wallet with ≤3 total trades makes a trade ≥$5,000.

**Whale Tracking** - Get notified of ALL large trades (any wallet):
```
/whale on 10000
```
This alerts you of any trade ≥$10,000 across the entire platform.

### Step 4: Manage Your Watchlist

View your tracked wallets:
```
/list
```

Temporarily pause a wallet:
```
/pause 0x1234...5678
```

Resume later:
```
/resume 0x1234...5678
```

## Alert Examples

### Trade Alert
```
🟢 Trade Alert

Trader: whale1
Action: BUY Yes
Amount: $5,000
Price: 65.0%

Market: Will Bitcoin reach $100k by end of 2025?

Market | Trader
```

### Insider Alert
```
🕵️ INSIDER DETECTED!

Trader: 0x1234...5678
Total trades: 2
Total volume: $15,000

Latest: BUY Yes - $10,000 @ 72.0%
Market: Will ETH flip BTC market cap?

Trader | Market
```

### Whale Alert
```
🐋 WHALE TRADE!

Trader: 0xabcd...efgh
Action: SELL No
Amount: $50,000
Price: 23.0%
Market: Will Trump win 2024 election?

Trader | Market
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot                              │
│  /track /list /settings /insider /whale                     │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                   Trade Monitor                              │
│  WebSocket subscription to ENVIO indexer                    │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   ENVIO     │  │   Gamma     │  │   SQLite    │
│  (trades)   │  │  (markets)  │  │  (storage)  │
└─────────────┘  └─────────────┘  └─────────────┘
```

## External APIs

| API | Purpose |
|-----|---------|
| **ENVIO GraphQL** | Real-time trade detection via WebSocket |
| **Gamma API** | Market metadata (question, outcomes, slug) |
| **Data API** | Trader profiles and history |
| **CLOB API** | Order book and pricing |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `ENVIO_GRAPHQL_URL` | Yes | ENVIO GraphQL endpoint for trade detection |
| `GAMMA_API_URL` | No | Gamma API (default: https://gamma-api.polymarket.com) |
| `DATA_API_URL` | No | Data API (default: https://data-api.polymarket.com) |
| `CLOB_API_URL` | No | CLOB API (default: https://clob.polymarket.com) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |
| `POLL_INTERVAL` | No | Fallback poll interval in seconds |

## Project Structure

```
polybot/
├── src/
│   ├── main.py           # Entry point
│   ├── config.py         # Configuration
│   ├── bot/
│   │   ├── handlers.py   # Command handlers
│   │   ├── callbacks.py  # Button callbacks
│   │   └── messages.py   # Message formatting
│   ├── api/
│   │   ├── envio.py      # ENVIO GraphQL client
│   │   ├── gamma.py      # Market metadata
│   │   ├── data.py       # Trader data
│   │   └── clob.py       # Order book
│   ├── monitor/
│   │   └── trade_monitor.py  # Real-time monitoring
│   └── storage/
│       ├── database.py   # SQLite operations
│       └── models.py     # Data models
└── data/
    └── polybot.db        # SQLite database
```

## License

MIT

## Contributing

Pull requests welcome! Please open an issue first to discuss what you would like to change.
