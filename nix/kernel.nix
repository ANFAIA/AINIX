# Kernel choice and configuration.
#
# The rule for every entry: an inference machine is a throughput machine. It
# runs a small number of long-lived processes that want whole cores and large
# contiguous memory, not many short-lived ones that want fair scheduling.
{ config, lib, pkgs, ... }:

let cfg = config.ainix.kernel; in
{
  options.ainix.kernel.custom = lib.mkEnableOption ''
    building a kernel with the config below instead of the stock one.

    Off by default, and the default is the honest one: a custom config means
    compiling the kernel from source with no binary-cache hit, which turns a
    five-minute image build into an hour. The kernel *parameters* in
    tuning.nix — hugepages, isolcpus, governor, THP — are where most of the
    win is, and they apply to the stock kernel too.

    Turn this on when measuring the config itself, which is the only thing it
    buys over the parameters alone
  '';

  config = {
  boot.kernelPackages = lib.mkDefault pkgs.linuxPackages_latest;

  boot.kernelPatches = lib.mkIf cfg.custom [{
    name = "ainix-inference";
    patch = null;
    structuredExtraConfig = with lib.kernel; {
      # Throughput over latency: no preemption inside the kernel means fewer
      # context switches during a long matmul.
      PREEMPT = lib.mkForce no;
      PREEMPT_VOLUNTARY = lib.mkForce no;
      PREEMPT_NONE = lib.mkForce yes;

      # 100 Hz instead of 250/1000. Fewer timer interrupts per second on the
      # cores doing the work.
      HZ_100 = yes;
      HZ = freeform "100";

      # Large pages for weights and KV cache — fewer TLB misses per token.
      TRANSPARENT_HUGEPAGE = yes;
      TRANSPARENT_HUGEPAGE_MADVISE = yes;

      # Needed by the accelerator profiles for clean device passthrough.
      VFIO = module;
      VFIO_IOMMU_TYPE1 = module;
      VFIO_PCI = module;

      # cgroup v2 accounting is how an agent's quota is actually enforced.
      CGROUPS = yes;
      MEMCG = yes;
      CGROUP_SCHED = yes;

      # Things an inference box has no use for.
      SOUND = lib.mkForce no;
      WIRELESS = lib.mkForce no;
      WLAN = lib.mkForce no;
    };
  }];
  };
}
