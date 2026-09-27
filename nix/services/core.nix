# The operating system's runtime core: the model runner, the broker, and the
# decision layer. Nothing else in AINIX is useful without all three, so they
# start together, before any agent, as one target.
#
# Laya is here rather than among the agents because deciding what runs is the
# OS's job, the way ART is Android's: the shell does not name the agent that
# answers a question — it asks, and the core decides. Laya still runs as its
# own uid under agentd's rules; being part of the core is about when it starts
# and what depends on it, not about what it may do.
{ config, lib, ... }:

{
  config = lib.mkIf config.ainix.agentd.enable {
    systemd.targets.ainix-core = {
      description = "AINIX core: model runner, agentd, Laya";
      wantedBy = [ "multi-user.target" ];
      wants = [ "ainix-runner.service" "ainix-agentd.service"
                "ainix-agent-system-laya.service" ];
      after = [ "ainix-runner.service" "ainix-agentd.service"
                "ainix-agent-system-laya.service" ];
    };

    # Laya comes up with the broker, not with the rest of the agents.
    systemd.services.ainix-agent-system-laya = {
      wantedBy = lib.mkForce [ "ainix-core.target" ];
      partOf = lib.mkForce [ "ainix-core.target" ];
      before = [ "ainix-agents.target" ];
    };

    # Every other agent starts after the core is up.
    systemd.targets.ainix-agents.after = [ "ainix-core.target" ];
  };
}
