# First boot runs before the login prompt, on the console, exactly once.
#
# Ordering is the whole point: a machine that reaches a login prompt before
# anyone has said which model it should run has already made the decision for
# the user.
{ config, lib, pkgs, ... }:

let cfg = config.ainix.firstboot; in
{
  options.ainix.firstboot.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = ''
      Ask on first boot. A test image turns this off: firstboot owns the
      console until a human answers, which is right for a real machine and
      wrong for an automated boot check.
    '';
  };

  options.ainix.firstboot.tty = lib.mkOption {
    type = lib.types.str;
    default = "tty1";
    example = "ttyAMA0";
    description = ''
      Which terminal first boot owns. It must be the one a human is actually
      looking at: on a serial-only machine, asking the question on tty1 means
      asking it where nobody can see or answer it.
    '';
  };

  config = lib.mkIf cfg.enable {
  systemd.services.ainix-firstboot = {
    description = "AINIX first-boot setup (network, then model)";
    wantedBy = [ "multi-user.target" ];
    before = [ "getty@${cfg.tty}.service" "serial-getty@${cfg.tty}.service" "ainix-runner.service" ];
    after = [ "network.target" "systemd-user-sessions.service" ];
    conflicts = [ "getty@${cfg.tty}.service" "serial-getty@${cfg.tty}.service" ];

    # Runs once. The state file it writes is its own guard.
    unitConfig.ConditionPathExists = "!/var/lib/ainix/state.toml";

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.python3}/bin/python3 /etc/ainix/firstboot/firstboot.py";
      Environment = [
        "AINIX_STATE=/var/lib/ainix/state.toml"
        "AINIX_WEIGHTS=/var/lib/ainix/weights"
        "AINIX_CATALOG=/etc/ainix/models.toml"
        # Derived from __file__ on a checkout, but the image puts the script at
        # /etc/ainix/firstboot and the fetcher somewhere else entirely.
        "AINIX_FETCH=/etc/ainix/fetch-model.sh"
        "PATH=${lib.makeBinPath (with pkgs; [ curl networkmanager coreutils ])}"
      ];

      # It is an interactive console program; it needs the tty it is asking on.
      StandardInput = "tty";
      StandardOutput = "tty";
      StandardError = "journal";
      TTYPath = "/dev/${cfg.tty}";
      TTYReset = true;
      TTYVHangup = true;
    };
  };
  };
}
