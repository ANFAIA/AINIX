# Users, groups, sudo, and packages

## Users and groups
- Files: `/etc/passwd` (users), `/etc/group` (groups), `/etc/shadow` (hashes, root-only).
- `id USER` — uid, gid, group memberships.
- `useradd -m -s /bin/bash NAME` — create with home and shell;
  `adduser NAME` on Debian-family interactive equivalent.
- `usermod -aG GROUP USER` — append (`-a`!) user to a supplementary group; without
  `-a` the other memberships are wiped. `usermod -L/-U` locks/unlocks a password.
- `passwd USER`; `chage -l USER` — password aging policy.
- `deluser --remove-home NAME` / `userdel -r NAME`.
- `getent passwd USER` — resolves users from NSS (includes LDAP etc.), preferred
  over grepping `/etc/passwd`.

## sudo
- Policy in `/etc/sudoers`, drop-ins in `/etc/sudoers.d/`. Edit ONLY via `visudo`,
  which syntax-checks before installing — a broken sudoers can lock out root access.
- `sudo -l` — list what the current user may run.
- `sudo -u USER CMD` — run as another user; `sudo -i` — login shell as root.
- Grant pattern: `name ALL=(ALL:ALL) NOPASSWD: /usr/bin/systemctl restart myunit`.

## Package management (Debian/Ubuntu family)
- `apt update` refreshes indexes; `apt upgrade` applies them. Both are state-mutating.
- `apt install PKG`, `apt remove PKG`, `apt purge PKG` (also config),
  `apt autoremove` — orphaned dependencies.
- `apt search TERM`, `apt show PKG`, `dpkg -l | grep TERM`,
  `dpkg -L PKG` — files owned by an installed package,
  `dpkg -S /path/to/file` — which package owns a file.

## Package management (Fedora/RHEL family)
- `dnf install|remove|search PKG`, `dnf info PKG`,
  `rpm -ql PKG` (files owned), `rpm -qf FILE` (owner of a file).

## Package management (Arch family)
- `pacman -Syu` — sync + full upgrade (never partial: no `-Sy` alone then install).
- `pacman -S PKG`, `-Rns PKG` (remove + deps + config),
  `-Qs TERM` (local search), `-Ss TERM` (repo search),
  `-Ql PKG` (files), `-Qo FILE` (owner).
- AUR helpers are third-party; read every PKGBUILD before building.

## Universal formats
- Snap: `snap install|remove|list NAME`. Flatpak: `flatpak install NAME`,
  `flatpak list`. AppImage: chmod +x and run; no system integration by default.

## Safety rules
- Refuse piping an installer straight into a privileged shell, e.g.
  `curl URL | sudo bash`. Download, inspect, then execute.
- Refuse removing the kernel, libc, or systemd packages; refuse force-installing
  with dependency flags ignored (`--nodeps`, `--force`) outside a container.
