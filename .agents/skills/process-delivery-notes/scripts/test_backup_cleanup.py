import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import backup_cleanup as bc


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='delivery-cleanup-test-')
        self.root=Path(self.temp.name)
        self.settings={k:str(self.root/v) for k,v in dict(backup_batch_root='outputs',pending_root='pending',factory_pending_root='pending/factory',ledger_root='ledgers',primary_archive_root='primary',settlement_archive_root='settlement').items()}
        for p in self.settings.values():Path(p).mkdir(parents=True,exist_ok=True)
        self.settings['distribution_ledger']=str(self.root/'settlement/main.xlsx')
        self.main=Path(self.settings['distribution_ledger']);self.main.write_bytes(b'main now')
        self.book=self.root/'ledgers/transport.xlsx';self.book.write_bytes(b'transport now')
        self.source=self.root/'pending/original.jpg'
        self.primary=self.root/'primary/note.jpg';self.primary.write_bytes(b'photo')
        self.settlement=self.root/'settlement/note.jpg';self.settlement.write_bytes(b'photo')
        self.batch=self.root/'outputs/delivery-batch-20200101-120000';(self.batch/'backups').mkdir(parents=True)
        self.manifest=[]
        for source,data in ((self.main,b'main before'),(self.book,b'transport before'),(self.source,b'photo')):
            target=self.batch/'backups'/source.name;target.write_bytes(data)
            self.manifest.append(dict(source=str(source),backup=str(target),sha256=bc.sha(target),time='2020-01-01T12:00:00+08:00'))
        self.progress=[dict(source_file=str(self.source),source_sha256=bc.sha(self.primary),note='P-XY-00001',status='cleaned',ledger_rows=[10],overview_rows=[20],primary_target=str(self.primary),settlement_target=str(self.settlement),primary_sha256=bc.sha(self.primary),settlement_sha256=bc.sha(self.settlement))]
        self.completion=dict(status='completed',notes_completed=1,source_cleaned=1,pending_in_folder=[],pending_notes=[],handles_released=True)
        self.write(self.batch/'main-disk-verified.json',dict(source=str(self.main),disk_verified=True,ledger_sha256=bc.sha(self.main)))
        self.write(self.batch/'transport-disk-verified.json',dict(source=str(self.book),disk_verified=True,ledger_sha256=bc.sha(self.book)))
        self.save()
        self.now=bc.timestamp('2026-10-31T23:00:00+08:00')

    def tearDown(self):self.temp.cleanup()
    def write(self,path,data):path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    def save(self):
        self.write(self.batch/'backup-manifest.json',self.manifest)
        self.write(self.batch/'progress.json',self.progress)
        self.write(self.batch/'completion.json',self.completion)
    def plan(self):return bc.plan(self.settings,self.now)
    def blocked(self,reason):
        result=self.plan();self.assertEqual(result['summary']['eligible_files'],0);self.assertIn(reason,result['batches'][0]['reason'])

    def test_complete_and_read_only(self):
        self.assertEqual(self.plan()['summary']['eligible_files'],3)
        self.assertTrue(all(Path(r['backup']).exists() for r in self.manifest))
    def test_legacy_completion(self):
        del self.completion['status'];self.save();self.assertEqual(self.plan()['summary']['eligible_files'],3)
    def test_unfinished(self):
        self.completion['pending_notes']=['P'];self.save();self.blocked('pending_or_failed')
    def test_missing_archive_retains_whole_batch(self):
        self.primary.unlink();self.blocked('archive_missing')
    def test_changed_archive(self):
        self.primary.write_bytes(b'changed');self.blocked('archive_missing_or_changed')
    def test_changed_backup(self):
        Path(self.manifest[0]['backup']).write_bytes(b'changed');self.blocked('backup_hash_changed')
    def test_path_escape(self):
        self.manifest[0]['backup']=str(self.main);self.save();self.blocked('path_outside')
    def test_unregistered_retained(self):
        unregistered=self.batch/'backups/unregistered.jpg';unregistered.write_bytes(b'leave')
        self.assertEqual(self.plan()['summary']['eligible_files'],3)
        self.assertIn(str(unregistered),self.plan()['batches'][0]['unregistered_files'])
    def test_missing_disk_proof(self):
        (self.batch/'main-disk-verified.json').unlink();self.blocked('missing_distribution')
    def test_newer_ledger_is_normal(self):
        self.main.write_bytes(b'later legitimate data');self.assertEqual(self.plan()['summary']['eligible_files'],3)
    def test_deleted_file_retry(self):
        Path(self.manifest[0]['backup']).unlink()
        result=self.plan();self.assertEqual(result['summary']['eligible_files'],2)
        self.assertEqual(result['batches'][0]['files'][0]['status'],'already_absent')
    def test_month_end_delay_and_current_month(self):
        for r in self.manifest:r['time']='2026-10-12T12:00:00+08:00'
        self.save();self.now=bc.timestamp('2026-10-31T22:59:59+08:00')
        self.assertEqual(self.plan()['summary']['not_due'],3)
        self.now=bc.timestamp('2026-10-31T23:00:00+08:00');self.assertEqual(self.plan()['summary']['eligible_files'],3)
        self.now=bc.timestamp('2026-11-02T09:00:00+08:00');self.assertEqual(self.plan()['summary']['eligible_files'],3)
        self.manifest[0]['time']='2026-11-01T00:00:00+08:00';self.save();self.assertEqual(self.plan()['summary']['eligible_files'],2)
        self.now=bc.timestamp('2026-11-01T00:00:00+08:00');self.assertEqual(self.plan()['summary']['eligible_files'],2)
    def test_leap_month_and_timezone(self):
        self.assertEqual(bc.cutoff(bc.timestamp('2028-02-29T15:00:00+00:00')).day,29)
        self.assertEqual(bc.cutoff(bc.timestamp('2028-02-28T23:00:00+08:00')).day,1)
    def reject_photo(self):
        r=self.manifest[-1];Path(r['backup']).write_bytes(b'rejected new photo');r['sha256']=bc.sha(r['backup'])
        self.progress[0].update(source_sha256=r['sha256'],status='cleaned_duplicate_keep_existing',disposition=bc.REJECTED)
        r.update(disposition=bc.REJECTED,user_decision='00001保留旧版',decision_evidence=str(self.batch/'decision.json'),resolution_report=str(self.batch/'duplicate-result.json'),authoritative_archive_sha256=bc.sha(self.primary),primary_target=str(self.primary),settlement_target=str(self.settlement))
        self.write(self.batch/'decision.json',dict(user_message='00001保留旧版'))
        report=dict(delivery_no='P-XY-00001',source_sha256=r['sha256'],disposition=bc.REJECTED,cleanup_status='deleted_rejected_duplicate',review_status='same_physical_note_verified',user_decision=r['user_decision'],authoritative_archive_sha256=r['authoritative_archive_sha256'],primary_target=str(self.primary),settlement_target=str(self.settlement))
        self.write(self.batch/'duplicate-result.json',report);self.save()
    def test_rejected_new_version(self):
        self.reject_photo();self.assertEqual(self.plan()['summary']['eligible_files'],3)
    def test_rejected_missing_decision(self):
        self.reject_photo();self.write(self.batch/'decision.json',dict(user_message='different decision'));self.blocked('user_decision_not_found')
    def test_factory_single_archive(self):
        self.manifest[-1]['source']=str(self.root/'pending/factory/original.jpg')
        self.progress[0]['source_file']=self.manifest[-1]['source'];self.progress[0].pop('ledger_rows')
        self.primary.unlink();(self.batch/'transport-disk-verified.json').unlink();self.save()
        self.assertEqual(self.plan()['summary']['eligible_files'],3)
    def test_resolved_batch(self):
        later=self.batch.with_name('delivery-batch-20200102-120000');shutil.copytree(self.batch,later)
        self.completion.update(status='completed_after_confirmations',notes_completed=0,source_cleaned=0,remaining_notes_resolved=1,resolved_by_batch=str(later))
        self.progress[0]['resolved_by_batch']=str(later)
        self.write(self.batch/'resolution.json',dict(batch=str(later),resolved_notes=['P-XY-00001']))
        later_manifest=copy.deepcopy(self.manifest)
        for r in later_manifest:
            r['backup']=str(later/'backups'/Path(r['backup']).name)
            r['time']='2020-01-02T12:00:00+08:00'
        self.write(later/'backup-manifest.json',later_manifest);self.save()
        self.assertEqual(self.plan()['summary']['eligible_files'],6)
        completion=json.loads((later/'completion.json').read_text());completion['status']='pending';self.write(later/'completion.json',completion)
        self.assertEqual(self.plan()['summary']['eligible_files'],0)
    def test_resolution_cycle(self):
        self.completion['resolved_by_batch']=str(self.batch);self.write(self.batch/'resolution.json',dict(batch=str(self.batch),resolved_notes=[]));self.save();self.blocked('resolution_cycle')
    def test_reparse_backup_rejected(self):
        target=Path(self.manifest[0]['backup'])
        real_lstat=Path.lstat
        from types import SimpleNamespace
        def lstat(path,*args,**kwargs):
            result=real_lstat(path,*args,**kwargs)
            if path == target:return SimpleNamespace(st_mode=result.st_mode,st_file_attributes=0x400,st_reparse_tag=0xA000000C)
            return result
        with patch.object(Path,'lstat',lstat):self.blocked('redirected_or_reparse')
    def test_real_junction_ancestor_escape(self):
        shell=shutil.which('pwsh') or shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        link=self.batch/'backups/redirect'
        command="New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+str(self.main.parent).replace("'","''")+"' | Out-Null"
        result=subprocess.run([shell,'-NoProfile','-Command',command],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        try:
            self.manifest[0]['backup']=str(link/self.main.name);self.save()
            self.blocked('redirected_or_reparse')
            result,_=self.invoke('-Execute');self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertTrue(self.main.exists() and self.primary.exists())
        finally:
            self.assertTrue(link.absolute().is_relative_to(self.root.absolute()))
            link.rmdir()  # Remove only the junction, not the target tree.
    def test_incomplete_photo_manifest(self):
        self.manifest.pop();self.save();self.blocked('progress_photo_not_covered')
    def test_backup_date_cannot_predate_batch(self):
        self.manifest[0]['time']='2019-12-01T00:00:00+08:00';self.save();self.blocked('timestamp_precedes_batch')
    def test_interrupted_execution_retries_remaining_files(self):
        Path(self.manifest[0]['backup']).unlink()
        result,report=self.invoke('-Execute');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        summary=json.loads(Path(str(report)+'.result.json').read_text())['summary']
        self.assertEqual((summary['deleted_ledgers'],summary['deleted_photos']),(1,1))
        self.assertFalse(any(Path(r['backup']).exists() for r in self.manifest))
    def invoke(self,*flags):
        shell=shutil.which('pwsh') or shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        settings=self.root/'settings.json';self.write(settings,self.settings)
        report=self.root/('run-'+str(len(list(self.root.glob('run-*.json'))))+'.json')
        cmd=[shell,'-NoProfile','-File',str(Path(__file__).with_name('cleanup-delivery-backups.ps1')),'-SettingsPath',str(settings),'-PythonPath',sys.executable,'-ReportPath',str(report),*flags]
        result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        return result,report
    def test_runner_preview_execute_and_retry(self):
        result,report=self.invoke();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(Path(self.manifest[0]['backup']).exists())
        result,report=self.invoke('-Execute');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        summary=json.loads(Path(str(report)+'.result.json').read_text())['summary']
        self.assertEqual((summary['deleted_ledgers'],summary['deleted_photos']),(2,1))
        self.assertTrue(self.main.exists() and self.primary.exists())
        result,report=self.invoke('-Execute');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(Path(str(report)+'.result.json').read_text())['summary']['deleted_ledgers'],0)
    def test_execute_rejects_simulated_time(self):
        result,_=self.invoke('-Execute','-AsOf','2026-10-31T23:00:00+08:00')
        self.assertNotEqual(result.returncode,0);self.assertTrue(Path(self.manifest[0]['backup']).exists())
    def test_runner_blocks_changed_backup(self):
        Path(self.manifest[0]['backup']).write_bytes(b'changed')
        result,_=self.invoke('-Execute');self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertTrue(all(Path(r['backup']).exists() for r in self.manifest))


if __name__=='__main__':unittest.main()
