.PHONY: dev test lint up down
dev:
	uvicorn app.main:app --reload --port 8080
test:
	pytest -q
lint:
	ruff check .
up:
	docker compose up --build
down:
	docker compose down
