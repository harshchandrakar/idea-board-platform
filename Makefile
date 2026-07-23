# The single human interface to the platform.
CLOUD ?= aws
ENV   ?= staging

.PHONY: up down test demo build-frontend gen deploy

up:            ## run the whole stack locally
	docker compose up --build

down:
	docker compose down -v

test:          ## run the Python test suite
	pip install -q -r requirements-dev.txt
	pytest -q

demo:          ## run the agent against a simulated cluster (no deps needed)
	python -m ai.agent demo

build-frontend:
	cd app/frontend && npm install && npm run build

gen:           ## generate IaC for a cloud from platform.json (needs GEMINI_API_KEY)
	python -m ai.iac_generator generate --provider $(CLOUD) --env $(ENV)

deploy:        ## kick off the pipeline (canary + agent) for CLOUD/ENV
	@echo "Trigger .github/workflows/deploy.yml with cloud=$(CLOUD) env=$(ENV)"
