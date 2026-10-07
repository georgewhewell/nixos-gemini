{
  buildPkgs,
  system,
}:
buildPkgs.runCommand "mainline-nixos-zlib.squashfs" {
  nativeBuildInputs = [buildPkgs.squashfsTools];
} ''
  mkdir -p store-contents
  closure=${buildPkgs.closureInfo {
    rootPaths = [system];
  }}
  for path in $(cat "$closure/store-paths"); do
    cp -a "$path" store-contents/
  done
  basename ${system} \
    > store-contents/.gemini-system
  # nix-store --load-db input for the persistent Nix database
  # (nixos/storage.nix): this image's paths live in the overlay's
  # read-only lower layer.
  cp "$closure/registration" store-contents/.gemini-registration
  # The builder's store may be hard-link optimised (auto-optimise-store),
  # and `cp -a` carries those links in.  Which files share an inode then
  # depends on the host's store history, not on the closure, so the image
  # and its content-addressed p29 name would change between identical
  # builds.  mksquashfs still deduplicates identical file contents.
  mksquashfs store-contents "$out" \
    -comp gzip -b 131072 -noappend -all-root -no-hardlinks -no-progress
  unsquashfs -s "$out" | grep -Fqx 'Compression gzip'
''
