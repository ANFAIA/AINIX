# A self-test the image runs on itself, when booted with `ainix.selftest`.
#
# Proving the agent plane works used to mean typing into the login prompt of a
# VM with `sleep` between keystrokes. This checks from inside, deterministically:
# the broker is up, every generated agent unit is running, the console agent
# passes its probe, and a process that is NOT an agent is refused by uid. Then
# it prints one verdict line to the console and powers off.
{ config, lib, pkgs, ... }:

let
  cfg = config.ainix.agentd;
  probe = "${cfg.root}/agents/system/agentd/probe.py";
  py = "${pkgs.python3}/bin/python3";

  # The agent units the image is SUPPOSED to run, known at evaluation time.
  # Discovering them at runtime with `systemctl list-units` found none in the
  # first version — so the loop checked nothing and the test passed anyway.
  expected = lib.filter (n: lib.hasPrefix "ainix-agent-" n)
    (lib.attrNames config.systemd.services);
in
{
  systemd.services.ainix-selftest = lib.mkIf cfg.enable {
    description = "AINIX self-test (only with ainix.selftest on the kernel command line)";
    wantedBy = [ "multi-user.target" ];
    after = [ "ainix-agents.target" "ainix-agentd.service" ];
    unitConfig.ConditionKernelCommandLine = "ainix.selftest";
    serviceConfig = {
      Type = "oneshot";
      StandardOutput = "journal+console";
      StandardError = "journal+console";
    };
    path = with pkgs; [ systemd sudo coreutils gnugrep ];
    script = ''
      fail=0
      say() { echo "AINIX-SELFTEST $*"; }
      check() { if eval "$2" >/dev/null 2>&1; then say "ok   $1"; else say "FAIL $1"; fail=1; fi; }

      # Give agents a moment to register after the target is reached.
      for _ in $(seq 30); do
        systemctl is-active --quiet ainix-agentd && break; sleep 1
      done
      sleep 3

      check "agentd is active" "systemctl is-active --quiet ainix-agentd"
      ${lib.concatMapStrings (u: ''
        check "${u} is active" "systemctl is-active --quiet ${u}"
      '') expected}
      check "at least one agent unit exists" "[ ${toString (lib.length expected)} -gt 0 ]"
      check "console agent passes its probe" \
        "sudo -u ainix-user-shell AINIX_SOCK=${cfg.socket} ${py} ${probe}"
      # nobody is in the broker's group? Then use a group member that is not an
      # agent: the human login user. It must be refused by uid.
      check "a non-agent uid cannot act as an agent" \
        "! sudo -u ainix AINIX_SOCK=${cfg.socket} ${py} ${probe}"
      check "the refusal names the uid" \
        "journalctl -u ainix-agentd -o cat | grep -q 'peer uid .* is not ainix-user-shell'"

      if [ $fail = 0 ]; then say "PASS"; else say "FAIL"; fi
      systemctl poweroff --no-block
    '';
  };
}
