# One systemd unit per agent, generated from the agent tree.
#
# Nobody writes these by hand. Each app and system agent in `agents/` gets a
# service and its own system user, `ainix-<tier>-<name>`, in the `ainix` group.
# That user is the agent's identity: agentd runs with AINIX_IDENTITY=uid and
# accepts a name only from the matching uid, read from the kernel with
# SO_PEERCRED. A compromised agent can use its own grants and nobody else's.
#
# User-tier agents get a user but no service — they are surfaces a human opens
# (`ainix`), not daemons.
{ config, lib, pkgs, ... }:

let
  cfg = config.ainix.agentd;
  plane = cfg.root;

  # The broker and first boot have units of their own.
  special = [ "system/agentd" "system/firstboot" ];

  tierDirs = tier:
    let dir = plane + "/agents/${tier}"; in
    if builtins.pathExists dir then
      lib.filter (n: builtins.pathExists (dir + "/${n}/agent.toml"))
        (builtins.attrNames (lib.filterAttrs (_: t: t == "directory")
          (builtins.readDir dir)))
    else [ ];

  agents = lib.concatMap (tier:
    map (name: {
      inherit tier name;
      id = "${tier}/${name}";
      unix = "ainix-${tier}-${name}";
      manifest = builtins.fromTOML
        (builtins.readFile (plane + "/agents/${tier}/${name}/agent.toml"));
    }) (tierDirs tier)) [ "user" "app" "system" ];

  daemons = lib.filter (a: a.tier != "user" && !(lib.elem a.id special)) agents;

  memOf = a: a.manifest.quota.memory or "512Mi";
  # "512Mi" -> "512M": systemd wants K/M/G, manifests use the Kubernetes spelling.
  toSystemd = q: lib.replaceStrings [ "Ki" "Mi" "Gi" ] [ "K" "M" "G" ] q;
in
{
  config = lib.mkIf cfg.enable {
    # The broker and first boot run as their own service users; giving them an
    # agent identity as well would be a second way to be them.
    users.users = lib.listToAttrs (map (a: lib.nameValuePair a.unix {
      isSystemUser = true;
      group = "ainix";
      description = "AINIX agent ${a.id}";
    }) (lib.filter (a: !(lib.elem a.id special)) agents));

    systemd.services = lib.listToAttrs (map (a:
      lib.nameValuePair "ainix-agent-${a.tier}-${a.name}" {
        description = "AINIX agent ${a.id} — ${a.manifest.agent.domain or ""}";
        wantedBy = [ "ainix-agents.target" ];
        partOf = [ "ainix-agents.target" ];
        after = [ "ainix-agentd.service" ];
        requires = [ "ainix-agentd.service" ];

        environment = {
          AINIX_SOCK = cfg.socket;
          PYTHONPATH = "${plane}/agents/lib";
          PYTHONUTF8 = "1";
        };

        serviceConfig = {
          Type = "exec";
          User = a.unix;
          Group = "ainix";
          ExecStart = "${pkgs.python3}/bin/python3 ${plane}/agents/lib/run_agent.py ${plane}/agents/${a.tier}/${a.name}";
          Restart = "always";
          RestartSec = 3;

          # The manifest's quota, enforced by the kernel rather than hoped for.
          MemoryMax = toSystemd (memOf a);
          CPUQuota = "${toString ((lib.toInt (a.manifest.quota.cpu or "1")) * 100)}%";

          # An agent reaches the world only through agentd. It needs the broker's
          # socket and a read-only view of its own directory.
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
          # AF_UNIX only: no agent opens a network socket of its own. Model
          # calls, peers, documents and tools all go through the broker.
          RestrictAddressFamilies = [ "AF_UNIX" ];
          IPAddressDeny = "any";
          SystemCallFilter = [ "@system-service" ];
          ReadOnlyPaths = [ "${plane}" ];
        };
      }) daemons);
  };
}
