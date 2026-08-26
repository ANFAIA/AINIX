# Networking, SSH, and remote transfer

## Interface and address inspection
- `ip addr` — addresses per interface (`ip a`). `ip link` — link state.
- `ip route` — routing table; default gateway line starts `default via`.
- Legacy but common: `ifconfig`, `netstat -rn`. Modern replacements are iproute2.
- `ping HOST`, `traceroute HOST`, `tracepath HOST` (no root needed).
- DNS: `resolvectl status`, `dig +short HOST`, `dig -x IP` (reverse),
  `getent hosts HOST` (NSS-respecting lookup).
- Sockets/ports: `ss -tulpn` — tcp(-t) udp(-u) listening(-l) processes(-p)
  numeric(-n). Root needed for `-p` on other users' processes.
  Older equivalent: `netstat -tulpn`.

## Transfers and HTTP
- `curl -fsSL URL -o OUT` — fail silently-less, follow redirects; `-I` headers only.
- `wget URL`, `wget -c URL` — resume support.
- `scp FILE USER@HOST:/path/`, `rsync -avh --progress SRC DST` — rsync resumes and
  does delta transfer; trailing slash on SRC means "contents of" not "the dir".

## SSH
- Client config per-user: `~/.ssh/config` — Host blocks set HostName, User,
  Port, IdentityFile, ProxyJump. Example:

      Host bastion
          HostName bastion.example.com
          User ops
          IdentityFile ~/.ssh/id_ed25519

      Host internal
          HostName 10.0.0.5
          ProxyJump bastion

- Keys: `ssh-keygen -t ed25519 -C COMMENT`; public key is `~/.ssh/id_ed25519.pub`.
  Install onto a server: `ssh-copy-id USER@HOST`. Private keys must be 600.
- Known hosts: `~/.ssh/known_hosts`; StrictHostKeyChecking behavior lives in config.
- Server config: `/etc/ssh/sshd_config` (drop-in dir `/etc/ssh/sshd_config.d/`).
  Important directives: Port, PermitRootLogin, PasswordAuthentication,
  PubkeyAuthentication, AllowUsers, AllowGroups. After edits:
  validate with `sshd -t`, then reload the unit — never restart blindly on a
  remote box; keep an existing session open until the new one is proven to work.

## Firewall basics
- nftables is the current backend; firewalld wraps it:
  `firewall-cmd --list-all`, `--add-service=http --permanent`, `--reload`.
- ufw on Debian-family: `ufw status verbose`, `ufw allow 22/tcp`, `ufw enable`.
- Enabling a firewall over SSH without first allowing ssh will cut the session —
  always add the allow rule before enabling.

## Safety rules
- Refuse disabling PasswordAuthentication or changing sshd port on a machine you
  cannot physically reach without explicit confirmation of a tested key login.
- Refuse `curl http://... | bash` installs; download then inspect.
