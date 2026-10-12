import csv
import importlib.util
import json
import tempfile
import unittest
import subprocess
import shutil
from pathlib import Path
from delivery_paths import pending_files, history_rows
import distribution_checks as dc
from test_distribution_workflow import row, incoming


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+'.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class DiscoveryTests(unittest.TestCase):
    def test_real_layout_inventory_and_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); pending=root/'pending'
            for p in (pending/'自提'/'nested',pending/'厂发',root/'ledgers',root/'primary',root/'settlement'):
                p.mkdir(parents=True)
            (pending/'loose.jpg').write_bytes(b'legacy')
            image=pending/'自提'/'nested'/'new.jpg';image.write_bytes(b'new')
            (pending/'厂发'/'factory.jpg').write_bytes(b'factory')
            settings={k:str(v) for k,v in dict(pending_root=pending,factory_pending_root=pending/'厂发',ledger_root=root/'ledgers',primary_archive_root=root/'primary',settlement_archive_root=root/'settlement').items()}
            import hashlib
            digest=hashlib.sha256(image.read_bytes()).hexdigest()
            batch=root/'outputs'/'delivery-batch-20261012-135814';batch.mkdir(parents=True)
            with (batch/'xy-result.csv').open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['delivery_no','source_file','source_sha256']);w.writeheader();w.writerow(dict(delivery_no='P-XY-00001',source_file=str(image),source_sha256=digest))
            result=module('inventory-pending').inventory(settings,root)
            self.assertEqual((result['total_files'],result['historical_hash_candidates']),(2,1))
            reconciled=module('reconcile-pending-delivery-notes').reconcile(settings,[],root)
            self.assertEqual(reconciled['pending_count'],2)
            self.assertEqual(next(r for r in reconciled['items'] if r['source_file']==str(image))['candidate_numbers'],['P-XY-00001'])
            self.assertEqual(len(pending_files(settings,'factory')),1)
            settings_file=root/'settings.json';settings_file.write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
            helper=Path(__file__).with_name('pending-images.ps1')
            quote=lambda p: "'"+str(p).replace("'","''")+"'"
            command='. '+quote(helper)+'; $s = Get-Content -LiteralPath '+quote(settings_file)+' -Raw -Encoding UTF8 | ConvertFrom-Json; @(Get-SelfPickupImages $s).Count'
            run=subprocess.run([shutil.which('pwsh') or shutil.which('powershell'),'-NoProfile','-Command',command],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(run.stdout.strip(),'2')

    def test_history_legacy_direct_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for folder in (root,root/'batch-old',root/'delivery-batch-20261012-120000',root/'outputs'/'delivery-batch-20261012-130000'):
                folder.mkdir(parents=True,exist_ok=True)
                (folder/'factory-result.json').write_text(json.dumps({'results':[{'delivery_no':'00001','sha256':'a'*64}]}))
            self.assertEqual(len(list(history_rows(root))),4)

    def test_note_arrival_across_materials(self):
        result=dc.plan(dict(stocks=[row(stock_id='A-1'),row(stock_id='A-2',spec='22')],existing=[],legacy=[],incoming=[incoming(),incoming(line_id='source/2',spec='22',arrival_date='2026-05-27')]))
        self.assertEqual(result['counts'],{'blocked':2})
        self.assertTrue(all(r['reason']=='inconsistent_arrival_within_note' for r in result['results']))
        self.assertTrue(all(r['status']=='none' for r in result['stock_status_candidates']))

    def test_same_note_independent_plan_dates_allowed(self):
        result=dc.plan(dict(stocks=[row(stock_id='A-1'),row(stock_id='A-2',spec='22',plan_date='2026-05-24')],existing=[],legacy=[],incoming=[incoming(),incoming(line_id='source/2',spec='22',plan_date='2026-05-24')]))
        self.assertEqual(result['counts'],{'ready':2})

    def test_existing_other_material_arrival_conflict(self):
        result=dc.plan(dict(stocks=[row(stock_id='A-1'),row(stock_id='A-2',spec='22')],existing=[incoming(stock_id='A-1')],legacy=[],incoming=[incoming(line_id='source/2',spec='22',arrival_date='2026-05-27')]))
        self.assertEqual(result['counts'],{'blocked':1})


if __name__=='__main__':unittest.main()
