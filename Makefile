.PHONY: help build train backtest paper live dashboard stop clean logs test lint

help: ## Show this help
	@echo "GridAI Trader - Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build all Docker images
	docker compose build

train: ## Train the volatility classifier model
	docker compose --profile training run --rm trainer

backtest: ## Run backtesting engine
	docker compose --profile backtest up --build

paper: ## Run paper trading mode
	docker compose --profile paper up --build

live: ## Run live trading mode (REAL MONEY)
	@echo "⚠️  WARNING: This uses REAL MONEY. Ensure .env is configured."
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	docker compose --profile live up --build

dashboard: ## Start the monitoring dashboard
	docker compose --profile dashboard up --build -d
	@echo "Dashboard available at http://localhost:8080"

stop: ## Stop all running containers
	docker compose --profile paper --profile live --profile dashboard --profile backtest down

clean: ## Remove containers, volumes, and images
	docker compose --profile paper --profile live --profile dashboard --profile backtest --profile training down -v --rmi local
	@echo "Cleaned up all containers, volumes, and images"

logs: ## View bot logs
	docker compose logs -f bot-paper bot-live 2>/dev/null || echo "No running bot containers"

test: ## Run unit tests locally
	python -m pytest tests/ -v

lint: ## Run linting
	python -m py_compile main.py
	python -m py_compile core/grid_engine.py
	python -m py_compile core/order_manager.py
	python -m py_compile core/position_tracker.py
	python -m py_compile ai/volatility_classifier.py
	python -m py_compile ai/trend_detector.py
	python -m py_compile risk/risk_manager.py
	python -m py_compile backtesting/backtest_engine.py
	python -m py_compile backtesting/metrics.py
	python -m py_compile dashboard/app.py
	python -m py_compile config/config_manager.py

wipe-state: ## Wipe all persisted state (dangerous!)
	@read -p "This will delete all trading state. Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	docker volume rm gridai_state gridai_db gridai_logs 2>/dev/null || true
	@echo "State wiped"

wipe-models: ## Remove trained models
	docker volume rm gridai_models 2>/dev/null || true
	@echo "Models wiped"
