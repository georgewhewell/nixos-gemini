{ buildPkgs, baseBundle, rescueBundle, bootFiles, activateFrom ? null }:
assert activateFrom == null || builtins.match "[0-9a-f]{64}" activateFrom != null;
# Derive an opt-in initramfs; accepted M69 and the qualified EFI payload stay exact.
buildPkgs.runCommand "gemini-efi-provision-bundle" {
  nativeBuildInputs = [ buildPkgs.python3 buildPkgs.cpio buildPkgs.gzip ];
  SOURCE_DATE_EPOCH = 1788493603;
} ''
  mkdir root "$out"
  gzip -dc ${baseBundle}/initramfs.cpio.gz | (cd root; cpio -id --quiet --no-preserve-owner)
  chmod u+w root/init root/bin root/etc
  cp ${./gemini-efi-publish.sh} root/bin/gemini-efi-publish
  cp ${./gemini-efi-provision.sh} root/bin/gemini-efi-provision
  cp ${bootFiles}/files.manifest root/etc/gemini-efi-files.manifest
  cp ${bootFiles}/archive.meta root/etc/gemini-efi-archive.meta
  ${buildPkgs.lib.optionalString (activateFrom != null) ''
    printf '%s\n' '${activateFrom}' > root/etc/gemini-efi-activate-from
  ''}
  chmod 0755 root/bin/gemini-efi-publish
  python3 - ${baseBundle} ${rescueBundle} ${bootFiles} "$out" <<'PY'
  import hashlib, json, re, sys, tarfile
  from pathlib import Path
  base, rescue, files, out = map(Path, sys.argv[1:])
  root = Path('root')
  init = root/'init'
  before = init.read_text()
  anchor = 'log "store-image=verified sha256=$actual"\n'
  assert before.count(anchor) == 1
  assert before.index(anchor) < before.index('loopdev=$(losetup -f')
  assert 'kill -0 "$watchdog_pid"' in before and 'lease=720s' in before
  after = before.replace(anchor, anchor + '. /bin/gemini-efi-provision\n')
  init.write_text(after)
  assert after.replace('. /bin/gemini-efi-provision\n', "") == before
  protected=[]
  for bundle in (base, rescue):
      manifest=dict(line.split('=',1) for line in (bundle/'MANIFEST').read_text().splitlines() if '=' in line)
      name, sha, size = (manifest[k] for k in ('store-file','store-sha256','store-size'))
      assert re.fullmatch('[0-9a-f]{64}', sha) and name == 'mainline-nixos-'+sha+'.squashfs'
      assert size.isdecimal() and int(size)>0
      assert (bundle/name).stat().st_size==int(size)
      protected.append(f'{sha} {size} {name}\n')
  assert len(set(protected))==2
  (root/'etc/gemini-efi-protected-stores.manifest').write_text("".join(protected))
  manifest=json.loads((files/'manifest.json').read_text())
  with tarfile.open(files/'boot-files.tar') as archive:
      members=archive.getmembers()
      assert len(members)==len(manifest['files']) and len(members) in (5,6)
      assert {m.name for m in members}==set(manifest['files'])
      for m in members:
          assert m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts
          data=archive.extractfile(m).read()
          assert {'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}==manifest['files'][m.name]
  added_files=['bin/gemini-efi-publish','bin/gemini-efi-provision',
               'etc/gemini-efi-files.manifest','etc/gemini-efi-archive.meta',
               'etc/gemini-efi-protected-stores.manifest']
  activation_file=root/'etc/gemini-efi-activate-from'
  activation_from=activation_file.read_text().strip() if activation_file.exists() else None
  if activation_from is not None:
      assert re.fullmatch('[0-9a-f]{64}',activation_from)
      added_files.append('etc/gemini-efi-activate-from')
  (out/'provision-manifest.json').write_text(json.dumps({
      'base_bundle':str(base),'rescue_bundle':str(rescue),'boot_files':str(files),
      'archive':manifest['archive'],'base_init_sha256':hashlib.sha256(before.encode()).hexdigest(),
      'init_sha256':hashlib.sha256(after.encode()).hexdigest(),
      'activation_from_sha256':activation_from,'added_files':added_files},indent=2)+'\n')
  print('PASS: bounded Stage 1 gate precedes store loop; exact archive members and both protected stores bound')
  PY
  sh -n root/init
  sh -n root/bin/gemini-efi-publish
  sh -n root/bin/gemini-efi-provision
  # Extraction assigns build-time timestamps and host inode numbers. Neither
  # belongs in a pinned boot image; retain file contents, modes and link topology.
  (cd root; find . -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +)
  (cd root; find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --reproducible --owner=0:0 --quiet) | gzip -n -9 > "$out/initramfs.cpio.gz"
  ln -s ${baseBundle}/kernel "$out/kernel"
  ln -s ${baseBundle}/gemini-usb11-host.dtb "$out/gemini-usb11-host.dtb"
''
