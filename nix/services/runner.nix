# The model runner: one shared llama.cpp serving the OpenAI endpoint on :8000.
#
# Shared on purpose. Agents do not each load weights — N agents times a 2 B
# model is out of memory, and worse on a GPU. Agents get scoped access to this
# endpoint instead.
#
# v1 runs llama.cpp as a hardened systemd service rather than an OCI container.
# The container path arrives with agentd, which is what needs per-agent
# sandboxing; a single runner does not, and a systemd service is fully
# declarative with no registry pull at boot. Recorded in docs/FINDINGS.md so
# the deviation from the architecture is visible rather than quietly assumed.
{ config, lib, pkgs, ... }:

let
  cfg = config.ainix.runner;
  inherit (lib) mkOption types mkIf;
in
{
  options.ainix = {
    profile = mkOption {
      type = types.enum [ "cpu" "nvidia" "amd" ];
      default = "cpu";
      description = "Which accelerator HAL this image carries.";
    };
    runner = {
      enable = mkOption { type = types.bool; default = true; };
      device = mkOption {
        type = types.enum [ "cpu" "gpu" ];
        default = "cpu";
        description = "Set by the hardware profile, not by hand.";
      };
      port = mkOption { type = types.port; default = 8000; };
      listen = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = ''
          Where the runner listens. Loopback by default, because agentd is the
          only intended client: a runner on 0.0.0.0 with its port open in the
          firewall let anyone on the network use the model directly, with no
          grant, no identity and no audit line — the whole capability system
          bypassed by one TCP connection. Exposing it is a deliberate act, and
          belongs behind something that authenticates.
        '';
      };
      weightsDir = mkOption { type = types.path; default = "/var/lib/ainix/weights"; };
      modelFile = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = ''
          Serve this GGUF directly instead of the model first boot chose. For
          images that must serve without a human answering a question — the
          self-test image uses it with a 19 MB model, so the whole path from
          agent to runner is exercised on every boot check.
        '';
      };
      threads = mkOption { type = types.int; default = 0; };  # 0 = llama.cpp default
      contextSize = mkOption {
        type = types.ints.positive;
        default = 4096;
        description = ''
          Tokens of context per request, as the development container sets.
          Left unset, llama.cpp b11151 takes the model's training context: for
          Qwen3.5 that is 262,144 tokens per slot, 518,912 across four — a KV
          cache sized for a document nobody sends, on a machine meant to be
          minimal. For a tiny model it goes the other way: stories15M trains at
          128 tokens and rejected the first real prompt.
        '';
      };
    };
  };

  config = mkIf cfg.enable {
    systemd.services.ainix-runner = {
      description = "AINIX model runner (llama.cpp, OpenAI endpoint)";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      # The runner cannot start without weights, and downloading them is
      # firstboot's job — where a human is watching the progress bar. A start
      # path that silently pulls gigabytes is a start path that hangs.
      unitConfig.ConditionPathExists =
        lib.mkIf (cfg.modelFile == null) "/var/lib/ainix/state.toml";

      serviceConfig = {
        Type = "exec";
        ExecStart = pkgs.writeShellScript "ainix-runner-start" ''
          set -eu
          ${if cfg.modelFile != null then ''
          model_path=${cfg.modelFile}
          '' else ''
          model=$(${pkgs.python3}/bin/python3 -c "
import tomllib
s=tomllib.load(open('/var/lib/ainix/state.toml','rb'))
cat=tomllib.load(open('/etc/ainix/models.toml','rb'))
print(cat[s['model']['default']]['file'])")
          model_path=${cfg.weightsDir}/"$model"
          ''}
          exec ${pkgs.llama-cpp}/bin/llama-server \
            --model "$model_path" \
            --host ${cfg.listen} --port ${toString cfg.port} \
            --jinja \
            --ctx-size ${toString cfg.contextSize} \
            ${lib.optionalString (cfg.threads > 0) "--threads ${toString cfg.threads}"} \
            ${lib.optionalString (cfg.device == "gpu") "--n-gpu-layers 999"}
        '';
        Restart = "always";
        RestartSec = 5;

        # Hardening. The runner reads weights and answers HTTP; it has no
        # business anywhere else on the filesystem.
        # No StateDirectory: the runner writes nothing. It used to declare
        # StateDirectory=ainix under DynamicUser, which makes systemd migrate
        # /var/lib/ainix into /var/lib/private — the directory first boot
        # writes its state and weights into, as root.
        DynamicUser = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        SystemCallFilter = [ "@system-service" ];
        ReadOnlyPaths = [ cfg.weightsDir ];
        # GPU profiles need the device nodes; the CPU profile gets nothing.
        PrivateDevices = cfg.device == "cpu";
        DeviceAllow = lib.optionals (cfg.device == "gpu") [
          "/dev/nvidiactl rw" "/dev/nvidia0 rw" "/dev/nvidia-uvm rw"
          "/dev/kfd rw" "/dev/dri rw"
        ];
      };
    };

    # Opened only when the runner is deliberately exposed.
    networking.firewall.allowedTCPPorts =
      lib.optionals (cfg.listen != "127.0.0.1" && cfg.listen != "::1") [ cfg.port ];
    systemd.tmpfiles.rules = [ "d ${cfg.weightsDir} 0755 root root -" ];
  };
}
