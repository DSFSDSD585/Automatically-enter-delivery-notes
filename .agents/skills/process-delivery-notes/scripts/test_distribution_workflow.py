"""Regression tests use temporary data only; no production workbook mutations."""
import copy
import json
import tempfile
import unittest
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
import distribution_checks as dc
import archive_factory_notes as af


def row(**changes):
    value=dict(project='项目甲',seller='销售甲',plan_date='2026-05-25',material='螺纹钢',brand='杭钢',model='HRB400E',spec='20',length='9',mode='factory',tons='20',pieces=10)
    value.update(changes);return value


def incoming(**changes):
    return row(**(dict(line_id='source/1',note_no='P-YX-0525-001',arrival_date='2026-05-26')|changes))


class PlanningTests(unittest.TestCase):
    def plan(self, inc=None, stocks=None, existing=None, **extra):
        return dc.plan(dict(incoming=inc or [incoming()],stocks=stocks or [row(stock_id='A-9')],existing=existing or [],legacy=[],**extra))

    def test_new_and_repeat(self):
        first=self.plan();self.assertEqual(first['results'][0]['status'],'ready')
        second=self.plan(existing=[incoming(stock_id='A-9')]);self.assertEqual(second['results'][0]['status'],'already_synced')

    def test_split_existing_sum_not_duplicate(self):
        old=[incoming(stock_id='A-9',tons='8',pieces=4),incoming(stock_id='A-10',tons='12',pieces=6)]
        stocks=[row(stock_id='A-9',tons='8',pieces=4),row(stock_id='A-10',tons='12',pieces=6)]
        self.assertEqual(self.plan(stocks=stocks,existing=old)['results'][0]['status'],'already_synced')

    def test_numeric_fifo_and_exact_total(self):
        stocks=[row(stock_id='A-10',tons='12',pieces=6),row(stock_id='A-9',tons='8',pieces=4)]
        parts=self.plan(stocks=stocks)['results'][0]['allocations']
        self.assertEqual([p['stock_id'] for p in parts],['A-9','A-10'])
        self.assertEqual(sum(Decimal(p['tons']) for p in parts),Decimal('20'))

    def test_batch_capacity_reserved_together(self):
        a=incoming(tons='12',pieces=6,distinct_note_reviewed=True)
        b={**a,'line_id':'source/2','note_no':'P-YX-0525-002'}
        self.assertTrue(all(r['reason']=='batch_exceeds_remaining_pieces' for r in self.plan([a,b])['results']))

    def test_two_notes_share_lot_safely(self):
        a=incoming(tons='8',pieces=4);b={**a,'line_id':'source/2','note_no':'P-YX-0525-002','tons':'12','pieces':6}
        p=self.plan([a,b]);self.assertEqual(p['counts'],{'ready':2});self.assertEqual(p['stock_status_candidates'][0]['status'],'complete')

    def test_same_group_total_not_one_to_one_weights(self):
        stocks=[row(stock_id='A-9',tons='8',pieces=4),row(stock_id='A-10',tons='12',pieces=6)]
        a=incoming(tons='9',pieces=4);b={**a,'line_id':'source/2','note_no':'P-YX-0525-002','tons':'11','pieces':6}
        self.assertEqual(self.plan([a,b],stocks)['counts'],{'ready':2})

    def test_plan_date_must_match(self):
        self.assertEqual(self.plan([incoming(plan_date='2026-05-24')])['results'][0]['reason'],'no_exact_inbound_match')

    def test_project_seller_brand_mode_separated(self):
        for field,new in [('project','项目乙'),('seller','销售乙'),('brand','其他'),('mode','self_pickup')]:
            with self.subTest(field=field):self.assertEqual(self.plan([incoming(**{field:new})])['results'][0]['reason'],'no_exact_inbound_match')

    def test_missing_arrival_is_blocked(self):
        self.assertEqual(self.plan([incoming(arrival_date=None)])['results'][0]['status'],'blocked')

    def test_existing_arrival_difference_no_insert(self):
        self.assertIn('do_not_append',self.plan(existing=[incoming(stock_id='A-9',arrival_date='2026-05-27')])['results'][0]['reason'])

    def test_partial_existing_not_whole_row_append(self):
        self.assertIn('do_not_append',self.plan(existing=[incoming(stock_id='A-9',tons='8',pieces=4)])['results'][0]['reason'])

    def test_other_number_needs_identity_review(self):
        old=incoming(stock_id='A-9');old['note_no']='OTHER-001'
        p=self.plan(existing=[old]);self.assertEqual(p['results'][0]['reason'],'possible_duplicate_other_number')

    def test_legacy_blocks_duplicate(self):
        data=dict(stocks=[row(stock_id='A-9')],incoming=[incoming()],existing=[],legacy=[incoming()])
        self.assertEqual(dc.plan(data)['results'][0]['status'],'legacy_record_exists')

    def test_same_number_changed_identity(self):
        old=incoming(stock_id='A-9')
        self.assertEqual(self.plan([incoming(plan_date='2026-05-24')],existing=[old])['results'][0]['reason'],'same_number_identity_or_plan_difference')

    def test_source_line_duplicate_rejected(self):
        with self.assertRaises(ValueError):self.plan([incoming(),incoming()])

    def test_leading_zero_retained(self):
        x=incoming();x['note_no']='0000123';self.assertEqual(self.plan([x])['results'][0]['note_no'],'0000123')

    def test_rebar_weight_requires_purchase(self):
        self.assertEqual(self.plan([incoming(tons='21')])['results'][0]['reason'],'purchase_weight_review_required')

    def test_estimate_review_is_specific(self):
        st=row(stock_id='A-9',material='盘螺');inc=incoming(material='盘螺',tons='19.8')
        self.assertEqual(self.plan([inc],[st])['results'][0]['reason'],'estimate_review_required')
        review=row(material='盘螺',delivered_tons='19.8',delivered_pieces=10,purchase_tons='20',purchase_pieces=10,reason='件数相同，暂估与实发相差0.2吨，经核对可接受')
        self.assertEqual(self.plan([inc],[st],estimate_reviews=[review])['results'][0]['status'],'ready')
        inc['tons']='10';self.assertEqual(self.plan([inc],[st],estimate_reviews=[review])['results'][0]['status'],'blocked')

    def test_loss_boundary_and_missing(self):
        self.assertEqual(dc.loss_check('盘螺','100','99.7')['status'],'within_limit')
        self.assertEqual(dc.loss_check('高线','100','99.699')['status'],'over_limit')
        self.assertEqual(dc.loss_check('线材','100',None)['status'],'skipped_no_received_weight')
        self.assertEqual(dc.loss_check('盘螺','100','101')['status'],'within_limit')
        self.assertEqual(dc.loss_check('盘螺','0','1')['status'],'invalid_weight')
        self.assertEqual(dc.loss_check('螺纹钢','100','1')['status'],'not_applicable')

    def test_loss_anomaly_does_not_replace_weight(self):
        p=self.plan([incoming(material='盘螺',received_tons='19')],[row(stock_id='A-9',material='盘螺')])
        self.assertEqual(p['results'][0]['loss_checks'][0]['status'],'over_limit')
        self.assertEqual(Decimal(p['results'][0]['allocations'][0]['tons']),Decimal('20'))

    def test_input_not_mutated(self):
        d=dict(stocks=[row(stock_id='A-9')],incoming=[incoming()],existing=[],legacy=[]);before=copy.deepcopy(d)
        dc.plan(d);self.assertEqual(d,before)

    def test_invalid_line_blocks_same_note(self):
        bad=incoming(line_id='source/2',arrival_date=None,spec='22')
        p=self.plan([incoming(),bad]);self.assertNotIn('ready',p['counts'])

    def test_existing_and_incoming_same_other_note_not_double_counted(self):
        old=incoming(stock_id='A-9',note_no='OLD-001')
        second=incoming(line_id='source/2',note_no='OLD-001')
        p=self.plan([incoming(),second],existing=[old])
        self.assertEqual(p['results'][0]['reason'],'possible_duplicate_other_number')

    def test_invalid_received_is_reported(self):
        self.assertEqual(dc.loss_check('盘螺','20','NaN')['status'],'invalid_weight')

    def test_same_day_same_quantity_new_physical_notes_can_be_reviewed(self):
        a=incoming(tons='10',pieces=5,distinct_note_reviewed=True)
        b=incoming(line_id='source/2',note_no='OTHER',tons='10',pieces=5,distinct_note_reviewed=True)
        self.assertEqual(self.plan([a,b])['counts'],{'ready':2})

    def test_identical_source_rows_are_not_summed_blindly(self):
        a=incoming(tons='10',pieces=5);b=incoming(line_id='source/2',tons='10',pieces=5)
        self.assertEqual(self.plan([a,b])['results'][0]['reason'],'possible_duplicate_source_details')

    def test_one_kilogram_difference_is_not_already_synced(self):
        p=self.plan([incoming(tons='20.001')],existing=[incoming(stock_id='A-9')])
        self.assertEqual(p['results'][0]['status'],'blocked')


