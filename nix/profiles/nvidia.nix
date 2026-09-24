# NVIDIA profile — the HAL for CUDA hardware.
#
# UNVERIFIED. Written from the documented interfaces; never booted, because
# this repository has no NVIDIA hardware attached. Treat every line as a
# hypothesis until it boots on a real card. See docs/FINDINGS.md.
{ config, lib, pkgs, ... }:
{
  ainix.profile = "nvidia";

  # The driver is unfree, and nixpkgs refuses to evaluate it — this profile
  # never evaluated at all until someone ran it, though the docs said it did.
  # Allow exactly the NVIDIA packages, not every unfree package in nixpkgs:
  # the licence exception should be as narrow as the hardware that needs it.
  nixpkgs.config.allowUnfreePredicate = pkg:
    builtins.elem (lib.getName pkg) [
      "nvidia-x11" "nvidia-settings" "nvidia-persistenced"
      "nvidia-container-toolkit" "libnvidia-container"
      "cuda_cudart" "cuda_nvcc" "cuda_cccl" "libcublas"
    ];
  ainix.runner.device = "gpu";

  hardware.graphics.enable = true;
  hardware.nvidia = {
    modesetting.enable = false;        # headless: no display, no modeset
    powerManagement.enable = false;    # suspend/resume is not a server concern
    open = lib.mkDefault true;         # open kernel modules, Turing and newer
    nvidiaSettings = false;
  };
  services.xserver.videoDrivers = [ "nvidia" ];

  # Persistence mode keeps the driver initialised between processes. Without
  # it, every runner start pays several seconds of device setup.
  hardware.nvidia.nvidiaPersistenced = true;

  # Containers reach the GPU through CDI, so the same OCI image runs unchanged
  # across profiles — the device spec is what differs, not the image.
  hardware.nvidia-container-toolkit.enable = true;

  boot.kernelParams = [ "intel_iommu=on" "amd_iommu=on" ];
  boot.blacklistedKernelModules = [ "nouveau" ];
}
