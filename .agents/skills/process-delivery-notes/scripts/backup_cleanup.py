"""Read-only monthly backup eligibility. Actual deletion is in the PowerShell runner."""
import argparse
import calendar
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8), 'Asia/Shanghai')
BATCH = re.compile(r'delivery-batch-(\d{8})-(\d{6})')
BOOKS = {'.xlsx', '.xls', '.xlsm'}
PHOTOS = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp', '.heic'}
REJECTED = 'rejected_duplicate_photo_keep_existing_archives'
BUSINESS = ('pending_root', 'ledger_root', 'primary_archive_root', 'settlement_archive_root')


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def hash_text(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value):
        raise ValueError('missing_or_invalid_hash')
    return value.lower()


def absolute(value):
    p = Path(value)
    if not p.is_absolute() or '..' in p.parts or any(':' in x for x in p.parts[1:]):
        raise ValueError('absolute_path_without_traversal_required')
    return Path(os.path.abspath(p))


def inside(path, root):
    path, root = absolute(path), absolute(root)
    if path == root or not path.is_relative_to(root):
        raise ValueError('path_outside_expected_root: '+str(path))
    return path


def safe_path(path, cloud_leaf=False):
    """Reject redirected ancestors; only observed Nutstore data-file tags are readable."""
    path = absolute(path)
    for part in reversed((path, *path.parents)):
        try:
            s = part.lstat()
        except FileNotFoundError:
            continue
        tag = getattr(s, 'st_reparse_tag', 0)
        reparse = getattr(s, 'st_file_attributes', 0) & 0x400
        if stat.S_ISLNK(s.st_mode) or reparse:
            if not (cloud_leaf and part == path and stat.S_ISREG(s.st_mode) and tag == 0x9000601A):
                raise ValueError('redirected_or_reparse_path: '+str(part))
    if path.resolve() != path:
        raise ValueError('resolved_path_changed: '+str(path))
    return path


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return result.astimezone(BEIJING)