def fixture_book(path, overview, stock):
    def sheet(rows):
        parts=[]
        for rn,values in rows.items():
            cs=[]
            for col,val in values.items():
                if isinstance(val,(int,float)):cs.append(f'<c r="{col}{rn}"><v>{val}</v></c>')
                else:cs.append(f'<c r="{col}{rn}" t="inlineStr"><is><t>{escape(str(val))}</t></is></c>')
            parts.append(f'<row r="{rn}">'+''.join(cs)+'</row>')
        return '<worksheet xmlns="'+af.NS['m']+'"><sheetData>'+''.join(parts)+'</sheetData></worksheet>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="'+af.NS['m']+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="总览表" sheetId="8" r:id="r9"/><sheet name="入库信息表" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r9" Target="worksheets/overview.xml"/><Relationship Id="r2" Target="/xl/worksheets/inbound.xml"/></Relationships>')
        z.writestr('xl/worksheets/overview.xml',sheet(overview));z.writestr('xl/worksheets/inbound.xml',sheet(stock))


class FactoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='delivery-skill-test-');self.root=Path(self.temp.name)
        self.settings={k:str(self.root/k) for k in ('pending_root','ledger_root','primary_archive_root','settlement_archive_root','factory_pending_root')}
        for path in self.settings.values():Path(path).mkdir()
        self.ledger=self.root/'distribution.xlsx';self.settings['distribution_ledger']=str(self.ledger)
        (Path(self.settings['settlement_archive_root'])/'项目甲').mkdir()
        self.source=Path(self.settings['factory_pending_root'])/'note.jpg';self.source.write_bytes(b'\xff\xd8\xfftest original bytes')
        self.backup=self.root/'image-backup.jpg';self.backup.write_bytes(self.source.read_bytes())
        day=(date(2026,5,26)-date(1899,12,30)).days
        self.ov={7:dict(A='A-9',C=day-1,D='螺纹钢',E='杭钢',F='HRB400E',G=20,H=9,J='销售甲',K='项目甲',Q=20,R=10,S=day,T='P-YX-0525-001')}
        self.st={11:dict(A='A-9',C=day-1,D='销售甲',E='螺纹钢',F='杭钢',G='HRB400E',H=20,I=9,M='项目甲',N='厂发')}
        fixture_book(self.ledger,self.ov,self.st)
        self.item=dict(source_file=str(self.source),source_sha256=af.digest(self.source),backup_file=str(self.backup),backup_sha256=af.digest(self.backup),delivery_no='P-YX-0525-001',project='项目甲',archive_project='项目甲',arrival_date='2026-05-26',ledger_file=str(self.ledger),ledger_sha256=af.digest(self.ledger),ledger_sheet='总览表',expected_rows=[dict(row=7,cells=copy.deepcopy(self.ov[7]))])
        self.n=0

    def tearDown(self):self.temp.cleanup()
    def run_item(self,execute=False):
        self.n+=1
        return af.run({'items':[self.item]},self.settings,self.root/f'result{self.n}.json',execute)[0]

    def test_dry_run_no_mutation(self):
        before=af.digest(self.ledger);out=self.run_item()
        self.assertEqual(out['status'],'ready');self.assertTrue(self.source.exists());self.assertFalse(Path(out['target']).exists());self.assertEqual(before,af.digest(self.ledger))

    def test_execute_and_retry_idempotent(self):
        first=self.run_item(True);self.assertEqual(first['status'],'completed');self.assertFalse(self.source.exists())
        self.assertEqual(af.digest(first['target']),self.item['source_sha256']);self.assertIn('2026',Path(first['target']).parts)
        second=self.run_item(True);self.assertEqual(second['status'],'already_complete');self.assertFalse(second['source_removed'])

    def test_changed_ledger_blocks_before_copy(self):
        self.ledger.write_bytes(self.ledger.read_bytes()+b'changed')
        self.assertEqual(self.run_item(True)['status'],'blocked');self.assertTrue(self.source.exists())

    def test_stale_expected_cell_blocks(self):
        self.item['expected_rows'][0]['cells']['Q']=22
        self.assertEqual(self.run_item(True)['status'],'blocked');self.assertTrue(self.source.exists())

    def test_plan_date_mismatch_blocks(self):
        self.st[11]['C']-=1;fixture_book(self.ledger,self.ov,self.st);self.item['ledger_sha256']=af.digest(self.ledger)
        self.assertEqual(self.run_item()['status'],'blocked')

    def test_backup_missing_blocks(self):
        self.backup.unlink();self.assertEqual(self.run_item(True)['status'],'blocked');self.assertTrue(self.source.exists())

    def test_conflicting_archive_never_overwritten(self):
        target=Path(self.run_item()['target']);target.parent.mkdir();target.write_bytes(b'other')
        self.assertEqual(self.run_item(True)['status'],'blocked');self.assertEqual(target.read_bytes(),b'other');self.assertTrue(self.source.exists())

    def test_incomplete_detail_set_blocks(self):
        self.ov[8]=self.ov[7].copy();fixture_book(self.ledger,self.ov,self.st);self.item['ledger_sha256']=af.digest(self.ledger)
        self.assertEqual(self.run_item()['status'],'blocked')

    def test_missing_project_not_created(self):
        self.item['archive_project']='不存在';self.assertEqual(self.run_item(True)['status'],'blocked')
        self.assertFalse((Path(self.settings['settlement_archive_root'])/'不存在').exists())

    def test_path_escape_blocked(self):
        self.item['archive_project']='../escape';self.assertEqual(self.run_item(True)['status'],'blocked')

    def test_different_year_uses_arrival_year(self):
        self.item['arrival_date']='2027-05-26';self.ov[7]['S']=(date(2027,5,26)-date(1899,12,30)).days
        fixture_book(self.ledger,self.ov,self.st);self.item['ledger_sha256']=af.digest(self.ledger);self.item['expected_rows'][0]['cells']=self.ov[7].copy()
        self.assertIn('2027',Path(self.run_item()['target']).parts)


if __name__=='__main__':unittest.main(verbosity=2)
