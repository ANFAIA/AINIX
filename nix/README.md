# The bootable image

```bash
make os-eval     # type-check the whole configuration, build nothing
make os-build    # build the qcow2 disk image  (needs KVM — see below)
make os-boot     # boot the artefact in QEMU
```

Nix runs inside a `nixos/nix` container because the development machine is a
Mac. A named volume keeps the store between runs, so the second build is fast.

## Layers

| file | what it decides |
|---|---|
| `base.nix` | what the system is *not* — no docs, no X, no sound, no printing |
| `disk.nix` | on-disk layout; switched off entirely for RAM-booted images |
| `kernel.nix` | kernel config, behind `ainix.kernel.custom` (off by default) |
| `tuning.nix` | kernel command line and sysctls — the actual AI tuning |
| `profiles/*.nix` | the HAL: one file per accelerator vendor |
| `services/runner.nix` | the shared model runner on :8000 |
| `services/firstboot.nix` | the network-then-model question, before the login prompt |

## Two artefacts, one configuration

`packages.netboot` is kernel + initrd with the whole store in a squashfs — it
boots from RAM with no disk and no bootloader. That is the boot test that
works on a Mac, because building a *disk image* needs KVM and Docker Desktop
does not provide it.

`packages.qcow2` is the shippable disk image. It evaluates and the system
builds; only the final image-assembly step needs a Linux host with KVM.

Both come from the same module list (`modulesFor` in `flake.nix`), so the
thing that boots in QEMU cannot drift from the thing that ships.

## Two knobs that are off on purpose

`ainix.kernel.custom` compiles a kernel with `PREEMPT_NONE`, `HZ_100`, and the
rest of `kernel.nix`. Off by default because it means no binary-cache hit —
an hour instead of five minutes — and the kernel *parameters* carry most of
the win anyway. Turn it on when measuring the config itself.

`ainix.tuning.disableMitigations` adds `mitigations=off`. Real throughput on
older cores, and a real re-exposure of Spectre/Meltdown-class attacks. Only
defensible on a single-tenant box running code you trust.

`ainix.tuning.inferenceCores` (isolcpus + nohz_full + rcu_nocbs) is empty by
default for a related reason: setting it on a 2-core VM leaves the system with
nowhere to run.
