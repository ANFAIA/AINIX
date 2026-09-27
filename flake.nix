{
  description = "AINIX — a Linux distribution stripped to the minimum that runs AI inference";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    nixos-generators = {
      url = "github:nix-community/nixos-generators";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixos-generators }:
    let
      # The profile is the HAL: it decides which accelerator driver and
      # userspace the image carries. Everything above it is identical.
      systems = [ "aarch64-linux" "x86_64-linux" ];

      # One module list, used by both the bootable system and the disk image,
      # so the artefact and the thing that boots in QEMU cannot drift apart.
      modulesFor = profile: [
        ./nix/base.nix
        ./nix/disk.nix
        ./nix/kernel.nix
        ./nix/tuning.nix
        ./nix/services/runner.nix
        ./nix/services/agentd.nix
        ./nix/services/agents.nix
        ./nix/services/core.nix
        ./nix/services/selftest.nix
        ./nix/services/firstboot.nix
        (./nix/profiles + "/${profile}.nix")
      ];

      # What the image is built from: the parts it executes, not the repo.
      # Referencing ./. put the whole tree in the world-readable Nix store —
      # docs, training scripts, and examples/acme/documents with its
      # "restricted" fixture. Documents in particular must never enter the
      # store: nothing there can be kept from any process on the machine.
      ainixSrc = nixpkgs.lib.fileset.toSource {
        root = ./.;
        fileset = nixpkgs.lib.fileset.unions [
          ./agents
          ./skills
          ./models.toml
          ./scripts/check_agent.py
          ./scripts/fetch-model.sh
        ];
      };

      mkSystem = { system, profile ? "cpu", extra ? [ ] }:
        nixpkgs.lib.nixosSystem {
          inherit system;
          modules = modulesFor profile ++ extra;
          specialArgs = { inherit ainixSrc; };
        };

      forAll = f: nixpkgs.lib.genAttrs systems f;
    in
    {
      nixosConfigurations = {
        # Boot-testable on this machine: `nix run .#vm-aarch64`
        ainix-cpu-aarch64 = mkSystem { system = "aarch64-linux"; profile = "cpu"; };
        ainix-cpu-x86_64 = mkSystem { system = "x86_64-linux"; profile = "cpu"; };
        # Boots entirely from RAM: kernel + initrd, no disk, no bootloader.
        # This is the boot test that works on a Mac — building a disk image
        # needs KVM, which Docker Desktop does not provide.
        ainix-netboot-aarch64 = mkSystem {
          system = "aarch64-linux";
          profile = "cpu";
          extra = [
            ({ modulesPath, ... }: {
              imports = [ (modulesPath + "/installer/netboot/netboot.nix") ];
              ainix.disk.enable = false;   # no disk at all: kernel + initrd only
              ainix.firstboot.tty = "ttyAMA0";   # serial is the only console here
              # A boot check cannot answer a question. firstboot owns the
              # console until a human does, which is right on a real machine.
              ainix.firstboot.enable = false;
            })
            # A 105 MB instruct model, fetched by hash, so the self-test
            # exercises the runner and the full agent -> agentd -> model path on
            # every boot check. The runner never served on the image before
            # this. Not the 19 MB stories15M: it trains at 128 tokens of
            # context, and llama.cpp caps each slot there, so shell-expert's
            # real system prompt (348 tokens) was rejected outright.
            ({ pkgs, ... }: {
              ainix.runner.modelFile = pkgs.fetchurl {
                url = "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_M.gguf";
                hash = "sha256-LoBAzq54Favg3LNUC5mV6qH6DSyp55fQpjWuRDPGjC0=";
              };
            })
          ];
        };

        # Written, but untestable without the hardware — see docs/FINDINGS.md.
        ainix-nvidia = mkSystem { system = "x86_64-linux"; profile = "nvidia"; };
        ainix-amd = mkSystem { system = "x86_64-linux"; profile = "amd"; };
      };

      packages = forAll (system:
        let
          arch = if system == "aarch64-linux" then "aarch64" else "x86_64";
          cfg = self.nixosConfigurations."ainix-cpu-${arch}";
        in
        {
          # A runnable QEMU boot of the real configuration. This is the fast
          # feedback loop — no disk image, boots in seconds.
          vm = cfg.config.system.build.vm;

          # The shippable artefact.
          qcow2 = nixos-generators.nixosGenerate {
            inherit system;
            format = "qcow";
            modules = modulesFor "cpu";
            specialArgs = { inherit ainixSrc; };
          };

          # kernel + initrd side by side, ready for `qemu -kernel -initrd`.
          netboot =
            let nb = self.nixosConfigurations.ainix-netboot-aarch64.config.system.build;
            in nixpkgs.legacyPackages.${system}.runCommand "ainix-netboot" { } ''
              mkdir -p $out
              ln -s ${nb.kernel}/Image $out/kernel
              ln -s ${nb.netbootRamdisk}/initrd $out/initrd
              echo "init=${nb.toplevel}/init ${toString cfg.config.boot.kernelParams}" > $out/cmdline
            '';

          default = cfg.config.system.build.toplevel;
        });
    };
}
