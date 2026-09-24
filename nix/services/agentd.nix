# agentd — the broker, started before anything that depends on it.
#
# It is the only process that knows where anything is: the model endpoint, each
# peer's queue, the document store. Agents hold manifests and ask; agentd holds
# addresses and answers. That is what makes a manifest enforceable rather than
# advisory, so it has to be up before a single agent registers.
{ config, lib, pkgs, ainixSrc, ... }:

let
  cfg = config.ainix.agentd;
  inherit (lib) mkOption mkIf types;

  # The agent tree, its base library, the skills, and the document store travel
  # into the image as one closure. agentd resolves everything relative to this.
  plane = pkgs.runCommand "ainix-agent-plane" { } ''
    mkdir -p $out
    cp -r ${ainixSrc}/agents      $out/agents
    cp -r ${ainixSrc}/skills      $out/skills
    cp    ${ainixSrc}/models.toml $out/models.toml
    ${lib.optionalString (builtins.pathExists (ainixSrc + "/groups.toml"))
      "cp ${ainixSrc}/groups.toml $out/groups.toml"}

    # The same validator CI runs, as a build step: an image whose agent tree
    # contains an illegal grant, an undeclared model, a user agent with
    # clearance, or a skill its tier cannot see does not build at all.
    ${pkgs.python3}/bin/python3 ${ainixSrc}/scripts/check_agent.py $out
  '';
in
{
  options.ainix.agentd = {
    enable = mkOption { type = types.bool; default = true; };
    socket = mkOption {
      type = types.path;
      default = "/run/ainix/agentd.sock";
      description = "Where agents reach the broker. A Unix socket, so reaching it is a filesystem permission and not a network one.";
    };
    root = mkOption {
      type = types.path;
      default = plane;
      description = "The agent plane: agents, skills, catalog, and documents.";
    };
  };

  config = mkIf cfg.enable {
    systemd.services.ainix-agentd = {
      description = "AINIX agentd — registry, discovery, capability broker";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      # Agents are useless without it and the runner is useless to them, so the
      # ordering is: runner, broker, agents.
      before = [ "ainix-agents.target" ];
      wants = [ "ainix-runner.service" ];

      environment = {
        AINIX_SOCK = cfg.socket;
        AINIX_ROOT = "${cfg.root}";
        AINIX_RUNNER = "http://127.0.0.1:${toString config.ainix.runner.port}";
        # Every agent on the image runs as its own ainix-<tier>-<name> user
        # (nix/services/agents.nix), so a name is accepted only from that uid.
        AINIX_IDENTITY = "uid";
        # Out of the Nix store, which every process can read. Provisioned by
        # the deployment, never built into the image.
        AINIX_DOCUMENTS = "/var/lib/ainix-agentd/documents";
        PYTHONPATH = "${cfg.root}/agents/lib";
        # systemd services get no LANG, so Python falls back to ASCII and the
        # first SKILL.md with an em dash kills the read. The code says utf-8
        # explicitly everywhere now; this covers anything that does not.
        PYTHONUTF8 = "1";
      };

      serviceConfig = {
        Type = "exec";
        ExecStart = "${pkgs.python3}/bin/python3 ${cfg.root}/agents/system/agentd/agentd.py";
        Restart = "always";
        RestartSec = 2;

        # The broker is the thing that enforces the rules, so it gets the
        # tightest confinement of anything on the machine. It needs one socket
        # directory and a read-only view of the plane; nothing else.
        #
        # NOT DynamicUser: a transient uid owns the socket and nothing else can
        # reach it, which makes the broker unreachable by the agents that exist
        # to talk to it. A fixed `ainix` group is the thing agents are added to,
        # and membership in that group is what "may speak to the broker" means.
        User = "ainix-agentd";
        Group = "ainix";
        RuntimeDirectory = "ainix";
        RuntimeDirectoryMode = "0770";
        # Its own state directory. It used to share StateDirectory=ainix, and
        # systemd hands a StateDirectory to the unit's user: /var/lib/ainix —
        # first boot's state and the model weights — became ainix-agentd's.
        StateDirectory = "ainix-agentd";
        StateDirectoryMode = "0700";
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" ];
        SystemCallFilter = [ "@system-service" ];
        ReadOnlyPaths = [ "${cfg.root}" ];
      };
    };

    users.groups.ainix = { };
    users.users.ainix-agentd = {
      isSystemUser = true;
      group = "ainix";
      description = "AINIX capability broker";
    };
    # A human at the console is talking to agents, so they need the group too.
    users.users.ainix.extraGroups = [ "ainix" ];

    # Agents are ordered against this rather than against agentd directly, so a
    # deployment can add one without editing the broker's unit.
    systemd.targets.ainix-agents = {
      description = "AINIX agents";
      wantedBy = [ "multi-user.target" ];
      after = [ "ainix-agentd.service" ];
    };

    environment.systemPackages = [
      (pkgs.writeShellScriptBin "ainix" ''
        # The console, for a human at the machine. It runs as the user/shell
        # agent's own uid: agentd binds names to uids, so a human operating the
        # console borrows the console's identity — and its grants, which are
        # deliberately the smallest on the machine — never their own.
        if [ "$(id -un)" != "ainix-user-shell" ]; then
          exec /run/wrappers/bin/sudo -u ainix-user-shell --preserve-env=TERM "$0" "$@"
        fi
        export AINIX_SOCK=${cfg.socket}
        export AINIX_ROOT=${cfg.root}
        export PYTHONPATH=${cfg.root}/agents/lib
        cd ${cfg.root}/agents/user/shell
        exec ${pkgs.python3}/bin/python3 -c '
import sys
from ainix_agent import Agent
a = Agent.from_manifest("agent.toml")
print(f"{a.name} — ask, or ^D")
while True:
    line = a.readline(a.prompt())
    if not line:
        break
    try:
        print(a.peer("app/shell-expert").task("shell.ask", line))
    except Exception as e:
        print(f"refused: {e}")
'
      '')
    ];
  };
}
