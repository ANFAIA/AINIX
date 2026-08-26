# Text processing, logs, and configuration files

## Text pipeline tools
- `grep -rn PATTERN DIR` — recursive with line numbers; `-i` case-insensitive;
  `-l` files-with-matches; `-E` extended regex; `-v` invert; `--include='*.py'`.
- `sed -n '10,20p' FILE` — print a line range; `sed -i.bak 's/old/new/g' FILE`
  — in-place edit WITH backup suffix; bare `-i` overwrites irreversibly.
- `awk '{print $1}'` — first whitespace-separated field; `awk -F: '{print $1}'
  /etc/passwd` — colon-separated fields.
- `sort | uniq -c | sort -rn` — count and rank duplicates; `uniq` requires
  sorted input.
- `cut -d, -f2`, `tr 'a-z' 'A-Z'`, `column -t`, `tee FILE` — split a stream.
- Streams: stdin(0) stdout(1) stderr(2). `CMD >out 2>err`, `CMD >all 2>&1`,
  `CMD 2>&1 | less`, `CMD &>file` (bash). `/dev/null` discards.

## Logs
- Debian-family auth log: `/var/log/auth.log`; RHEL-family: `/var/log/secure`.
- Kernel ring buffer: `dmesg -T` (human timestamps); persistent in the journal.
- Everything systemd: `journalctl` — see processes-services reference.
- Log rotation config: `/etc/logrotate.conf` + `/etc/logrotate.d/`.
- Follow a file: `tail -f /var/log/syslog`; multi-file: `multitail`.

## Shell configuration
- Login shells read `/etc/profile` then `~/.bash_profile` or `~/.profile`;
  interactive non-login shells read `~/.bashrc`. Zsh: `~/.zshrc`, global `/etc/zshrc`.
- Environment variables: export in these files; check with `printenv VAR`,
  `echo "$VAR"`. PATH entries are colon-separated; prepend:
  `export PATH="$HOME/bin:$PATH"`.
- `source FILE` / `. FILE` — apply changes to the current shell without re-login.
- Aliases: `alias ll='ls -la'` in rc file; functions for anything with arguments.

## Common configuration files
- Hostname resolution overrides: `/etc/hosts` (`IP HOSTNAME [aliases]`),
  checked before DNS per `/etc/nsswitch.conf` `hosts:` line.
- DNS resolvers: `systemd-resolved` uses `/etc/resolv.conf` symlink to stub,
  real servers configured per-link via networkd or NetworkManager.
- Timezone: `timedatectl set-timezone AREA/CITY`; list with
  `timedatectl list-timezones`. Sync status: `timedatectl` shows NTP state.
- Locale: `localectl set-locale LANG=en_US.UTF-8`.
- fstab mounts: `/etc/fstab` fields = device mountpoint type options dump pass.
  Validate before rebooting: `findmnt --verify` or `mount -a` (as root, after
  snapshotting). A bad fstab line can make the next boot drop to emergency shell.
- Crontabs: `crontab -e` (user), `/etc/crontab` system-wide. Fields:
  minute hour day month weekday command. Systemd timers are preferred where
  available because they log to the journal.
- sysctl kernel tunables: `/etc/sysctl.d/*.conf`, apply with
  `sysctl --system`, inspect with `sysctl KEY`.

## Editing discipline
- Prefer targeted edits with verification over rewrites: back up (`cp F F.bak`),
  edit, validate syntax (`nginx -t`, `sshd -t`, `visudo -c`, `fstab`: findmnt),
  reload the unit, confirm the service still answers — before closing the session.
