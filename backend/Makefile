.PHONY: install run test seed db-up db-down

install:
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	.venv/bin/python -m pytest

seed:
	.venv/bin/python -m db.seed

db-up:
	docker compose up -d db

db-down:
	docker compose down