def cutoff(now):
    now = now.astimezone(BEIJING)
    if now.day == calendar.monthrange(now.year, now.month)[1] and now.hour >= 23:
        return now
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class Evidence:
    def __init__(self, settings):
        self.settings = settings
        self.root = safe_path(settings['backup_batch_root'])
        self.files = {}
        self.cache = {}
        for key in BUSINESS:
            business = absolute(settings[key])
            if self.root == business or self.root.is_relative_to(business) or business.is_relative_to(self.root):
                raise ValueError('backup_root_overlaps_business_root')

    def read(self, path):
        path = safe_path(inside(path, self.root))
        before = sha(path)
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if sha(path) != before:
            raise ValueError('evidence_changed_during_read')
        self.files[str(path)] = before
        return data

    def batch_path(self, value):
        p = safe_path(inside(value, self.root))
        if p.parent != self.root or not BATCH.fullmatch(p.name) or not p.is_dir():
            raise ValueError('invalid_batch_directory')
        return p

    def ledger_path(self, value):
        p = absolute(value)
        if not any(p.is_relative_to(absolute(self.settings[k])) for k in ('ledger_root', 'settlement_archive_root')):
            raise ValueError('unexpected_business_workbook')
        if p.suffix.lower() not in BOOKS or not safe_path(p, True).is_file():
            raise ValueError('business_workbook_missing')
        return p

    def load(self, batch, stack=()):
        batch = self.batch_path(batch)
        if batch in stack:
            raise ValueError('resolution_cycle')
        if batch in self.cache:
            return self.cache[batch]
        completion = self.read(batch/'completion.json')
        progress = self.read(batch/'progress.json')
        manifest = self.read(batch/'backup-manifest.json')
        if not isinstance(progress, list) or not progress or not isinstance(manifest, list) or not manifest:
            raise ValueError('missing_progress_or_backup_records')
        if completion.get('status') not in (None, 'completed', 'completed_after_confirmations'):
            raise ValueError('batch_not_completed')
        if completion.get('pending_in_folder') != [] or any(completion.get(k) for k in ('pending_notes', 'failed', 'failures', 'errors')):
            raise ValueError('pending_or_failed_items')
        if completion.get('handles_released') is not True:
            raise ValueError('batch_handles_not_released')
        if completion.get('notes_completed', 0) + completion.get('remaining_notes_resolved', 0) != len(progress):
            raise ValueError('completion_count_does_not_cover_progress')
        if completion.get('source_cleaned', 0) + completion.get('remaining_notes_resolved', 0) != len(progress):
            raise ValueError('cleanup_count_does_not_cover_progress')
        # Legacy batches have per-workbook disk reports instead of per-note stages.
        verified = []
        for path in sorted(batch.glob('*-disk-verified.json')):
            data = self.read(path)
            if data.get('disk_verified') is not True:
                raise ValueError('disk_verification_failed')
            hash_text(data.get('ledger_sha256'))
            verified.append(self.ledger_path(data['source']))
        if absolute(self.settings['distribution_ledger']) not in verified:
            raise ValueError('missing_distribution_disk_verification')
        resolver = completion.get('resolved_by_batch')
        resolved_progress = {}
        resolution = None
        if resolver:
            target = self.batch_path(resolver)
            resolution = self.read(batch/'resolution.json')
            if absolute(resolution.get('batch', '')) != target:
                raise ValueError('resolution_target_mismatch')
            _, later, _ = self.load(target, (*stack, batch))
            resolved_progress = {r.get('note', r.get('delivery_no')): r for r in later}
        for row in progress:
            if row.get('status') not in ('cleaned', 'cleaned_duplicate_keep_existing'):
                raise ValueError('progress_not_cleaned')
            if not row.get('overview_rows'):
                raise ValueError('missing_saved_overview_rows')
            source = inside(row['source_file'], self.settings['pending_root'])
            factory = source.is_relative_to(absolute(self.settings['factory_pending_root']))
            if not factory and (not row.get('ledger_rows') or not any(p.is_relative_to(absolute(self.settings['ledger_root'])) for p in verified)):
                raise ValueError('missing_transport_disk_verification')
            if row.get('resolved_by_batch'):
                note = row.get('note', row.get('delivery_no'))
                if not resolver or absolute(row['resolved_by_batch']) != absolute(resolver) or note not in resolution.get('resolved_notes', []):
                    raise ValueError('unproven_resolved_note')
                later = resolved_progress.get(note)
                if not later or later['status'] != row['status']:
                    raise ValueError('resolution_progress_mismatch')
                for field in ('primary_target', 'settlement_target', 'primary_sha256', 'settlement_sha256'):
                    if str(row.get(field, '')).lower() != str(later.get(field, '')).lower():
                        raise ValueError('resolution_archive_mismatch')
                if row['source_sha256'].lower() != later['source_sha256'].lower() and row.get('reviewed_backup_sha256', '').lower() != row['source_sha256'].lower():
                    raise ValueError('unreviewed_resolved_photo_change')
        self.cache[batch] = (completion, progress, manifest)
        return self.cache[batch]

    def archive(self, path, digest, kind):
        path = safe_path(inside(path, self.settings[kind+'_archive_root']), True)
        digest = hash_text(digest)
        if not path.is_file() or sha(path) != digest:
            raise ValueError('archive_missing_or_changed: '+str(path))
        self.files[str(path)] = digest

    def photo(self, batch, record, progress):
        digest = hash_text(record['sha256'])
        matches = [r for r in progress if absolute(r['source_file']) == absolute(record['source']) and hash_text(r.get('source_sha256')) == digest]
        if len(matches) != 1:
            raise ValueError('photo_progress_not_unique')
        row = matches[0]
        source = inside(record['source'], self.settings['pending_root'])
        factory = source.is_relative_to(absolute(self.settings['factory_pending_root']))
        expected = digest
        if record.get('disposition') == REJECTED:
            if row.get('disposition') != REJECTED or not record.get('user_decision'):
                raise ValueError('rejected_photo_decision_missing')
            decision = self.read(record['decision_evidence'])
            decision_text = decision.get('user_message', decision.get('user_decision', ''))
            if record['user_decision'] not in decision_text:
                raise ValueError('user_decision_not_found')
            result = self.read(record['resolution_report'])
            expected = hash_text(record['authoritative_archive_sha256'])
            if result.get('disposition') != REJECTED or result.get('cleanup_status') != 'deleted_rejected_duplicate' or result.get('review_status') != 'same_physical_note_verified':
                raise ValueError('rejected_photo_not_resolved')
            if result.get('delivery_no') != row.get('note', row.get('delivery_no')) or result.get('user_decision') != record['user_decision']:
                raise ValueError('rejected_photo_identity_mismatch')
            if hash_text(result.get('source_sha256')) != digest and hash_text(row.get('reviewed_backup_sha256')) != digest:
                raise ValueError('rejected_backup_not_reviewed')
            if hash_text(result.get('authoritative_archive_sha256')) != expected:
                raise ValueError('rejected_photo_archive_hash_mismatch')
            for key in ('primary_target', 'settlement_target'):
                if absolute(result[key]) != absolute(row[key]) or absolute(record[key]) != absolute(row[key]):
                    raise ValueError('rejected_photo_archive_path_mismatch')
        elif row.get('disposition') == REJECTED:
            raise ValueError('rejected_backup_manifest_missing_disposition')
        for kind in (('settlement',) if factory else ('primary', 'settlement')):
            if hash_text(row.get(kind+'_sha256')) != expected:
                raise ValueError('recorded_archive_hash_mismatch')
            self.archive(row[kind+'_target'], expected, kind)


