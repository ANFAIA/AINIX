# AMD profile — the HAL for ROCm hardware.
#
# UNVERIFIED, for the same reason as the NVIDIA profile: no AMD card here.
{ config, lib, pkgs, ... }:
{
  ainix.profile = "amd";
  ainix.runner.device = "gpu";

  hardware.graphics.enable = true;
  hardware.amdgpu.opencl.enable = true;
  systemd.tmpfiles.rules = [
    # ROCm expects these to exist before the runtime opens them.
    "d /dev/kfd 0666 root root -"
  ];
  users.groups.render = { };
  users.users.ainix.extraGroups = [ "render" "video" ];

  boot.kernelParams = [ "amd_iommu=on" ];
  boot.initrd.kernelModules = [ "amdgpu" ];
}
