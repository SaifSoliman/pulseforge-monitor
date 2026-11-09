.PHONY: install dev test lint run compose-up compose-down
install:
	python -m pip install -r requirements-dev.txt
run:
	uvicorn app.main:app --reload

dev: run

test:
	pytest -q

lint:
	ruff check app tests

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down
