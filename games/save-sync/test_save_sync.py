import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import save_sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.local = self.base / 'local'
        self.remote = self.base / 'remote'
        self.state = self.base / 'state'
        for p in (self.local, self.remote, self.state):
            p.mkdir()
        self.config = self.base / 'mapping.json'
        self.config.write_text(json.dumps({'version': 1, 'state_dir': str(self.state), 'games': {
            'example-game': {'local': str(self.local), 'remote': str(self.remote)}}}))

    def run_sync(self, **kwargs):
        return save_sync.sync(self.config, 'example-game', **kwargs)

    def put(self, root, name='slot.sav', content=b'initial'):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def baseline(self):
        return json.loads((self.state / 'example-game.json').read_text())

    def test_baselines_are_persistent_and_isolated_per_game(self):
        self.put(self.local)
        self.run_sync()
        first_state = (self.state / 'example-game.json').read_bytes()
        second_local = self.base / 'second-local'
        second_remote = self.base / 'second-remote'
        second_local.mkdir()
        second_remote.mkdir()
        self.put(second_remote, name='SAVEFILE0P/save', content=b'second')
        data = json.loads(self.config.read_text())
        data['games']['second-game'] = {'local': str(second_local), 'remote': str(second_remote)}
        self.config.write_text(json.dumps(data))
        save_sync.sync(self.config, 'second-game')
        self.assertEqual((second_local / 'SAVEFILE0P/save').read_bytes(), b'second')
        self.assertEqual((self.state / 'example-game.json').read_bytes(), first_state)
        self.assertTrue((self.state / 'second-game.json').is_file())
        self.assertEqual(self.run_sync()['copies'], [])

    def test_malformed_configurations_fail_closed(self):
        original = json.loads(self.config.read_text())
        cases = [
            ('version', 2), ('version', True), ('unexpected', 1),
            ('local', 'relative/path'), ('local', str(self.local) + '/../escaped'),
            ('remote', str(self.local / 'nested')), ('state_dir', str(self.local / 'state')),
            ('include', '*.sav'), ('exclude', ['../*']), ('include', ['/absolute/*'])]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                data = json.loads(json.dumps(original))
                if key in ('local', 'remote', 'include', 'exclude'):
                    data['games']['example-game'][key] = value
                else:
                    data[key] = value
                self.config.write_text(json.dumps(data))
                with self.assertRaises(save_sync.SyncError):
                    self.run_sync()
        self.assertFalse((self.state / 'example-game.json').exists())

    def test_duplicate_json_keys_are_rejected_instead_of_last_value_wins(self):
        self.put(self.local)
        original = self.config.read_text()
        self.config.write_text(original.replace('"version": 1', '"version": 99, "version": 1'))
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.assertFalse((self.remote / 'slot.sav').exists())
        self.config.write_text(original)
        self.run_sync()
        state_path = self.state / 'example-game.json'
        raw = state_path.read_text()
        state_path.write_text(raw.replace('"version": 1', '"version": 99, "version": 1'))
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()

    def test_first_sync_different_files_requires_manual_resolution(self):
        self.put(self.local, content=b'left')
        self.put(self.remote, content=b'right')
        with self.assertRaises(save_sync.ConflictError):
            self.run_sync()
        self.assertFalse((self.state / 'example-game.json').exists())
        self.put(self.remote, content=b'left')
        self.assertEqual(self.run_sync()['copies'], [])
        self.assertEqual(set(self.baseline()['files']), {'slot.sav'})

    def test_new_nested_files_after_baseline_merge_in_each_direction(self):
        self.run_sync()
        self.put(self.local, name='a/slot.sav', content=b'left')
        self.put(self.remote, name='b/slot.sav', content=b'right')
        result = self.run_sync()
        self.assertEqual(result['copies'], [{'from': 'local', 'path': 'a/slot.sav'}, {'from': 'remote', 'path': 'b/slot.sav'}])
        self.assertEqual((self.remote / 'a/slot.sav').read_bytes(), b'left')
        self.assertEqual((self.local / 'b/slot.sav').read_bytes(), b'right')

    def test_equal_independent_changes_advance_baseline_without_copy(self):
        self.put(self.local)
        self.run_sync()
        self.put(self.local, content=b'same update')
        self.put(self.remote, content=b'same update')
        self.assertEqual(self.run_sync()['copies'], [])
        self.assertEqual(self.baseline()['files']['slot.sav'], hashlib.sha256(b'same update').hexdigest())

    def test_hardlinks_and_special_files_are_rejected(self):
        outside = self.put(self.base, name='outside.sav')
        os.link(outside, self.local / 'slot.sav')
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        (self.local / 'slot.sav').unlink()
        os.mkfifo(self.local / 'pipe')
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()

    def test_baseline_lock_and_backup_parent_symlinks_are_rejected(self):
        self.put(self.local)
        outside = self.base / 'outside'
        outside.mkdir()
        (self.state / 'sync.lock').symlink_to(outside / 'lock')
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        (self.state / 'sync.lock').unlink()
        (self.state / 'example-game.json').symlink_to(outside / 'baseline')
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        (self.state / 'example-game.json').unlink()
        self.run_sync()
        self.put(self.local, content=b'update')
        (self.state / 'backups').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'initial')
        self.assertEqual(list(outside.iterdir()), [])

    def test_destination_mutation_during_staging_is_not_overwritten(self):
        from unittest.mock import patch
        self.put(self.local)
        self.run_sync()
        self.put(self.local, content=b'update')
        before = self.baseline()
        transfer = save_sync._transfer
        def mutate_destination(source, output):
            transfer(source, output)
            self.put(self.remote, content=b'external writer')
        with patch.object(save_sync, '_transfer', mutate_destination):
            with self.assertRaises(save_sync.SyncError):
                self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'external writer')
        self.assertEqual(self.baseline(), before)

    def test_replace_failure_keeps_old_bytes_and_backup(self):
        from unittest.mock import patch
        self.put(self.local)
        self.run_sync()
        self.put(self.remote, content=b'remote update')
        before = self.baseline()
        replace = os.replace
        def failing_replace(source, dest, **kwargs):
            if dest == 'slot.sav' and os.fstat(kwargs['dst_dir_fd']).st_ino == self.local.stat().st_ino:
                raise OSError('injected rename failure')
            return replace(source, dest, **kwargs)
        with patch.object(os, 'replace', failing_replace):
            with self.assertRaises(save_sync.SyncError):
                self.run_sync()
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'initial')
        self.assertEqual(self.baseline(), before)
        backups = list((self.state / 'backups').rglob('slot.sav'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'initial')
        self.assertFalse(list(self.local.glob('.wolf-sync-*')))

    def test_cli_busy_and_unsafe_return_nonzero(self):
        import fcntl
        import subprocess
        import sys
        command = [sys.executable, str(Path(__file__).with_name('save_sync.py')), '--config', str(self.config), '--game', 'example-game']
        with (self.state / 'sync.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            busy = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(busy.returncode, 4)
            self.assertEqual(json.loads(busy.stderr)['error'], 'locked')
        self.put(self.local).unlink()
        (self.local / 'slot.sav').symlink_to(self.base / 'outside')
        unsafe = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(unsafe.returncode, 3)
        self.assertEqual(json.loads(unsafe.stderr)['error'], 'unsafe')

    def test_world_writable_state_is_rejected(self):
        self.put(self.local)
        self.state.chmod(0o777)
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.assertFalse((self.remote / 'slot.sav').exists())

    def test_file_directory_conflicts_abort_dry_run_and_preserve_both(self):
        self.put(self.local, name='slot', content=b'flat save')
        self.put(self.remote, name='slot/nested.sav', content=b'nested save')
        with self.assertRaises(save_sync.ConflictError):
            self.run_sync(dry_run=True)
        with self.assertRaises(save_sync.ConflictError) as cm:
            self.run_sync()
        archive = Path(cm.exception.archive)
        self.assertEqual((archive / 'local/slot').read_bytes(), b'flat save')
        self.assertEqual((archive / 'remote/slot/nested.sav').read_bytes(), b'nested save')
        self.assertEqual((self.local / 'slot').read_bytes(), b'flat save')
        self.assertEqual((self.remote / 'slot/nested.sav').read_bytes(), b'nested save')

    def test_orphan_staging_files_block_instead_of_syncing_partial_bytes(self):
        self.put(self.local, name='.wolf-sync-orphan', content=b'partial')
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.assertFalse((self.remote / '.wolf-sync-orphan').exists())
        self.assertEqual((self.local / '.wolf-sync-orphan').read_bytes(), b'partial')

    def test_cli_json_and_conflict_exit_status_block_launch(self):
        import subprocess
        import sys
        command = [sys.executable, str(Path(__file__).with_name('save_sync.py')), '--config', str(self.config), '--game', 'example-game']
        self.put(self.local)
        preview = subprocess.run(command + ['--dry-run'], capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(json.loads(preview.stdout)['copies'], [{'from': 'local', 'path': 'slot.sav'}])
        self.assertFalse((self.remote / 'slot.sav').exists())
        applied = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.put(self.local, content=b'left')
        self.put(self.remote, content=b'right')
        conflict = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(conflict.returncode, 2)
        error = json.loads(conflict.stderr)
        self.assertEqual(error['error'], 'conflict')
        self.assertEqual(error['paths'], ['slot.sav'])
        self.assertTrue(Path(error['archive']).is_dir())

    def test_moved_root_is_detected_before_save_commit(self):
        from unittest.mock import patch
        self.put(self.local)
        transfer = save_sync._transfer
        moved = False
        def move_destination(source, output):
            nonlocal moved
            transfer(source, output)
            if not moved:
                self.remote.rename(self.base / 'detached')
                self.remote.mkdir()
                moved = True
        with patch.object(save_sync, '_transfer', move_destination):
            with self.assertRaises(save_sync.SyncError):
                self.run_sync()
        self.assertFalse((self.state / 'example-game.json').exists())
        self.assertFalse((self.base / 'detached/slot.sav').exists())
        self.assertFalse((self.remote / 'slot.sav').exists())

    def test_identical_first_sync_and_repeated_noop_do_not_rewrite(self):
        local = self.put(self.local)
        remote = self.put(self.remote)
        before = (local.stat().st_ino, remote.stat().st_ino)
        self.assertEqual(self.run_sync()['copies'], [])
        state_path = self.state / 'example-game.json'
        state_inode = state_path.stat().st_ino
        self.assertEqual(self.run_sync()['copies'], [])
        self.assertEqual(before, (local.stat().st_ino, remote.stat().st_ino))
        self.assertEqual(state_path.stat().st_ino, state_inode)
        self.assertFalse((self.state / 'backups').exists())

    def test_baseline_is_bound_to_mapping_and_rejects_corrupt_hashes(self):
        self.put(self.local)
        self.run_sync()
        old_config = self.config.read_text()
        data = json.loads(old_config)
        data['games']['example-game']['exclude'] = ['Player*.log']
        self.config.write_text(json.dumps(data))
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.config.write_text(old_config)
        baseline = self.baseline()
        baseline['files']['slot.sav'] = 'invalid hash'
        (self.state / 'example-game.json').write_text(json.dumps(baseline))
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()

    def test_overlapping_roots_and_escaped_ids_fail_before_writes(self):
        original = json.loads(self.config.read_text())
        for game, field, value in [('example-game', 'remote', str(self.local)), ('../escaped', 'remote', str(self.remote))]:
            with self.subTest(game=game):
                data = json.loads(json.dumps(original))
                mapping = data['games'].pop('example-game')
                mapping[field] = value
                data['games'][game] = mapping
                self.config.write_text(json.dumps(data))
                with self.assertRaises(save_sync.SyncError):
                    save_sync.sync(self.config, game)
                self.assertFalse((self.base / 'escaped.json').exists())
        self.config.write_text(json.dumps(original))

    def test_include_exclude_filters_keep_logs_and_settings_independent(self):
        data = json.loads(self.config.read_text())
        data['games']['example-game'].update(include=['*.dat', '*.info', 'backups/*'], exclude=['Player*.log', 'backups/*.log'])
        self.config.write_text(json.dumps(data))
        for name in ('1.dat', '1.info', 'backups/1.dat', 'Player.log', 'Player-prev.log', 'screeninfo.cfg', 'backups/Player.log'):
            self.put(self.local, name=name)
        result = self.run_sync()
        self.assertEqual([item['path'] for item in result['copies']], ['1.dat', '1.info', 'backups/1.dat'])
        self.assertEqual(set(self.baseline()['files']), {'1.dat', '1.info', 'backups/1.dat'})
        for name in ('Player.log', 'Player-prev.log', 'screeninfo.cfg', 'backups/Player.log'):
            self.assertFalse((self.remote / name).exists())

    def test_source_mutation_during_copy_aborts_before_any_save_replacement(self):
        from unittest.mock import patch
        self.put(self.local, name='a.sav', content=b'a')
        changed = self.put(self.local, name='b.sav', content=b'b')
        changed_inode = changed.stat().st_ino

        def copying_while_writer_is_active(source, output):
            while chunk := source.read(65536):
                output.write(chunk)
            if os.fstat(source.fileno()).st_ino == changed_inode:
                changed.write_bytes(b'changed during copy')

        with patch.object(save_sync, '_transfer', copying_while_writer_is_active, create=True):
            with self.assertRaises(save_sync.SyncError):
                self.run_sync()
        self.assertEqual(list(self.remote.rglob('*')), [])
        self.assertFalse((self.state / 'example-game.json').exists())

    def test_lock_contention_fails_closed_and_release_allows_retry(self):
        import fcntl
        self.put(self.local)
        with (self.state / 'sync.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(save_sync.LockError):
                self.run_sync()
            self.assertFalse((self.remote / 'slot.sav').exists())
        self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'initial')

    def test_links_are_rejected_even_when_nested_or_in_root_ancestors(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.put(outside, content=b'outside')
        for name, target in [('slot.sav', outside / 'slot.sav'), ('escape', outside)]:
            with self.subTest(name=name):
                link = self.local / name
                link.symlink_to(target)
                with self.assertRaises(save_sync.SyncError):
                    self.run_sync()
                link.unlink()
        alias = self.base / 'alias'
        alias.symlink_to(self.local, target_is_directory=True)
        data = json.loads(self.config.read_text())
        data['games']['example-game']['local'] = str(alias)
        self.config.write_text(json.dumps(data))
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.assertEqual((outside / 'slot.sav').read_bytes(), b'outside')

    def test_overwrites_are_atomic_and_backup_previous_bytes(self):
        self.put(self.local)
        self.run_sync()
        # A reader holding the old inode must still see the complete old save.
        with (self.remote / 'slot.sav').open('rb') as reader:
            self.put(self.local, content=b'new version')
            result = self.run_sync()
            self.assertEqual(reader.read(), b'initial')
        backups = list((self.state / 'backups').rglob('slot.sav'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'initial')
        self.assertEqual(result['backups'], [str(backups[0])])
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'new version')
        self.assertEqual((self.remote / 'slot.sav').stat().st_mode & 0o777, 0o600)

    def test_dry_run_reports_plan_without_writing_saves_or_baseline(self):
        self.put(self.remote, name='nested/new.sav')
        result = self.run_sync(dry_run=True)
        self.assertEqual(result['copies'], [{'from': 'remote', 'path': 'nested/new.sav'}])
        self.assertEqual(list(self.local.iterdir()), [])
        self.assertFalse((self.state / 'example-game.json').exists())
        self.put(self.local, name='nested/new.sav', content=b'different')
        with self.assertRaises(save_sync.ConflictError) as cm:
            self.run_sync(dry_run=True)
        self.assertIsNone(cm.exception.archive)
        self.assertFalse((self.state / 'conflicts').exists())

    def test_missing_files_are_resurrected_and_double_deletion_blocks(self):
        self.put(self.local)
        self.run_sync()
        (self.local / 'slot.sav').unlink()
        self.run_sync()
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'initial')
        (self.remote / 'slot.sav').unlink()
        self.put(self.local, content=b'updated survivor')
        self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'updated survivor')
        before = self.baseline()
        (self.local / 'slot.sav').unlink()
        (self.remote / 'slot.sav').unlink()
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()
        self.assertEqual(before, self.baseline())

    def test_conflicts_preserve_both_abort_all_copies_and_keep_baseline(self):
        self.put(self.local)
        self.run_sync()
        before = self.baseline()
        self.put(self.local, content=b'left')
        self.put(self.remote, content=b'right')
        self.put(self.local, name='unrelated.sav')
        with self.assertRaises(save_sync.ConflictError) as cm:
            self.run_sync()
        self.assertEqual(cm.exception.paths, ['slot.sav'])
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'left')
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'right')
        self.assertFalse((self.remote / 'unrelated.sav').exists())
        self.assertEqual(before, self.baseline())
        archive = Path(cm.exception.archive)
        self.assertEqual((archive / 'local/slot.sav').read_bytes(), b'left')
        self.assertEqual((archive / 'remote/slot.sav').read_bytes(), b'right')

    def test_changes_propagate_in_each_direction_using_common_baseline(self):
        self.put(self.local)
        self.run_sync()
        self.put(self.local, content=b'local update')
        self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'local update')
        self.put(self.remote, content=b'remote update')
        self.run_sync()
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'remote update')

    def test_first_sync_copies_one_sided_file_and_records_hash(self):
        self.put(self.local)
        result = self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'initial')
        self.assertEqual(result['copies'], [{'from': 'local', 'path': 'slot.sav'}])
        self.assertEqual(self.baseline()['files'], {'slot.sav': hashlib.sha256(b'initial').hexdigest()})


    def test_unstable_device_number_after_reboot_is_accepted_and_migrated(self):
        # Btrfs anonymous device numbers change across reboots; inode identity must suffice.
        self.put(self.local)
        self.run_sync()
        path = self.state / 'example-game.json'
        doc = json.loads(path.read_text())
        doc['roots'] = {side: [12345, value[1]] for side, value in doc['roots'].items()}
        path.write_text(json.dumps(doc, sort_keys=True))
        self.put(self.local, content=b'after reboot')
        self.run_sync()
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'after reboot')
        self.assertNotEqual(self.baseline()['roots']['local'][0], 12345)

    def test_replaced_root_directory_is_still_rejected(self):
        self.put(self.local)
        self.run_sync()
        self.remote.rename(self.base / 'old-remote')
        self.remote.mkdir()
        self.put(self.remote)
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()


