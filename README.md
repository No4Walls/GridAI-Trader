# GridAI Trader

AI-powered Bitcoin grid trading bot that dynamically adapts to volatility and market regimes while prioritizing capital preservation.

## Features

- **Grid Trading Engine** — Configurable grid with automatic order placement, fill detection, and counter-order logic
- **AI Volatility Classifier** — RandomForest model classifies LOW/MEDIUM/HIGH volatility regimes to adjust grid spacing
- **Trend Detection** — MA crossover, RSI, ADX analysis pauses trading during strong directional moves
- **Risk Management** — Max drawdown, capital deployment limits, daily loss cap, emergency stop-loss
- **Backtesting** — 2+ year BTC history with fee/slippage simulation, Sharpe ratio, drawdown metrics
- **Paper Trading** — Live market feed with simulated execution
- **Live Trading** — Coinbase Advanced Trade via ccxt with retry logic, rate limiting, crash recovery
- **Dashboard** — Real-time web UI with equity curve, grid visualization, trade log, risk status

## Prerequisites

- Docker & Docker Compose v2+
- (Optional) Python 3.9+ for local development

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url> && cd gridai-trader
cp .env.example .env
# Edit .env with your Coinbase API credentials
```

### 2. Train the AI model

```bash
docker compose --profile training run --rm trainer
```

### 3. Run backtest

```bash
docker compose --profile backtest up --build
```

### 4. Run paper trading (recommended first)

```bash
docker compose --profile paper up --build
```

### 5. Start the dashboard

```bash
docker compose --profile dashboard up --build -d
# Open http://localhost:8080
```

### 6. Run live trading (REAL MONEY)

```bash
# Ensure .env has valid COINBASE_API_KEY and COINBASE_API_SECRET
docker compose --profile live up --build
```

## Makefile Commands

```bash
make help          # Show all commands
make build         # Build Docker images
make train         # Train volatility model
make backtest      # Run backtester
make paper         # Run paper trading
make live          # Run live trading (with confirmation)
make dashboard     # Start dashboard
make stop          # Stop all containers
make clean         # Remove containers, volumes, images
make test          # Run unit tests locally
make wipe-state    # Delete all trading state
make wipe-models   # Remove trained models
```

## Configuration

YAML config files in `config/`:

| Profile | Description |
|---------|-------------|
| `default.yaml` | Base configuration |
| `conservative.yaml` | Tighter grids, lower risk limits |
| `balanced.yaml` | Default risk/reward balance |
| `aggressive.yaml` | Wider grids, higher risk tolerance |

Environment variable overrides:

| Variable | Description |
|----------|-------------|
| `GRIDAI_NUM_GRIDS` | Number of grid levels |
| `GRIDAI_ORDER_SIZE` | Order size in USDT |
| `GRIDAI_MAX_DRAWDOWN` | Max drawdown % |
| `GRIDAI_MAX_CAPITAL` | Max capital deployed % |
| `GRIDAI_DAILY_LOSS_CAP` | Daily loss cap in USDT |
| `GRIDAI_LOG_LEVEL` | Logging level |

## Docker Volumes

| Volume | Purpose |
|--------|---------|
| `gridai_state` | Bot state and checkpoints |
| `gridai_models` | Trained ML models |
| `gridai_db` | SQLite database and trade logs |
| `gridai_logs` | Application logs |

### Persist state safely

State is automatically persisted to Docker volumes. To wipe:

```bash
make wipe-state    # Remove trading state
make wipe-models   # Remove models
make clean         # Remove everything
```

## Architecture

```
gridai-trader/
├── core/                  # Grid engine, order manager, position tracker
├── ai/                    # Volatility classifier, trend detector
├── risk/                  # Risk management system
├── data/                  # Historical loader, realtime feed (ccxt)
├── backtesting/           # Backtest engine, metrics
├── dashboard/             # Flask + SocketIO web dashboard
├── config/                # YAML configuration profiles
├── scripts/               # Entry point scripts
├── tests/                 # Unit tests
├── state/                 # Runtime state (Docker volume)
├── models/                # ML models (Docker volume)
├── logs/                  # Logs (Docker volume)
├── main.py                # Main orchestrator
├── Dockerfile             # Multi-stage Docker build
├── docker-compose.yml     # Compose with profiles
└── Makefile               # Common commands
```

## Risk Disclosure

**Trading cryptocurrency involves substantial risk of loss.** This software is provided as-is with no guarantees. You are solely responsible for any financial losses. Always start with paper trading mode to validate strategy before using real funds. Never trade with money you cannot afford to lose.

## Safe Startup Defaults

- Default mode is **paper trading** (no real money)
- Risk guardrails are enabled by default (15% max drawdown, 50% max capital deployed)
- Emergency stop-loss triggers at 10% portfolio loss
- All state persists across restarts via Docker volumes
- Live mode requires explicit API key configuration and confirmation
