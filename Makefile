# AINIX — POC targets.
ACCEL       ?= cpu
IMAGE       ?= ainix/runtime:$(ACCEL)
MODEL       ?= unsloth/gemma-3-1b-it
PORT        ?= 8000
NAME        ?= ainix-runner
HF_CACHE    ?= $(HOME)/.cache/huggingface
MAX_CACHE   ?= $(HOME)/.cache/ainix/max

.PHONY: image run stop logs smoke bench clean agent-new agent-check agents models fetch

image:
ifeq ($(ENGINE),max)
	docker build --build-arg ACCEL=$(ACCEL) -f runtime/Dockerfile -t $(IMAGE) .
else
	docker build -f runtime/Dockerfile.llamacpp -t $(IMAGE) .
endif
	@docker image inspect $(IMAGE) --format 'image size: {{.Size}} bytes'

run:
	mkdir -p $(HF_CACHE) $(MAX_CACHE) $(WEIGHTS)
	docker rm -f $(NAME) 2>/dev/null || true
ifeq ($(ENGINE),max)
	docker run -d --name $(NAME) -p $(PORT):8000 \
	  -v $(HF_CACHE):/var/cache/huggingface \
	  -v $(MAX_CACHE):/opt/venv/share/max/.max_cache \
	  -e AINIX_MODEL=$(MODEL) -e AINIX_DEVICES=$(ACCEL) \
	  $(IMAGE)
	@echo "serving $(MODEL) on :$(PORT) — first run downloads weights and compiles the graph"
else
	docker run -d --name $(NAME) -p $(PORT):8000 \
	  -v $(WEIGHTS):/weights:ro \
	  -e AINIX_MODEL_FILE=/weights/$(GGUF) \
	  $(IMAGE)
	@echo "serving $(GGUF) on :$(PORT)"
endif

stop:
	docker rm -f $(NAME) 2>/dev/null || true

logs:
	docker logs -f $(NAME)

smoke:
	PORT=$(PORT) MODEL=$(MODEL) test/smoke.sh

bench:
	PORT=$(PORT) MODEL=$(MODEL) bench/run.sh

clean: stop
	docker rmi $(IMAGE) 2>/dev/null || true

# ---- agents ---------------------------------------------------------------

# make agent-new TIER=app NAME=my-agent
agent-new:
	scripts/new-agent.sh $(TIER) $(NAME)

# make agent-check            (all agents)
# make agent-check NAME=app/x (one agent)
agent-check:
	scripts/check-agent.sh $(NAME)

agents: agent-check

# ---- models ---------------------------------------------------------------

models:
	@python3 scripts/list_models.py

# make fetch MODEL_NAME=qwen3-1.7b
fetch:
	scripts/fetch-model.sh $(MODEL_NAME)
