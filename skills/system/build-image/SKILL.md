# build-image

## Procedure

1. Nix runs **inside a container** (`nixos/nix`) — this is a Mac. A named
   volume keeps the store between runs, so the second build is fast.
   `make os-eval` type-checks the whole configuration and builds nothing.
2. **Boot-test with the netboot output, not the disk image.** Building a qcow2
   ends in a VM that installs a bootloader and needs KVM, which Docker Desktop
   does not expose:
   `Required features: {kvm}  Available: {benchmark, big-parallel, ...}`.
   The netboot output — kernel plus the whole closure as a squashfs initrd —
   boots the *same module list*, so the test is real.
3. Boot it with the host's own qemu and HVF; it reaches the first-boot prompt
   in about five seconds.
4. `git add -N` any new `.nix` file before evaluating. Nix ignores files git
   does not track, and the error says so but is easy to misread as a syntax
   problem.

## The three failures to check first

1. **No console output at all** — `console=` order. The *last* one wins for
   `/dev/console`, so a serial console must come last or the whole boot log
   goes to a screen nobody is watching.
2. **Emergency mode on a mount** — a `fileSystems` entry for a device this
   image has no reason to have. A RAM-booted system has no ESP; the failed
   mount takes Local File Systems down with it. Guard the layout behind an
   option instead of `mkDefault`.
3. **An interactive service asking where nobody can answer** — `TTYPath`
   pinned to `/dev/tty1` on a serial-only machine. It must also conflict with
   `serial-getty@`, not just `getty@`, or the login prompt races it.

## Two knobs that stay off

`ainix.kernel.custom` compiles the kernel config in `nix/kernel.nix` and costs
the binary cache — an hour instead of five minutes — while the kernel
*parameters* carry most of the win. `ainix.tuning.disableMitigations` is a
real re-exposure of Spectre-class attacks, defensible only single-tenant.
Turning either on without saying so in the results is dishonest benchmarking.

## Unverified

The NVIDIA and AMD profiles evaluate but have never booted — no such hardware
is attached. Treat them as hypotheses, not coverage.
