# Makefile for GRAAM-GYAAN (Offline-First AI Assistant for Rural Welfare)

.PHONY: demo seed test test-demo check scrape clean run-live

seed:
	python scripts/seed_demo.py

demo: seed
	@echo "================================================================="
	@echo "Starting GRAAM-GYAAN in Offline-Ready Demo Mode (DEMO_CACHE=1)"
	@echo "Open your browser at: http://localhost:8000"
	@echo "================================================================="
	DEMO_CACHE=1 uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

test:
	python -m pytest -v

test-demo:
	python scripts/run_demo_scenario.py

check:
	python scripts/check_hardcoded.py

scrape:
	python scripts/scrape_sources.py

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('__pycache__'), pathlib.Path('.pytest_cache'), pathlib.Path('backend/__pycache__'), pathlib.Path('tests/__pycache__')]]"
