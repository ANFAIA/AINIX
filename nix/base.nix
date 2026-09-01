# What a machine needs to boot, reach a shell, and run a model. Nothing else.
#
# Every removal here is deliberate. A distribution for inference does not need
# a documentation set, a printer stack, or a sound server, and each one it
# carries is memory it cannot give to a model.
{ config, lib, pkgs, ainixSrc, ... }:

{
  system.stateVersion = "25.05";

  # --- what is NOT here -----------------------------------------------------
  documentation.enable = false;          # ~200 MB of man/info/doc
  documentation.nixos.enable = false;
  services.xserver.enable = false;
  services.pulseaudio.enable = false;
  services.printing.enable = false;
  programs.command-not-found.enable = false;   # pulls a channel database
  security.polkit.enable = lib.mkDefault false;
  xdg.autostart.enable = false;
  xdg.mime.enable = false;
  xdg.icons.enable = false;
  fonts.fontconfig.enable = false;

  # systemd's own optional units. An inference box has no removable media, no
  # OSTree, and no user sessions to speak of.
  systemd.services.systemd-udev-settle.enable = false;
  systemd.services.NetworkManager-wait-online.enable = false;

  # --- what IS here ---------------------------------------------------------
  environment.systemPackages = with pkgs; [
    curl            # firstboot's connectivity probe and model download
    jq              # the runner speaks JSON; so does every agent
    python3         # the interop half of the Mojo-first agents
    llama-cpp       # the model runner itself
  ];

  # Network configuration is a first-boot question, so the tools firstboot
  # offers must actually exist on the image — it only lists what it finds.
  networking.networkmanager.enable = true;
  networking.hostName = "ainix";

  # Immutable-ish: the system closure is read-only, state is explicit.
  users.mutableUsers = false;
  users.users.ainix = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    initialPassword = "ainix";   # POC only — replace with a hashed password
  };
  security.sudo.wheelNeedsPassword = false;

  # Serial console, because the first place this boots is a VM. Order matters:
  # the LAST console= wins for /dev/console, so the serial one goes last or the
  # boot log never leaves the virtual screen.
  boot.kernelParams = [ "console=tty0" "console=ttyAMA0,115200" ];

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # The catalog and the first-boot agent travel with the system.
  environment.etc."ainix/models.toml".source = "${ainixSrc}/models.toml";
  environment.etc."ainix/firstboot".source = "${ainixSrc}/agents/system/firstboot";
  # A self-check a human can run on the booted machine: register with agentd,
  # ask for a skill, list who is home.
  environment.etc."ainix/probe.py".source = "${ainixSrc}/agents/system/agentd/probe.py";
  environment.etc."ainix/fetch-model.sh" = {
    source = "${ainixSrc}/scripts/fetch-model.sh";
    mode = "0755";
  };
}
