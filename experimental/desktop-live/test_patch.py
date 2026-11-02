import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import patch as patcher
from discover import list_chats
import sqlite3
from patch import rebuild, read_header, packed_files, integrity, SUPPORTED_SHA256, prepare
from types import SimpleNamespace


class ArchiveTests(unittest.TestCase):
    def test_discovery_is_read_only_and_excludes_deleted_chats(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'tasks.sqlite'
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE tasks (task_id TEXT, title TEXT, workspace_path TEXT, deleted INTEGER, archived INTEGER, updated_at INTEGER)')
                connection.executemany('INSERT INTO tasks VALUES (?,?,?,?,?,?)', [
                    ('sess_visible', 'Disposable chat', '/fake/workspace', 0, 0, 1),
                    ('sess_deleted', 'Deleted', '/fake/other', 1, 0, 2)])
            connection.close()
            before = db.read_bytes()
            self.assertEqual(list_chats(db), [{'session_id': 'sess_visible', 'title': 'Disposable chat', 'workspace': '/fake/workspace'}])
            self.assertEqual(db.read_bytes(), before)

    def test_install_rollback_and_update_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'app.asar'
            bundle = root / 'bundle'
            bundle.mkdir()
            original, replacement = b'synthetic-original', b'synthetic-replacement'
            original_sha = hashlib.sha256(original).hexdigest()
            patched_sha = hashlib.sha256(replacement).hexdigest()
            target.write_bytes(original)
            (bundle / 'app.asar.patched').write_bytes(replacement)
            (bundle / 'manifest.json').write_text(json.dumps({
                'asar': str(target), 'original_sha256': original_sha,
                'patched_sha256': patched_sha}))
            args = SimpleNamespace(bundle=str(bundle), action='install')
            with patch.object(patcher, 'SUPPORTED_SHA256', original_sha), patch.object(patcher, 'require_closed'):
                patcher.install_or_restore(args)
                self.assertEqual(target.read_bytes(), replacement)
                self.assertEqual((bundle / 'app.asar.original').read_bytes(), original)
                args.action = 'rollback'
                target.write_bytes(b'new-application-update')
                with self.assertRaisesRegex(ValueError, 'Installed app changed'):
                    patcher.install_or_restore(args)
                self.assertEqual(target.read_bytes(), b'new-application-update')
                target.write_bytes(replacement)
                patcher.install_or_restore(args)
                self.assertEqual(target.read_bytes(), original)

    def test_rebuild_preserves_unmodified_files_and_adds_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original.asar'
            header = {'files': {'out': {'files': {'main': {'files': {
                'index.js': {'size': 3, 'offset': '0'},
                'keep.bin': {'size': 4, 'offset': '3', 'integrity': integrity(b'keep')},
                'native.node': {'size': 10, 'unpacked': True}}}}}}}
            raw = json.dumps(header).encode()
            payload = struct.pack('<I', len(raw)) + raw
            payload += b'\0' * (-len(payload) % 4)
            pickle = struct.pack('<I', len(payload)) + payload
            original.write_bytes(struct.pack('<II', 4, len(pickle)) + pickle + b'oldkeep')
            loaded, base = read_header(original)
            output = root / 'patched.asar'
            rebuild(original, output, loaded, base, {
                'out/main/index.js': b'new-longer', 'out/main/adapter.mjs': b'new-module'})
            changed, changed_base = read_header(output)
            values = {}
            with output.open('rb') as stream:
                for key, metadata, offset in packed_files(changed):
                    stream.seek(changed_base + offset)
                    values[key] = stream.read(metadata['size'])
            self.assertEqual(values, {'out/main/index.js': b'new-longer',
                                     'out/main/keep.bin': b'keep',
                                     'out/main/adapter.mjs': b'new-module'})
            self.assertTrue(changed['files']['out']['files']['main']['files']['native.node']['unpacked'])
            self.assertEqual(changed['files']['out']['files']['main']['files']['index.js']['integrity'], integrity(b'new-longer'))

    def test_unsupported_build_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'app.asar'
            source.write_bytes(b'unrecognized build')
            output = root / 'bundle'
            with self.assertRaisesRegex(ValueError, 'Unsupported ZCode'):
                prepare(SimpleNamespace(asar=str(source), workspace=str(root), session='sess_test',
                                        state_dir=str(root / 'private'), output=str(output)))
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
