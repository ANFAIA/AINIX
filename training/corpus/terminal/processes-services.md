# Processes, signals, and systemd services

## Inspecting processes
- `ps aux` — every process, BSD style; `ps -ef` System V style.
- `pgrep -f PATTERN`, `pidof NAME` — find pids.
- `top`, `htop` — interactive; sort with `P` (CPU), `M` (memory).
- `kill -l` — list signals. Common: SIGTERM(15) polite, SIGKILL(9) uncatchable,
  SIGHUP(1) reload/reread config for daemons, SIGINT(2) Ctrl-C.
- `kill PID`, `kill -TERM PID`, `pkill -f PATTERN` — escalate TERM then KILL,
  never start at KILL.
- Backgrounding: `CMD &`, `nohup CMD &`, `disown`; jobs control `jobs`,
  `fg %N`, `bg %N`, Ctrl-Z suspends.

## systemd units
- `systemctl status UNIT` — state and recent log lines.
- `systemctl start|stop|restart|reload UNIT`.
- `systemctl enable --now UNIT` — enable at boot AND start immediately.
- `systemctl disable UNIT`; `systemctl is-enabled UNIT`.
- `systemctl list-units --failed` — triage starting point after boot problems.
- `systemctl list-unit-files --state=enabled`.
- Unit files live in `/etc/systemd/system/` (admin) and `/usr/lib/systemd/system/`
  (packages). After editing: `systemctl daemon-reload`.
- Timers replace cron under systemd: `systemctl list-timers`.
- Journal: `journalctl -u UNIT`, `journalctl -f` (follow),
  `journalctl --since "1 hour ago"`, `journalctl -p err..alert` (priority filter).
- `systemd-analyze blame` — slow-boot per-unit timings.

## Resource limits and cgroups
- `ulimit -a` — shell resource limits.
- `systemd-run --scope -p MemoryMax=500M CMD` — run a command under a cgroup limit.
- OOM events appear in the journal as `Out of memory: Killed process`.

## Safety rules
- Killing PID 1, mass `kill -9` of everything, or `kill` by name pattern without
  checking `pgrep` output first are refusals: confirm the exact pid list before
  signaling.
