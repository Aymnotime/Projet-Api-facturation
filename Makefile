.PHONY: test api frontend docker-up

test:
	.venv/bin/pytest -q backend/tests

api:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

docker-up:
	docker compose up --build
