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
    path = with pkgs; [ systemd sudo coreutils gnugrep iptables llama-cpp curl findutils nix ];
    script = ''
      fail=0
      say() { echo "AINIX-SELFTEST $*"; }
      # A failure prints the last lines of what the check said: a verdict of
      # FAIL with no reason sends whoever reads it back into the VM to find one.
      check() {
        if out=$(eval "$2" 2>&1); then say "ok   $1"
        else say "FAIL $1"; printf '%s\n' "$out" | tail -4 | sed 's/^/AINIX-SELFTEST        /'; fail=1; fi
      }

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
      # The property, not the label: a nixpkgs build carries no git metadata
      # and reports "build 0", so the version string proves nothing. What
      # matters is that this engine can load the catalog's Qwen3.5 models,
      # which the b5311 nixpkgs ships could not ("unknown architecture qwen35").
      check "the image's llama.cpp knows the qwen35 architecture" \
        "grep -q qwen35 ${pkgs.llama-cpp}/lib/libllama.so"
      check "the runner port is not open to the network" \
        "! iptables -S 2>/dev/null | grep -q -- '--dport ${toString config.ainix.runner.port}'"
      ${lib.optionalString (config.ainix.runner.modelFile != null) ''
      for _ in $(seq 60); do curl -fsS http://127.0.0.1:${toString config.ainix.runner.port}/health >/dev/null 2>&1 && break; sleep 1; done
      check "the runner serves, on loopback" \
        "curl -fsS http://127.0.0.1:${toString config.ainix.runner.port}/health"
      check "agent units may open Unix sockets only" \
        "systemctl show -p RestrictAddressFamilies ainix-agent-app-shell-expert | grep -qx 'RestrictAddressFamilies=AF_UNIX'"
      check "console -> shell-expert -> model, end to end" \
        "sudo -u ainix-user-shell AINIX_SOCK=${cfg.socket} PYTHONPATH=${cfg.root}/agents/lib ${py} ${cfg.root}/agents/system/agentd/e2e.py ${cfg.root}"
      ''}
      # Nothing classified may live in the store: every process can read it.
      # Both checks below pass by finding nothing, so first prove the closure
      # was actually listed — an empty list would make them pass vacuously.
      check "the system closure can be listed" \
        "[ \$(nix-store -qR /run/current-system | wc -l) -gt 100 ]"
      check "no documents directory anywhere in the system closure" \
        "! for p in \$(nix-store -qR /run/current-system); do [ -d \"\$p\" ] && find \"\$p\" -maxdepth 4 -type d -name documents; done | grep -q ."
      check "the repository is not in the image, only what it runs" \
        "! for p in \$(nix-store -qR /run/current-system | grep -- -source\$); do [ -e \"\$p/training\" ] && echo \$p; done | grep -q ."
      check "the refusal names the uid" \
        "journalctl -u ainix-agentd -o cat | grep -q 'peer uid .* is not ainix-user-shell'"

      if [ $fail = 0 ]; then say "PASS"; else say "FAIL"; fi
      systemctl poweroff --no-block
    '';
  };
}
