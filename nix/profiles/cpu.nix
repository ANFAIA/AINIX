# CPU profile — no accelerator.
#
# The baseline, and the only profile that can be built and booted on the
# development machine. Everything above the HAL is identical to the GPU
# profiles; only the driver and the runner's device flag differ.
{ lib, ... }:
{
  ainix.profile = "cpu";
  ainix.runner.device = "cpu";
  # No driver, no firmware, no CDI spec. That is the point of this profile.
}
