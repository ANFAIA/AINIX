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
      weightsDir = mkOption { type = types.path; default = "/var/lib/ainix/weights"; };
      threads = mkOption { type = types.int; default = 0; };  # 0 = llama.cpp default
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
      unitConfig.ConditionPathExists = "/var/lib/ainix/state.toml";

      serviceConfig = {
        Type = "exec";
        ExecStart = pkgs.writeShellScript "ainix-runner-start" ''
          set -eu
          model=$(${pkgs.python3}/bin/python3 -c "
import tomllib,sys
s=tomllib.load(open('/var/lib/ainix/state.toml','rb'))
cat=tomllib.load(open('/etc/ainix/models.toml','rb'))
name=s['model']['default']
print(cat[name]['file'])")
          exec ${pkgs.llama-cpp}/bin/llama-server \
            --model ${cfg.weightsDir}/"$model" \
            --host 0.0.0.0 --port ${toString cfg.port} \
            ${lib.optionalString (cfg.threads > 0) "--threads ${toString cfg.threads}"} \
            ${lib.optionalString (cfg.device == "gpu") "--n-gpu-layers 999"}
        '';
        Restart = "always";
        RestartSec = 5;

        # Hardening. The runner reads weights and answers HTTP; it has no
        # business anywhere else on the filesystem.
        DynamicUser = true;
        StateDirectory = "ainix";
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

    networking.firewall.allowedTCPPorts = [ cfg.port ];
    systemd.tmpfiles.rules = [ "d ${cfg.weightsDir} 0755 root root -" ];
  };
}
