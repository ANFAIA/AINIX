# AINIX — POC targets.
ENGINE      ?= llamacpp        # llamacpp | max  — see docs/FINDINGS.md
ACCEL       ?= cpu
IMAGE       ?= ainix/runtime:$(ACCEL)-$(ENGINE)
WEIGHTS     ?= $(HOME)/.cache/ainix/weights
GGUF        ?= gemma-3-1b-it-Q4_K_M.gguf
MODEL       ?= unsloth/gemma-3-1b-it
PORT        ?= 8000
NAME        ?= ainix-runner
HF_CACHE    ?= $(HOME)/.cache/huggingface
MAX_CACHE   ?= $(HOME)/.cache/ainix/max

.PHONY: image run stop logs smoke bench clean agent-new agent-check agents models fetch firstboot os-eval os-build os-boot skills

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
