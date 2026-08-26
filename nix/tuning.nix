# Runtime tuning: kernel command line and sysctls.
#
# Each option says why it is here. Options that trade away safety or that only
# make sense on a machine dedicated to inference are behind `ainix.tuning.*`
# flags and default to OFF — a POC that silently disables mitigations is not a
# result anyone can trust.
{ config, lib, pkgs, ... }:

let
  cfg = config.ainix.tuning;
  inherit (lib) mkOption mkEnableOption types mkIf mkMerge optionals;
in
{
  options.ainix.tuning = {
    inferenceCores = mkOption {
      type = types.str;
      default = "";
      example = "4-9";
      description = ''
        CPU range handed exclusively to inference: isolcpus + nohz_full +
        rcu_nocbs. The kernel will not schedule anything else there and will
        stop sending it timer ticks.

        Empty by default. Setting this on a 2-core VM leaves the system with
        nothing to run on, so it must be chosen per machine.
      '';
    };

    hugepages1G = mkOption {
      type = types.int;
      default = 0;
      description = ''
        Number of 1 GiB hugepages reserved at boot for weights and KV cache.
        Reserved memory is gone from general use, so this is sized per machine
        and per model, not guessed.
      '';
    };

    disableMitigations = mkEnableOption ''
      turning off CPU speculation mitigations.

      Worth real throughput on older cores, and a genuine security trade-off:
      it re-exposes Spectre/Meltdown-class attacks. Only defensible on a
      single-tenant box running code you trust. Off by default, deliberately
    '';
  };

  config = {
    boot.kernelParams = mkMerge [
      [
        # Governor decided at boot rather than by a daemon reacting after the
        # latency has already been paid.
        "cpufreq.default_governor=performance"

        # THP on request only. Always-on THP causes allocation stalls that show
        # up as unexplained latency spikes mid-generation.
        "transparent_hugepage=madvise"

        # NUMA balancing migrates pages under a running model. On a box with
        # one workload pinned deliberately, that is pure overhead.
        "numa_balancing=disable"

        # Clean DMA for accelerator passthrough; pt = passthrough for the host.
        "iommu=pt"

        # ASPM power states add wake-up latency on the PCIe link to the GPU.
        "pcie_aspm=off"
      ]
      (optionals (cfg.inferenceCores != "") [
        "isolcpus=${cfg.inferenceCores}"
        "nohz_full=${cfg.inferenceCores}"
        "rcu_nocbs=${cfg.inferenceCores}"
      ])
      (optionals (cfg.hugepages1G > 0) [
        "hugepagesz=1G"
        "hugepages=${toString cfg.hugepages1G}"
      ])
      (optionals cfg.disableMitigations [ "mitigations=off" ])
    ];

    boot.kernel.sysctl = {
      # Swapping a model's weights out is never the right answer; the machine
      # should fail loudly instead of thrashing.
      "vm.swappiness" = 0;

      # Weight loading is one enormous sequential read. Let it use the cache
      # aggressively and write back lazily.
      "vm.dirty_ratio" = 40;
      "vm.dirty_background_ratio" = 10;

      # The OpenAI endpoint is the machine's whole external surface.
      "net.core.somaxconn" = 1024;
      "net.core.rmem_max" = 16777216;
      "net.core.wmem_max" = 16777216;

      # An agent holding many model sockets plus weight files runs out of the
      # default budget quickly.
      "fs.file-max" = 2097152;
    };

    # Same reasoning as swappiness, at the service level.
    systemd.services."ainix-runner".serviceConfig.MemorySwapMax = "0";
  };
}