class NewestWinsTests(unittest.TestCase):
    """Opt-in conflict_policy=newest: whole save set from the newer side wins."""
    run_sync, put, baseline = SyncTests.run_sync, SyncTests.put, SyncTests.baseline

    def setUp(self):
        SyncTests.setUp(self)
        data = json.loads(self.config.read_text())
        data['games']['example-game']['conflict_policy'] = 'newest'
        self.config.write_text(json.dumps(data))

    def touch(self, path, offset):
        stamp = time.time() + offset
        os.utime(path, (stamp, stamp))

    def diverge(self, local_age, remote_age):
        self.put(self.local)
        self.put(self.local, name='other.sav', content=b'other')
        self.run_sync()
        self.touch(self.put(self.local, content=b'left'), local_age)
        self.touch(self.put(self.remote, content=b'right'), remote_age)

    def test_newer_remote_wins_and_local_is_backed_up(self):
        self.diverge(-600, -60)
        result = self.run_sync()
        self.assertEqual(result['resolution']['winner'], 'remote')
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'right')
        backups = [Path(p) for p in result['backups']]
        self.assertIn(b'left', [p.read_bytes() for p in backups])
        self.assertEqual(self.baseline()['files']['slot.sav'], hashlib.sha256(b'right').hexdigest())

    def test_newer_local_wins(self):
        self.diverge(-30, -900)
        result = self.run_sync()
        self.assertEqual(result['resolution']['winner'], 'local')
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'left')

    def test_whole_set_follows_winner_even_for_loser_only_edits(self):
        self.diverge(-600, -60)
        self.touch(self.put(self.local, name='other.sav', content=b'local-only edit'), -600)
        result = self.run_sync()
        self.assertEqual(result['resolution']['winner'], 'remote')
        self.assertEqual((self.local / 'other.sav').read_bytes(), b'other')
        self.assertIn(b'local-only edit', [Path(p).read_bytes() for p in result['backups']])

    def test_loser_new_files_are_kept_not_deleted(self):
        self.diverge(-600, -60)
        self.touch(self.put(self.local, name='slot2.sav', content=b'new slot'), -600)
        self.run_sync()
        self.assertEqual((self.remote / 'slot2.sav').read_bytes(), b'new slot')

    def test_near_tie_still_aborts_and_preserves_both(self):
        self.diverge(-100, -99.5)
        before = self.baseline()
        with self.assertRaises(save_sync.ConflictError) as cm:
            self.run_sync()
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'left')
        self.assertEqual((self.remote / 'slot.sav').read_bytes(), b'right')
        self.assertEqual(before, self.baseline())
        self.assertTrue(Path(cm.exception.archive).is_dir())

    def test_future_timestamp_aborts(self):
        self.diverge(-600, 3600)
        with self.assertRaises(save_sync.ConflictError):
            self.run_sync()
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'left')

    def test_dry_run_reports_winner_without_writing(self):
        self.diverge(-600, -60)
        result = self.run_sync(dry_run=True)
        self.assertEqual(result['resolution']['winner'], 'remote')
        self.assertEqual((self.local / 'slot.sav').read_bytes(), b'left')

    def test_file_directory_clash_still_aborts(self):
        self.put(self.local)
        self.run_sync()
        (self.remote / 'slot.sav').unlink()
        self.put(self.remote, name='slot.sav/inner', content=b'dir')
        with self.assertRaises(save_sync.ConflictError):
            self.run_sync()

    def test_invalid_policy_rejected(self):
        data = json.loads(self.config.read_text())
        data['games']['example-game']['conflict_policy'] = 'last-writer'
        self.config.write_text(json.dumps(data))
        with self.assertRaises(save_sync.SyncError):
            self.run_sync()

    def test_policy_does_not_invalidate_existing_baseline(self):
        data = json.loads(self.config.read_text())
        del data['games']['example-game']['conflict_policy']
        self.config.write_text(json.dumps(data))
        self.put(self.local)
        self.run_sync()
        data['games']['example-game']['conflict_policy'] = 'newest'
        self.config.write_text(json.dumps(data))
        self.assertEqual(self.run_sync()['copies'], [])


if __name__ == '__main__':
    unittest.main()
