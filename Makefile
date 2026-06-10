VENV_PYTHON ?= .venv/bin/python

FIXTURE_REGRESSION_TESTS = tests/test_poc_acceptance.py tests/test_final_gate.py
GENERIC_HEALTH_TESTS = tests/test_runtime_governance.py tests/test_governed_review_flow_e2e.py tests/test_frontend_shell.py tests/test_api_health.py tests/test_api_identity_boundary.py tests/test_api_security_boundary.py tests/test_deploy_config_hygiene.py

.PHONY: poc-acceptance fixture-regression generic-health tranche-b-tests final-gate postgres-proof

poc-acceptance:
	$(VENV_PYTHON) -m strategyos_mvp.poc_acceptance

fixture-regression:
	$(VENV_PYTHON) -m pytest -q $(FIXTURE_REGRESSION_TESTS)

generic-health:
	$(VENV_PYTHON) -m pytest -q $(GENERIC_HEALTH_TESTS)

tranche-b-tests:
	$(VENV_PYTHON) -m pytest -q $(FIXTURE_REGRESSION_TESTS) $(GENERIC_HEALTH_TESTS)

final-gate:
	$(VENV_PYTHON) -m strategyos_mvp.final_gate

postgres-proof:
	@test -n "$$STRATEGYOS_POSTGRES_E2E_DATABASE_URL" || (echo "Set STRATEGYOS_POSTGRES_E2E_DATABASE_URL to a dedicated proof database; this test truncates strategyos_* tables." >&2; exit 2)
	$(VENV_PYTHON) -m pytest -q tests/test_governed_review_flow_postgres_e2e.py -rs
