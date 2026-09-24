#!/usr/bin/env bash
# Build the RAM-bootable image, boot it with `ainix.selftest`, and read the
# verdict the image prints about itself. Needs Docker (for Nix) and
# qemu-system-aarch64. About two minutes, most of it the build.
set -euo pipefail
cd "$(dirname "$0")/.."

git add -N flake.nix nix >/dev/null 2>&1 || true
mkdir -p build/boot
docker run --rm -v "$PWD":/src -w /src -v ainix-nix-store:/nix -v "$PWD/build":/out nixos/nix \
  sh -c "nix --extra-experimental-features 'nix-command flakes' build .#netboot --out-link /out/netboot \
         && cp -L /out/netboot/kernel /out/netboot/initrd /out/boot/ \
         && cat /out/netboot/cmdline > /out/boot/cmdline && chmod 644 /out/boot/*"

accel="-accel tcg"; cpu="-cpu max"
if [ "$(uname -s)" = Darwin ]; then accel="-accel hvf"; cpu="-cpu host"; fi
if [ -w /dev/kvm ]; then accel="-accel kvm"; cpu="-cpu host"; fi

# Kept, so a FAIL can be read after the VM is gone.
log=build/boot/selftest.log
timeout 300 qemu-system-aarch64 -M virt $cpu $accel -smp 4 -m 8192 \
  -kernel build/boot/kernel -initrd build/boot/initrd \
  -append "$(cat build/boot/cmdline) ainix.selftest" \
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
  -nographic -no-reboot >"$log" 2>&1 || true

sed 's/\x1b\[[0-9;:?]*[a-zA-Z]//g' "$log" | grep -a "AINIX-SELFTEST" | sed 's/^.*AINIX-SELFTEST/ /'
grep -aq "AINIX-SELFTEST PASS" "$log"
