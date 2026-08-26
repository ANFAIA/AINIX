# Filesystem navigation, search, and permissions

## Navigation
- `pwd` — print working directory.
- `ls -la` — long listing including hidden files; `-h` human-readable sizes.
- `cd -` — return to previous directory. `cd` alone goes to `$HOME`.
- `realpath FILE` / `readlink -f FILE` — absolute resolved path.

## Find and locate files
- `find PATH -name '*.log' -mtime -7` — files modified in the last 7 days.
- `find . -type f -size +100M` — regular files larger than 100 MB.
- `find . -type d -name node_modules -prune -o -type f -print` — skip a subtree.
- `find . -perm 777 -type f` — world-writable files (audit use).
- `locate PATTERN` — index lookup; run `updatedb` to refresh the index.
- `which CMD`, `command -v CMD`, `type CMD` — resolve what a command name runs.
- `du -sh DIR`, `df -h` — directory size vs filesystem free space.
- `wc -l FILE` counts lines; `file FILE` identifies type by content.

## Permissions model
- Modes: read=4, write=2, execute=1 for user/group/other. `755` = rwxr-xr-x.
- `chmod 640 FILE`, `chmod u+x SCRIPT`, `chmod -R g-w DIR`.
- Ownership: `chown user:group FILE`; recursive with `-R`. Requires root.
- Special bits: setuid (`chmod u+s`), setgid on directories makes new files inherit
  the group, sticky bit (`+t`) on shared dirs like `/tmp`.
- Default modes come from `umask`; typical umask `022` yields `644` files, `755` dirs.
- Extended attributes via `getfattr`/`setfattr`; ACLs via `getfacl`/`setfacl`.

## Links
- Hard link: `ln TARGET LINK_NAME` — same inode; cannot cross filesystems.
- Symbolic link: `ln -s TARGET LINK_NAME` — path reference, may dangle.
- Broken symlinks: `find . -xtype l`.

## Archives
- Tar gzip: `tar -czf OUT.tar.gz DIR/`; extract: `tar -xzf OUT.tar.gz`; list: `tar -tzf`.
- Zip: `zip -r OUT.zip DIR/`, `unzip OUT.zip`.
- Never extract an untrusted archive outside a scratch directory without first
  listing it (`tar -tf`) — archives can contain absolute paths or `..` traversal.

## Safe-deletion contract
- `rm -rf` on a variable path must be guarded: quote variables and prefer
  explicit absolute paths. Refuse requests like `rm -rf /`, `rm -rf $VAR/`
  when `$VAR` may be empty, or force-delete of system directories.
