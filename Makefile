# MAISYS — local dev convenience targets.
# Linux / macOS only. Windows users: use scripts/dev-*.ps1 directly.

.PHONY: up down down-v smoke logs clean help

help:
	@echo "MAISYS local dev targets:"
	@echo "  make up        Bring up docker-compose, wait for healthy"
	@echo "  make down      Stop containers, keep volumes"
	@echo "  make down-v    Stop containers and remove volumes (lose data)"
	@echo "  make smoke     Run the auth-service smoke test"
	@echo "  make logs      Tail logs from all services"
	@echo "  make clean     Same as down-v"

up:
	./scripts/dev-up.sh

down:
	./scripts/dev-down.sh

down-v:
	./scripts/dev-down.sh -v

smoke:
	./scripts/dev-smoke-test.sh

logs:
	./scripts/dev-up.sh logs

clean: down-v