def plan(settings, now=None, only_batch=None):
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    boundary = cutoff(now)
    evidence = Evidence(settings)
    paths = [evidence.batch_path(only_batch)] if only_batch else sorted(p for p in evidence.root.iterdir() if BATCH.fullmatch(p.name))
    batches = []
    for batch in paths:
        result = {'batch': str(batch), 'status': 'blocked', 'files': []}
        batches.append(result)
        try:
            batch = evidence.batch_path(batch)
            _, progress, manifest = evidence.load(batch)
            backup_root = safe_path(batch/'backups')
            photo_records = [r for r in manifest if Path(r['backup']).suffix.lower() in PHOTOS]
            for row in progress:
                if sum(absolute(r['source']) == absolute(row['source_file']) and hash_text(r['sha256']) == hash_text(row['source_sha256']) for r in photo_records) != 1:
                    raise ValueError('progress_photo_not_covered_by_backup_manifest')
            registered = set()
            for record in manifest:
                path = safe_path(inside(record['backup'], backup_root))
                if path in registered:
                    raise ValueError('duplicate_registered_backup')
                registered.add(path)
                kind = 'ledger' if path.suffix.lower() in BOOKS else 'photo' if path.suffix.lower() in PHOTOS else None
                if not kind:
                    raise ValueError('unapproved_backup_extension')
                digest = hash_text(record['sha256'])
                if kind == 'photo':
                    evidence.photo(batch, record, progress)
                else:
                    evidence.ledger_path(record['source'])
                created = timestamp(record['time'])
                batch_started = datetime.strptime(batch.name, 'delivery-batch-%Y%m%d-%H%M%S').replace(tzinfo=BEIJING)
                if created < batch_started:
                    raise ValueError('backup_timestamp_precedes_batch')
                if created > now:
                    raise ValueError('backup_timestamp_in_future')
                present = path.exists()
                if present and (not path.is_file() or sha(path) != digest):
                    raise ValueError('backup_hash_changed: '+str(path))
                month_end_window = now.day == calendar.monthrange(now.year, now.month)[1] and now.hour >= 23
                eligible = created <= boundary if month_end_window else created < boundary
                result['files'].append({'path': str(path), 'backup_root': str(backup_root), 'kind': kind,
                                        'sha256': digest, 'size': path.stat().st_size if present else 0,
                                        'status': 'already_absent' if not present else 'eligible' if eligible else 'not_due'})
            # Unregistered files are never candidates and remain in place.
            result['unregistered_files'] = []
            for directory, dirs, names in os.walk(backup_root, followlinks=False):
                for name in list(dirs):
                    path = Path(directory)/name
                    try: safe_path(path)
                    except ValueError:
                        dirs.remove(name)
                        result['unregistered_files'].append(str(path))
                result['unregistered_files'].extend(str(Path(directory)/n) for n in names if Path(directory)/n not in registered)
            result['status'] = 'ready' if any(r['status'] == 'eligible' for r in result['files']) else 'retained'
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            result.update(status='blocked', reason=str(exc))
            for row in result['files']:
                row['status'] = 'blocked_batch'
    eligible = [f for b in batches if b['status'] == 'ready' for f in b['files'] if f['status'] == 'eligible']
    return {'schema_version': 1, 'read_only': True, 'now': now.isoformat(), 'cutoff': boundary.isoformat(),
            'backup_batch_root': str(evidence.root), 'batches': batches, 'evidence_files': evidence.files,
            'summary': {'eligible_files': len(eligible), 'eligible_bytes': sum(f['size'] for f in eligible),
                        'blocked_batches': sum(b['status'] == 'blocked' for b in batches),
                        'not_due': sum(f['status'] == 'not_due' for b in batches for f in b['files'])}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--as-of', help='Read-only simulation; never accepted by the execution runner')
    parser.add_argument('--batch')
    args = parser.parse_args()
    settings_path = safe_path(args.settings)
    settings_hash = sha(settings_path)
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    out = safe_path(args.report)
    root = safe_path(settings['backup_batch_root'])
    if out == settings_path or out.exists() or not out.parent.is_dir():
        raise ValueError('choose_new_report_in_existing_directory')
    for key in BUSINESS:
        if out.is_relative_to(absolute(settings[key])):
            raise ValueError('report_inside_business_root')
    for parent in out.parents:
        if parent.parent == root and BATCH.fullmatch(parent.name):
            raise ValueError('report_inside_batch')
    result = plan(settings, timestamp(args.as_of) if args.as_of else None, args.batch)
    if sha(settings_path) != settings_hash:
        raise ValueError('settings_changed_during_preflight')
    result['settings_sha256'] = settings_hash
    result['simulation'] = bool(args.as_of)
    with out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
