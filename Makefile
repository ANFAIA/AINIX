# AINIX — POC targets.
ENGINE      ?= llamacpp        # llamacpp | max  — see docs/FINDINGS.md
ACCEL       ?= cpu
IMAGE       ?= ainix/runtime:$(ACCEL)-$(ENGINE)
WEIGHTS     ?= $(HOME)/.cache/ainix/weights
GGUF        ?= gemma-3-1b-it-Q4_K_M.gguf
MODEL       ?= unsloth/gemma-3-1b-it
PORT        ?= 8000
NAME        ?= ainix-runner   # the runner container; agents use AGENT=
HF_CACHE    ?= $(HOME)/.cache/huggingface
MAX_CACHE   ?= $(HOME)/.cache/ainix/max

.PHONY: image run stop logs smoke bench clean agent-new agent-check agents models fetch firstboot os-eval os-build os-boot skills example-check policy lint mojo-build test test-full boot-check runner-check

image:
ifeq ($(ENGINE),max)
	docker build --build-arg ACCEL=$(ACCEL) -f runtime/Dockerfile -t $(IMAGE) .
else
	docker build -f runtime/Dockerfile.llamacpp -t $(IMAGE) .
endif
	@docker image inspect $(IMAGE) --format 'image size: {{.Size}} bytes'

run:
	@scripts/port-free.sh $(PORT) $(NAME)
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
	  -e LLAMA_ARG_MODEL=/weights/$(GGUF) \
	  $(IMAGE)
	@echo "serving $(GGUF) on :$(PORT)"
endif

stop:
	docker rm -f $(NAME) 2>/dev/null || true

logs:
	docker logs -f $(NAME)

smoke:
	PORT=$(PORT) MODEL=$(MODEL) NAME=$(NAME) test/smoke.sh

bench:
	PORT=$(PORT) MODEL=$(MODEL) bench/run.sh

clean: stop
	docker rmi $(IMAGE) 2>/dev/null || true

# ---- agents ---------------------------------------------------------------

# make agent-new TIER=app AGENT=my-agent
agent-new:
	scripts/new-agent.sh $(TIER) $(AGENT)

# make agent-check            (all agents)
# make agent-check AGENT=app/x (one agent), or bare for all
agent-check:
	scripts/check-agent.sh $(AGENT)

agents: agent-check

# ---- models ---------------------------------------------------------------

models:
	@python3 scripts/list_models.py

# make fetch MODEL_NAME=qwen3-1.7b
fetch:
	scripts/fetch-model.sh $(MODEL_NAME)

# ---- first boot -----------------------------------------------------------

# make firstboot [ARGS=--force]
firstboot:
	python3 agents/system/firstboot/firstboot.py $(ARGS)

# ---- skills ---------------------------------------------------------------

# make skills            (everything)
# make skills TIER=app   (only what an app agent can see)
skills:
	@scripts/skillctl.py list $(if $(TIER),--as $(TIER))

# ---- bootable image -------------------------------------------------------
#
# Nix runs in a container because this is a Mac: no nix, no Linux kernel. The
# named volume keeps the store between runs, so the second build is fast.

NIX_RUN = docker run --rm -v "$(PWD)":/src -w /src -v ainix-nix-store:/nix \
          -v "$(PWD)/build":/out nixos/nix \
          nix --extra-experimental-features 'nix-command flakes'
PROFILE ?= cpu
ARCH    ?= aarch64

# Type-check the whole configuration without building anything.
os-eval:
	@git add -N flake.nix nix >/dev/null 2>&1 || true
	$(NIX_RUN) eval --raw \
	  .#nixosConfigurations.ainix-$(PROFILE)-$(ARCH).config.system.build.toplevel.drvPath

os-build:
	@git add -N flake.nix nix >/dev/null 2>&1 || true
	$(NIX_RUN) build .#qcow2 --out-link /out/ainix-qcow2 --print-build-logs

# Boots the artefact itself, with qemu from the host.
os-boot:
	qemu-system-aarch64 -M virt -cpu max -smp 4 -m 8192 \
	  -bios $$(brew --prefix qemu)/share/qemu/edk2-aarch64-code.fd \
	  -drive file=build/ainix-qcow2/nixos.qcow2,format=qcow2,if=virtio,snapshot=on \
	  -netdev user,id=n0,hostfwd=tcp::8001-:8000 -device virtio-net-pci,netdev=n0 \
	  -nographic

# ---- examples -------------------------------------------------------------

# make example-check [EXAMPLE=acme] — validates an example deployment with the
# same rules the distribution enforces on itself.
EXAMPLE ?= acme
example-check:
	python3 scripts/check_agent.py examples/$(EXAMPLE)

# Both halves of the capability system: the grants, and the classification.
policy:
	./test/agent-policy.sh
	@echo
	./test/clearance-policy.sh

# ---- the whole suite ------------------------------------------------------
#
# `make test` needs nothing but python3: no Docker, no network, no model. It is
# what CI runs on every push. `make test-full` adds the checks that need Docker
# (a live runner, the NixOS evaluation) and the Mojo toolchain.

MOJO ?= $(shell command -v mojo 2>/dev/null || echo .venv-mojo/bin/mojo)

lint:
	@if command -v ruff >/dev/null 2>&1; then R=ruff; \
	 elif command -v uvx >/dev/null 2>&1; then R="uvx ruff"; \
	 else echo "lint: ruff not found (pip install ruff, or install uv)"; exit 1; fi; \
	 $$R check --select F,E9,B --exclude '.venv*,training/.venv*,build' .

# Every .mojo file in the repo must compile. Four agent entrypoints once sat in
# obsolete syntax for weeks because nothing ever built them.
mojo-build:
	@test -x "$(MOJO)" || { echo "mojo-build: no Mojo toolchain (pip install modular)"; exit 1; }
	@fail=0; for f in $$(find agents examples training scripts -name '*.mojo' | sort); do \
	   if $(MOJO) build "$$f" -o /tmp/ainix-mojo-check.bin >/tmp/ainix-mojo.log 2>&1; then :; \
	   else echo "FAIL $$f"; grep error: /tmp/ainix-mojo.log | head -3; fail=1; fi; \
	 done; test $$fail = 0 && echo "all .mojo files compile"

test: lint agent-check policy
	@$(MAKE) --no-print-directory example-check EXAMPLE=acme
	@$(MAKE) --no-print-directory example-check EXAMPLE=globex
	@echo "\nmake test: all passed"

# Boots the real image and reads the verdict it prints about itself.
boot-check:
	./test/boot-check.sh

# Start a runner on a port that is actually free, smoke it, remove it. `smoke`
# on its own assumes a runner is already up on :8000 — on a machine where some
# other app holds :8000 that is a test of the other app.
runner-check:
	@port=$$(for p in $$(seq 8090 8199); do lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1 || { echo $$p; break; }; done); \
	 echo "runner-check on :$$port"; \
	 $(MAKE) --no-print-directory run PORT=$$port NAME=ainix-runner-check >/dev/null && \
	 $(MAKE) --no-print-directory smoke PORT=$$port NAME=ainix-runner-check; rc=$$?; \
	 docker rm -f ainix-runner-check >/dev/null 2>&1; exit $$rc

test-full: test mojo-build os-eval runner-check boot-check
