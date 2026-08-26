# Where the system lives on disk.
#
# Labels rather than device names or UUIDs: the same image has to boot as a
# QEMU virtio disk, as an NVMe drive, and off a USB stick, and only a label
# survives all three.
{ config, lib, pkgs, modulesPath, ... }:

{
  # A RAM-booted or image-generated system defines its own layout and has no
  # ESP to mount. Leaving these definitions in place there sends the boot to
  # emergency mode on a /boot that was never supposed to exist.
  options.ainix.disk.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    description = "Define the on-disk layout. False for netboot/RAM images.";
  };

  config = lib.mkIf config.ainix.disk.enable {
    # mkDefault throughout: an image generator (nixos-generators' qcow format,
    # or an installer) defines its own layout and must win. These values are the
    # bare-metal fallback, not an assertion.
    fileSystems."/" = lib.mkDefault {
      device = "/dev/disk/by-label/ainix-root";
      fsType = "ext4";
      options = [ "noatime" ];   # weight files are read constantly; timestamps are noise
    };

    fileSystems."/boot" = lib.mkDefault {
      device = "/dev/disk/by-label/ESP";
      fsType = "vfat";
    };

    boot.loader.systemd-boot.enable = lib.mkDefault true;   # no GRUB to configure
    boot.loader.efi.canTouchEfiVariables = lib.mkDefault false;
    boot.loader.timeout = lib.mkDefault 1;

    # Only what is needed to find and mount the root device.
    boot.initrd.availableKernelModules = [ "virtio_pci" "virtio_blk" "virtio_scsi" "nvme" "ahci" "usbhid" "sd_mod" ];

    swapDevices = [ ];   # deliberately none — see vm.swappiness in tuning.nix
  };
}
