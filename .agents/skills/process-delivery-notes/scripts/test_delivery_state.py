import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from delivery_state import State, digest, now, cleanup_blockers
from rules_data import outputs


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.rules=self.root/'rules.md';self.rules.write_text('完整规则\n'+('不要重复录入\n'*80),encoding='utf-8')
        self.proof=self.root/'evidence.json';self.proof.write_text('{"readback":"verified"}',encoding='utf-8')
        self.s=State(self.root/'state',create=True)

    def tearDown(self):self.s.close();self.tmp.cleanup()

    def start(self):
        c=self.s.prepare_read(self.rules,page_chars=200)
        for n in range(1,c['pages']+1):self.s.page(c['receipt'],n);self.s.mark_shown(c['receipt'],n)
        return self.s.begin('processing','test scope',c['receipt'])

    def event(self, key='one',status='problem',check='数量',stage='quantity'):
        return dict(event_key=key,object={'key':'P-N-0001:line1','note':'P-N-0001','scope':'原单第1条；表Q3','project':'P'},
                    check=check,stage=stage,status=status,checked_at=now(),result='原单2吨，台账1吨',
                    action='核对，未修改',next='核对原单',verified=True,
                    evidence=[{'path':str(self.proof),'sha256':digest(self.proof),'kind':'workbook_disk_read','observation':'读取Q3及对应原单'}])

    def test_full_content_and_all_pages_required(self):
        c=self.s.prepare_read(self.rules,page_chars=200)
        with self.assertRaisesRegex(ValueError,'not_fully_read'):self.s.begin('processing','x',c['receipt'])
        parts=[]
        for n in range(1,c['pages']+1):parts.append(self.s.page(c['receipt'],n));self.s.mark_shown(c['receipt'],n)
        self.assertIn(self.rules.read_text(encoding='utf-8'),''.join(parts))
        self.s.begin('processing','x',c['receipt'])

    def test_rule_change_invalidates_receipt(self):
        run=self.start();self.rules.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'rules_changed'):self.s.record(run,self.event(),self.rules)

    def test_receipt_cannot_be_reused_for_another_run(self):
        c=self.s.prepare_read(self.rules)
        for n in range(1,c['pages']+1):self.s.mark_shown(c['receipt'],n)
        run=self.s.begin('processing','first',c['receipt']);self.s.finish(run,'completed')
        with self.assertRaisesRegex(ValueError,'already_used'):self.s.begin('processing','second',c['receipt'])

    def test_read_receipt_does_not_ignore_new_decision(self):
        c=self.s.prepare_read(self.rules)
        for n in range(1,c['pages']+1):self.s.mark_shown(c['receipt'],n)
        self.s.decision({'note':'N','scope':'单据'},'保留旧版',[{'text':'用户原话'}])
        with self.assertRaisesRegex(ValueError,'context_missing_or_changed'):self.s.begin('processing','x',c['receipt'])

    def test_new_normal_batch_keeps_old_issue(self):
        run=self.start();self.s.record(run,self.event(),self.rules);self.s.finish(run,'completed')
        run=self.start();v=self.event('other','ok');v['object']['key']='other';v['object']['note']='OTHER'
        self.s.record(run,v,self.rules);self.assertEqual(len(self.s.open_issues()),1)

    def test_save_only_cannot_resolve(self):
        run=self.start();self.s.record(run,self.event(),self.rules)
        v=self.event('done','resolved');v['evidence'][0]['kind']='save_command'
        with self.assertRaisesRegex(ValueError,'concrete_verification'):self.s.record(run,v,self.rules)
        self.assertEqual(len(self.s.open_issues()),1)

    def test_unknown_not_ok(self):
        run=self.start();v=self.event(status='ok');v.pop('verified')
        with self.assertRaisesRegex(ValueError,'verification_required'):self.s.record(run,v,self.rules)

    def test_photo_proof_not_distribution_completion(self):
        run=self.start();v=self.event(status='ok',stage='distribution');v['evidence'][0]['kind']='photo_visual'
        with self.assertRaisesRegex(ValueError,'this_stage'):self.s.record(run,v,self.rules)

    def test_close_one_issue_not_entire_note(self):
        run=self.start();self.s.record(run,self.event(),self.rules);self.s.record(run,self.event('date',check='日期'),self.rules)
        self.s.record(run,self.event('withdrawn','false_positive'),self.rules)
        self.assertEqual([r['check_name'] for r in self.s.open_issues()],['日期'])
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM events WHERE status='false_positive'").fetchone()[0],1)

    def test_different_stage_cannot_close_quantity_issue(self):
        run=self.start();self.s.record(run,self.event(),self.rules)
        v=self.event('close','resolved',stage='photo');v['evidence'][0]['kind']='photo_visual'
        with self.assertRaisesRegex(ValueError,'stage_mismatch'):self.s.record(run,v,self.rules)

    def test_verified_alias_scope_and_leading_zeros(self):
        from rules_data import note_candidates
        fixture={'note_aliases':[
            {'project':'示例项目A','canonical':'TEST-WH-00001','aliases':['TSET-WH-00001']},
            {'project':'示例项目B','canonical':'0000101/0000202','aliases':['0000101','0000202']}]}
        self.assertIn('TEST-WH-00001',note_candidates('TSET-WH-00001','示例项目A',fixture))
        self.assertEqual(note_candidates('TSET-WH-00001','另一项目',fixture),{'TSET-WH-00001'})
        self.assertEqual(note_candidates('TSET-WH-001','示例项目A',fixture),{'TSET-WH-001'})
        self.assertIn('0000101/0000202',note_candidates('0000101','示例项目B',fixture))

    def test_plan_annotation_retained_and_year_not_guessed(self):
        from rules_data import date_parts
        self.assertEqual(date_parts('2026/9/28十点前'),{'raw':'2026/9/28十点前','date':'2026-09-28','annotation':'十点前'})
        self.assertEqual(date_parts('9月28日十点前',2026)['annotation'],'十点前')
        with self.assertRaisesRegex(ValueError,'year_needs_review'):date_parts('9月28日十点前')

    def test_reopen_preserves_history_and_idempotent_retry(self):
        run=self.start();self.s.record(run,self.event(),self.rules)
        self.s.record(run,self.event('resolved','resolved'),self.rules)
        v=self.event('reopened');seq=self.s.record(run,v,self.rules)
        self.assertEqual(self.s.record(run,v,self.rules),seq)
        row=self.s.open_issues()[0];self.assertEqual(json.loads(row['data'])['transition'],'reopened')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],3)

    def test_ok_cannot_hide_existing_issue(self):
        run=self.start();self.s.record(run,self.event(),self.rules)
        with self.assertRaisesRegex(ValueError,'explicit_resolution'):self.s.record(run,self.event('ok','ok'),self.rules)

    def test_not_applicable_cannot_hide_existing_issue(self):
        run=self.start();self.s.record(run,self.event(),self.rules)
        with self.assertRaisesRegex(ValueError,'explicit_resolution'):self.s.record(run,self.event('na','not_applicable'),self.rules)

    def test_actual_problem_cannot_disable_tracking(self):
        run=self.start();v=self.event();v['track_issue']=False
        with self.assertRaisesRegex(ValueError,'must_remain_tracked'):self.s.record(run,v,self.rules)

    def test_user_modified_stays_open(self):
        run=self.start();v=self.event(status='modified_unverified');v['verified']=False;v['evidence']=[{'text':'用户说已改'}]
        self.s.record(run,v,self.rules);self.assertEqual(self.s.open_issues()[0]['status'],'modified_unverified')

    def test_no_receipt_weight_not_applicable(self):
        run=self.start();v=self.event(status='not_applicable',stage='weighing');v['result']='未计算：原单未注明实收';v['verified']=False
        self.s.record(run,v,self.rules);self.assertEqual(len(self.s.open_issues()),0)

    def test_history_unknown_time_is_not_latest_actual(self):
        run=self.start();self.s.record(run,self.event(),self.rules);self.s.finish(run,'interrupted')
        historical=self.s.begin('history_import','old');v=self.event('old');v.update(origin='historical_import',checked_at=None)
        self.s.record(historical,v);self.s.finish(historical,'completed')
        c=self.s.context();self.assertEqual(c['latest_processing']['id'],run)
        self.assertEqual(self.s.open_issues()[0]['latest_seq'],1)
        self.assertIsNone(self.s.db.execute("SELECT checked_at FROM events WHERE event_key='old'").fetchone()[0])

    def test_batch_completion_is_not_a_note_check_time(self):
        from import_delivery_history import Importer
        workspace=self.root/'workspace';batch=workspace/'outputs/delivery-batch-20260101-120000';batch.mkdir(parents=True)
        (batch/'progress.json').write_text(json.dumps([{'note':'N','status':'cleaned','ledger_rows':[1],'overview_rows':[2]}]),encoding='utf-8')
        (batch/'completion.json').write_text(json.dumps({'resolution_completed_at':'2026-10-12T14:00:00+08:00'}),encoding='utf-8')
        importer=Importer(self.s,workspace);importer.batches()
        rows=self.s.db.execute('SELECT checked_at,data FROM events').fetchall()
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(row['checked_at'])
            self.assertEqual(json.loads(row['data'])['batch_completion_time'],'2026-10-12T14:00:00+08:00')

    def test_failed_export_does_not_rollback_state(self):
        run=self.start();self.s.record(run,self.event(),self.rules)
        with patch('delivery_state.atomic_text',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.s.export()
        self.assertEqual(len(self.s.open_issues()),1)
        self.s.export();self.assertIn('数量',(self.s.root/'未解决问题清单.md').read_text(encoding='utf-8'))

    def test_transaction_failure_has_no_partial_issue(self):
        run=self.start();v=self.event();v['check']=None
        with self.assertRaises(Exception):self.s.record(run,v,self.rules)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM issues').fetchone()[0],0)

    def test_shared_state_change_requires_reread(self):
        a=self.start();b=self.start();self.s.record(a,self.event(),self.rules)
        with self.assertRaisesRegex(ValueError,'shared_state_changed'):self.s.record(b,self.event('other'),self.rules)

    def test_concurrent_history_writes_keep_every_event(self):
        def work(i):
            s=State(self.s.root)
            try:
                run=s.begin('history_import','history');v=self.event('event-'+str(i));v.update(origin='historical_import',checked_at=None)
                s.record(run,v);s.finish(run,'completed')
            finally:s.close()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(work,range(12)))
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],12)
        self.assertEqual(len(self.s.open_issues()),1)

    def test_timezone_normalization_and_unknown(self):
        run=self.start();v=self.event();v['checked_at']='2026-01-01T02:00:00+00:00';self.s.record(run,v,self.rules)
        self.assertEqual(self.s.open_issues()[0]['checked_at'],'2026-01-01T10:00:00+08:00')
        v=self.event('bad');v['checked_at']='2026-01-01T10:00:00'
        with self.assertRaisesRegex(ValueError,'timezone'):self.s.record(run,v,self.rules)

    def test_history_does_not_reopen_known_resolved_result(self):
        run=self.start();self.s.record(run,self.event(),self.rules);self.s.record(run,self.event('resolved','resolved'),self.rules)
        h=self.s.begin('history_import','old');v=self.event('old');v.update(origin='historical_import',checked_at=None)
        self.s.record(h,v);self.assertEqual(len(self.s.open_issues()),0)

    def test_cleanup_requires_complete_import_and_scoped_open_issues(self):
        with self.assertRaisesRegex(ValueError,'history_import_not_complete'):cleanup_blockers(self.s.root,'batch',['P-N-0001'])
        self.s.db.execute("INSERT INTO meta VALUES('history_import_complete','true')");self.s.db.commit()
        run=self.start();self.s.record(run,self.event(),self.rules)
        self.assertEqual(len(cleanup_blockers(self.s.root,'batch',['P-N-0001'])),1)
        self.assertEqual(cleanup_blockers(self.s.root,'batch',['OTHER']),[])

    def test_rule_mappings_generated_without_drift(self):
        from rules_data import check_path
        for name,value in outputs().items():self.assertEqual(check_path(name).read_text(encoding='utf-8-sig'),value)

    def history_bundle(self):
        source=self.root/'old-report.json';source.write_text('{"history":"synthetic"}',encoding='utf-8')
        value=self.event('historical-event');value['checked_at']='2026-01-01T10:00:00'
        path=self.root/'history.json'
        path.write_text(json.dumps({'history_scope_reviewed':True,'records':[
            {'source':str(source),'sha256':digest(source),'locator':'row1','record':value}],
            'decisions':[{'source':str(source),'sha256':digest(source),'locator':'decision1',
                          'object':{'note':'P-N-0001','scope':'照片版本'},'instruction':'保留旧版'}]}),encoding='utf-8')
        return path,source

    def test_portable_history_import_unknown_time_and_retry(self):
        from import_delivery_history import Importer
        path,_=self.history_bundle()
        for _ in range(2):Importer(self.s,self.root/'empty-workspace').execute(path)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],1)
        row=self.s.db.execute('SELECT checked_at,data FROM events').fetchone()
        self.assertIsNone(row['checked_at'])
        self.assertEqual(json.loads(row['data'])['historical_time_raw'],'2026-01-01T10:00:00')
        self.assertIsNone(self.s.context()['latest_processing'])
        self.assertEqual(len(cleanup_blockers(self.s.root,'batch',['P-N-0001'])),1)

    def test_portable_import_changed_source_blocks_cleanup(self):
        from import_delivery_history import Importer
        path,source=self.history_bundle();source.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source_missing_or_changed'):
            Importer(self.s,self.root/'empty').execute(path)
        with self.assertRaisesRegex(ValueError,'history_import_not_complete'):
            cleanup_blockers(self.s.root,'batch',[])

    def test_batch_scan_alone_cannot_mark_history_complete(self):
        from import_delivery_history import Importer
        result=Importer(self.s,self.root/'empty').execute()
        self.assertFalse(result['history_scope_reviewed'])
        with self.assertRaisesRegex(ValueError,'history_import_not_complete'):
            cleanup_blockers(self.s.root,'batch',[])

    def test_default_state_root_uses_local_config(self):
        from delivery_state import default_root
        skill=self.root/'skill';(skill/'assets').mkdir(parents=True)
        config=skill/'assets/settings.json'
        with patch('delivery_state.SKILL',skill):
            self.assertEqual(default_root(),Path.home()/'.delivery-processing-state')
            config.write_text(json.dumps({'state_root':str(self.root/'independent-state')}),encoding='utf-8')
            self.assertEqual(default_root(),self.root/'independent-state')
            config.write_text('{"state_root":"relative-path"}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'absolute_path'):default_root()

    def test_fresh_checkout_uses_generated_project_example(self):
        from rules_data import check_path
        ref=self.root/'references';ref.mkdir()
        example=ref/'project-map.example.csv';example.write_text('example',encoding='utf-8')
        self.assertEqual(check_path('project-map.csv',self.root),example)
        local=ref/'project-map.csv';local.write_text('local',encoding='utf-8')
        self.assertEqual(check_path('project-map.csv',self.root),local)


class CleanupStateTests(unittest.TestCase):
    def test_eligible_backup_blocked_by_durable_issue(self):
        from test_backup_cleanup import CleanupTests
        import backup_cleanup
        fixture=CleanupTests('test_complete_and_read_only');fixture.setUp();self.addCleanup(fixture.tearDown)
        s=State(fixture.root/'state',create=True);self.addCleanup(s.close)
        s.db.execute("INSERT INTO meta VALUES('history_import_complete','true')");s.db.commit()
        fixture.settings['state_root']=str(s.root)
        self.assertEqual(fixture.plan()['summary']['eligible_files'],3)
        run=s.begin('history_import','historical')
        s.record(run,dict(event_key='open',object={'key':'P-XY-00001','note':'P-XY-00001','scope':'Q20'},check='配送数量',stage='quantity',status='problem',
                          checked_at=None,result='待核',action='历史导入',next='复核',evidence=[{'path':'historical'}],origin='historical_import'))
        fixture.blocked('unresolved_related_issues')
        self.assertTrue(s.path.exists());self.assertTrue(all(Path(x['backup']).exists() for x in fixture.manifest))


if __name__=='__main__':unittest.main()
