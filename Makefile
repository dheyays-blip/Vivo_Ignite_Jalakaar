# JALAAKAR — clone, setup, run.
#
#     git clone https://github.com/orgkushal/Jalakaar.git && cd Jalakaar
#     make setup
#     make run
#
# `make setup` creates .venv, installs everything, and builds the database
# from the Parquet files in data/bootstrap/. No network needed.
# `make run` serves the API and the site together on :8000.

PY      := python3
VENV    := .venv
BIN     := $(VENV)/bin
PORT    ?= 8000

.DEFAULT_GOAL := help
.PHONY: help setup run test audit clean reset demo-user whatsapp-check users delete-user

help:
	@echo ""
	@echo "  make setup    create .venv, install deps, build the database"
	@echo "  make run      serve API + site on http://localhost:$(PORT)"
	@echo "  make test     98 API checks + frontend audit"
	@echo "  make audit    frontend only (links, classes, cache stamps)"
	@echo "  make reset    clear signups and alerts from data/app.db"
	@echo "  make users    who registered, and when (phones masked)"
	@echo "  make delete-user PHONE=9…  remove one account (keeps alert history)"
	@echo "  make whatsapp-check  will a send really deliver? (contacts nothing)"
	@echo "  make clean    remove .venv and the built database"
	@echo ""

$(BIN)/python:
	@echo "  creating $(VENV) …"
	@$(PY) -m venv $(VENV)
	@$(BIN)/pip install --quiet --upgrade pip

setup: $(BIN)/python
	@echo "  installing dependencies …"
	@$(BIN)/pip install --quiet -r requirements.txt -r requirements-api.txt
	@$(BIN)/python tools/bootstrap.py
	@echo "  Ready.  Run:  make run"

run:
	@test -x $(BIN)/uvicorn || { echo "  Run 'make setup' first."; exit 1; }
	@echo "  http://localhost:$(PORT)        the site"
	@echo "  http://localhost:$(PORT)/docs   the API"
	@echo ""
	@$(BIN)/uvicorn api.main:app --port $(PORT) --reload

test:
	@$(BIN)/python api/test_smoke.py
	@$(BIN)/python tools/audit_web.py

audit:
	@$(BIN)/python tools/audit_web.py

reset:
	@$(BIN)/python tools/reset_app_db.py --users

demo-user:
	@$(BIN)/python tools/seed_demo.py

whatsapp-check:
	@$(BIN)/python tools/check_twilio.py

users:
	@$(BIN)/python tools/list_users.py

# make delete-user PHONE=9123456780        asks to confirm
# make delete-user PHONE=9123456780 DRY=1  shows what would go
delete-user:
	@test -n "$(PHONE)" || { echo "  Usage: make delete-user PHONE=9123456780 [DRY=1]"; exit 1; }
	@$(BIN)/python tools/delete_user.py --phone $(PHONE) $(if $(DRY),--dry-run,)

clean:
	@rm -rf $(VENV) data/jalaakar.db data/app.db*
	@echo "  removed .venv, jalaakar.db, app.db"
