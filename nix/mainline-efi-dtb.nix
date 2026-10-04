{ buildPkgs, kernel, baselineDtb }:
# Keep every qualified hardware property, but bind late-CPU readiness to the
# actual EFI kernel's config, build ID and command line.
buildPkgs.runCommand "gemini-mainline-efi-dtb" {
  nativeBuildInputs = [ buildPkgs.python3 buildPkgs.dtc buildPkgs.binutils ];
} ''
  mkdir -p "$out"
  cp ${baselineDtb}/gemini.dtb "$out/gemini.dtb"
  chmod u+w "$out/gemini.dtb"
  python3 - ${kernel} "$out/gemini.dtb" \
    ${./a72-profile-package.py} ${./generate-late-cpu-provenance.py} <<'PY'
  import json, struct, subprocess, sys
  from pathlib import Path

  kernel, dtb, package, generator = map(Path, sys.argv[1:])
  leaf = '/chosen/gemini-late-cpu-provenance'

  def snapshot(node='/'):
      def get(*args):
          return subprocess.check_output(['fdtget', *args], text=True).strip()
      data = {node: {p: get('-t', 'bx', str(dtb), node, p)
                     for p in get('-p', str(dtb), node).split()}}
      for child in get('-l', str(dtb), node).split():
          data.update(snapshot(node.rstrip('/') + '/' + child))
      return data

  def reservations():
      raw = dtb.read_bytes()
      offset = struct.unpack_from('>I', raw, 16)[0]
      entries = []
      while True:
          entry = struct.unpack_from('>QQ', raw, offset)
          if entry == (0, 0):
              return entries
          entries.append(entry)
          offset += 16

  before, reserved = snapshot(), reservations()
  assert leaf in before, 'baseline lacks its qualified CPU provenance'
  assert not any(n.startswith(leaf + '/') for n in before), 'unexpected provenance children'
  subprocess.run(['fdtput', '-r', str(dtb), leaf], check=True)
  subprocess.run([sys.executable, str(package), str(kernel), str(dtb), str(generator)], check=True)
  after = snapshot()
  assert set(before) == set(after), 'EFI rebinding changed DT nodes'
  for prop in ('expected-ikconfig-identity', 'expected-gnu-build-id-identity', 'expected-cmdline-identity'):
      assert before[leaf][prop] != after[leaf][prop], 'EFI identity was not rebound: ' + prop
  old_record, new_record = before.pop(leaf), after.pop(leaf)
  assert before == after, 'EFI rebinding changed hardware properties'
  assert reserved == reservations(), 'EFI rebinding changed memory reservations'
  (dtb.parent / 'provenance-rebind.json').write_text(json.dumps(
      {'kernel': str(kernel), 'changed_node': leaf,
       'baseline': old_record, 'efi': new_record}, indent=2) + '\n')
  print('PASS: only CPU provenance rebound to the EFI kernel; hardware and reservations retained')
  PY
''
