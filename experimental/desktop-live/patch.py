"""Reversible, opt-in patch for the observed Windows ZCode 3.17.1 build.

Only prepare redistributable tooling: the generated archive stays on your machine.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

SUPPORTED_SHA256 = '9a09f6ef7a938072c57f56d3dbf4b5677eaceb1c5b00ae555fb7e2bfdea88255'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def secure_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.is_junction():
        raise ValueError('Use a real private directory, not a junction/symlink')
    if os.name == 'nt':
        identity = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
        sid = next(csv.reader(io.StringIO(identity)))[1]
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                        f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], check=True,
                       stdout=subprocess.DEVNULL)
    else:
        path.chmod(0o700)


def read_header(path):
    with Path(path).open('rb') as source:
        lead = source.read(16)
        if len(lead) != 16 or struct.unpack('<I', lead[:4])[0] != 4:
            raise ValueError('Invalid ASAR header')
        length = struct.unpack('<I', lead[12:16])[0]
        if length > 64 * 1024 * 1024:
            raise ValueError('ASAR header too large')
        return json.loads(source.read(length)), 8 + struct.unpack('<I', lead[4:8])[0]


def packed_files(header):
    result = []
    def walk(node, prefix=''):
        for name, value in node.get('files', {}).items():
            key = prefix + name
            if 'files' in value:
                walk(value, key + '/')
            elif 'offset' in value:
                result.append((key, value, int(value['offset'])))
    walk(header)
    return sorted(result, key=lambda item: item[2])


def integrity(data, block=4194304):
    return {'algorithm': 'SHA256', 'hash': hashlib.sha256(data).hexdigest(),
            'blockSize': block, 'blocks': [hashlib.sha256(data[i:i+block]).hexdigest()
                                         for i in range(0, len(data), block)]}


def rebuild(source, output, header, base, replacements):
    entries = packed_files(header)
    existing = {name for name, _, _ in entries}
    for name, data in replacements.items():
        if name not in existing:
            node = header
            parts = name.split('/')
            for part in parts[:-1]:
                node = node['files'][part]
            node['files'][parts[-1]] = {'size': len(data), 'offset': '0'}
            entries.append((name, node['files'][parts[-1]], None))
    position = 0
    for name, metadata, _ in entries:
        metadata['offset'] = str(position)
        if name in replacements:
            metadata['size'] = len(replacements[name])
            metadata['integrity'] = integrity(replacements[name], metadata.get('integrity', {}).get('blockSize', 4194304))
        position += metadata['size']
    raw = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode()
    payload = struct.pack('<I', len(raw)) + raw
    payload += b'\0' * (-len(payload) % 4)
    pickle = struct.pack('<I', len(payload)) + payload
    with Path(output).open('xb') as target, Path(source).open('rb') as original:
        target.write(struct.pack('<II', 4, len(pickle)) + pickle)
        for name, metadata, old_offset in entries:
            if name in replacements:
                target.write(replacements[name])
            else:
                original.seek(base + old_offset)
                data = original.read(metadata['size'])
                if len(data) != metadata['size']:
                    raise ValueError('Truncated original archive')
                target.write(data)


def prepare(args):
    source = Path(args.asar).resolve(strict=True)
    if digest(source) != SUPPORTED_SHA256:
        raise ValueError('Unsupported ZCode build: original archive SHA256 differs; nothing installed')
    workspace = Path(args.workspace).resolve(strict=True)
    if not workspace.is_dir() or not args.session.startswith('sess_'):
        raise ValueError('Explicit existing workspace and sess_ ID required')
    output = Path(args.output).absolute()
    state = Path(args.state_dir).absolute()
    if output.exists() or state.exists():
        raise ValueError('Output and state directories must be new')
    secure_directory(output)
    secure_directory(state)
    header, base = read_header(source)
    index = header['files']['out']['files']['main']['files']['index.js']
    with source.open('rb') as stream:
        stream.seek(base + int(index['offset']))
        main = stream.read(index['size']).decode()
    if not all(marker in main for marker in ['Ci=CE({windowHostProcessMap:xr', 'd as lw', 'function dF(e)']):
        raise ValueError('Observed desktop host symbols no longer match')
    bootstrap = '''
// Optional local desktop adapter; observed Windows ZCode 3.17.1 symbols.
import { startLocalAdapter as codexStartLocalAdapter } from './codex-local-adapter.mjs';
import { f as CodexChannelClient } from './chunk-CM2YMK3U.js';
X.whenReady().then(() => codexStartLocalAdapter({
  BrowserWindow: SE,
  attachWorkspaceHost: Ci.attachWorkspaceHost,
  releaseAttachment: Ci.releaseAttachment,
  makeClient: port => new CodexChannelClient(new lw(dF(port))),
  workspacePath: WORKSPACE,
  sessionId: SESSION,
  stateDirectory: STATE
})).then(adapter => { X.on('before-quit', () => { void adapter.dispose(); }); })
  .catch(error => console.error('[codex-local-adapter]', error.message));
'''.replace('WORKSPACE', json.dumps(str(workspace))).replace('SESSION', json.dumps(args.session)).replace('STATE', json.dumps(str(state)))
    candidate = output / 'app.asar.patched'
    rebuild(source, candidate, header, base, {
        'out/main/index.js': (main + bootstrap).encode(),
        'out/main/codex-local-adapter.mjs': Path(__file__).with_name('adapter.mjs').read_bytes()})
    manifest = {'asar': str(source), 'original_sha256': SUPPORTED_SHA256,
                'patched_sha256': digest(candidate), 'state_dir': str(state)}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print('Prepared locally. Close ZCode normally, then run install with --bundle ' + str(output))


def require_closed():
    if os.name != 'nt':
        raise ValueError('Installation and rollback are supported only on Windows')
    listing = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq ZCode.exe', '/FO', 'CSV', '/NH'], text=True)
    if any(row and row[0].lower() == 'zcode.exe' for row in csv.reader(io.StringIO(listing))):
        raise ValueError('Close ZCode normally first; no process will be killed')


def install_or_restore(args):
    require_closed()
    bundle = Path(args.bundle).resolve(strict=True)
    manifest = json.loads((bundle / 'manifest.json').read_text())
    target = Path(manifest['asar'])
    backup = bundle / 'app.asar.original'
    if args.action == 'install':
        if digest(target) != SUPPORTED_SHA256 or manifest['original_sha256'] != SUPPORTED_SHA256:
            raise ValueError('Original changed; refusing to install')
        source = bundle / 'app.asar.patched'
        expected = manifest['patched_sha256']
        if backup.exists():
            raise ValueError('Backup already exists; refusing to overwrite')
    else:
        if digest(target) != manifest['patched_sha256']:
            raise ValueError('Installed app changed; refusing to overwrite an update')
        source, expected = backup, SUPPORTED_SHA256
    if digest(source) != expected:
        raise ValueError('Source hash mismatch')
    if args.action == 'install':
        with backup.open('xb') as stream, target.open('rb') as original:
            shutil.copyfileobj(original, stream)
        if digest(backup) != SUPPORTED_SHA256:
            raise ValueError('Backup verification failed')
    temporary = target.with_name('app.asar.desktop-live-tmp')
    with temporary.open('xb') as stream, source.open('rb') as replacement:
        shutil.copyfileobj(replacement, stream)
    if digest(temporary) != expected:
        raise ValueError('Copy verification failed; original remains in place')
    os.replace(temporary, target)
    if digest(target) != expected:
        raise ValueError('Installed archive verification failed')
    print(args.action + ' complete. Start ZCode normally. Chat databases were not touched.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    stage = commands.add_parser('prepare')
    for flag in ['asar', 'workspace', 'session', 'state-dir', 'output']:
        stage.add_argument('--' + flag, required=True)
    for action in ['install', 'rollback']:
        commands.add_parser(action).add_argument('--bundle', required=True)
    arguments = parser.parse_args()
    try:
        prepare(arguments) if arguments.action == 'prepare' else install_or_restore(arguments)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
