#!/bin/sh
# Publish the existing p32 filesystem's layout; the caller verifies its mount.
# Publishing home last keeps Stage 1's layout gate closed until copying ends.
set -eu
root=$1
source_home=$2
[ "$#" -eq 2 ] || exit 2
[ -d "$root" ] && [ ! -L "$root" ] || exit 1
[ -d "$source_home" ] && [ ! -L "$source_home" ] || exit 1

if [ -e "$root/home" ] || [ -L "$root/home" ]; then
    for path in home nix nix/upper nix/work nix/var; do
        [ -d "$root/$path" ] && [ ! -L "$root/$path" ] || exit 1
    done
    echo 'layout=already-initialized'
    exit 0
fi

# Never adopt a populated, foreign or partially initialized filesystem.
for path in "$root"/* "$root"/.[!.]* "$root"/..?*; do
    [ -e "$path" ] || [ -L "$path" ] || continue
    [ "${path##*/}" = lost+found ] && [ -d "$path" ] && [ ! -L "$path" ] || exit 1
done
stage=$root/.gemini-layout-stage
mkdir -m 0700 "$stage"
cp -a "$source_home" "$stage/home"
mkdir -p "$stage/nix/upper" "$stage/nix/work" "$stage/nix/var"
chmod 0755 "$stage/home" "$stage/nix" "$stage/nix/work" "$stage/nix/var"
chown 0:30000 "$stage/nix/upper"
chmod 1775 "$stage/nix/upper"
sync
[ ! -e "$root/nix" ] && [ ! -L "$root/nix" ] || exit 1
mv "$stage/nix" "$root/nix"
sync
[ ! -e "$root/home" ] && [ ! -L "$root/home" ] || exit 1
mv "$stage/home" "$root/home"
rmdir "$stage"
sync
echo 'layout=initialized home=copied activation=next-boot'
