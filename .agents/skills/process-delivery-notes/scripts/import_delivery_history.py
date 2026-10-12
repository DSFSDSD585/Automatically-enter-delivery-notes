"""Import existing delivery evidence without touching business files or asserting a new audit."""
import argparse
import csv
import json
from pathlib import Path
from delivery_state import State, DEFAULT_ROOT, digest, dump, time_value, now


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


class Importer:
    def __init__(self, state, workspace):
        self.s = state
        self.root = Path(workspace)
        self.run = state.begin('history_import', '导入本地历史批次及规范化记录；不重新核查业务文件')
        self.sources = {}
        self.count = 0

    def evidence(self, path, locator, observation):
        path = Path(path)
        if str(path) not in self.sources:
            self.sources[str(path)] = digest(path)
        sha = self.sources[str(path)]
        return [{'path':str(path),'sha256':sha,'locator':str(locator),'observation':observation,'kind':'historical_report'}]

    def add(self, path, locator, note, check, stage, status, result, scope, project='',
            key=None, actual_time=None, track=True, action='读取历史记录并整理；本次未修改业务文件', extra=None):
        at = None
        if actual_time:
            try: at = time_value(actual_time)
            except ValueError: pass
        ev = self.evidence(path,locator,result)
        value = {'event_key':ev[0]['sha256']+':'+str(locator)+':'+status,
                 'object':{'key':key or note,'note':note,'project':project,'scope':scope},
                 'check':check,'stage':stage,'status':status,'checked_at':at,
                 'result':result,'action':action,
                 'next':'按对应原单及当前实际文件复核后更新；不能把导入当本次核查' if status in ('problem','not_checked','modified_unverified') else '保留历史结论；本次对象再次处理时对照当前文件',
                 'evidence':ev,'origin':'historical_import','track_issue':track,
                 'historical_time_raw':actual_time,'historical_time_note':'原始时间不带时区或未提供时，不补造核对时间'}
        if extra: value.update(extra)
        self.s.record(self.run,value)
        self.count += 1

    def batches(self):
        for base in [self.root,self.root/'outputs']:
            if not base.is_dir(): continue
            for batch in sorted(base.iterdir()):
                if not batch.is_dir() or not batch.name.startswith(('batch-','delivery-batch-')):continue
                p=batch/'progress.json'
                if p.is_file():
                    rows=read(p)
                    if not isinstance(rows,list):continue
                    completion=read(batch/'completion.json') if (batch/'completion.json').exists() else {}
                    for i,row in enumerate(rows):
                        note=row.get('note',row.get('delivery_no',''))
                        if not note:continue
                        for stage,field in [('transport','ledger_rows'),('distribution','overview_rows'),('archive_primary','primary_target'),('archive_settlement','settlement_target')]:
                            if not row.get(field):continue
                            status='ok' if row.get('status') in ('cleaned','cleaned_duplicate_keep_existing') else 'not_checked'
                            self.add(p,str(i)+'/'+stage,note,'批次'+stage,stage,status,
                                     '历史逐单阶段记录：'+str(row.get(field))+'；原批次状态：'+str(row.get('status')),
                                     '批次'+batch.name,track=False,
                                     extra={'original_record':row,'related_batches':[str(batch)],
                                            'batch_completion_time':completion.get('resolution_completed_at')})
                    for row in completion.get('pending_notes',[]):
                        note=row.get('note') if isinstance(row,dict) else str(row)
                        self.add(batch/'completion.json','pending/'+note,note,'批次遗留问题','distribution','problem',dump(row),batch.name,
                                 extra={'related_batches':[str(batch)]})
                # Older self-pickup CSV means transport and archive, not distribution completion.
                p=batch/'final-source-results.csv'
                if p.is_file():
                    for i,row in enumerate(csv.DictReader(p.open(encoding='utf-8-sig',newline=''))):
                        note=row.get('delivery_no')
                        if not note:continue
                        self.add(p,'row/'+str(i),note,'旧自提批次阶段','transport','not_checked',
                                 '历史CSV状态：'+dump(row)+'；不得推定配送已录',batch.name,track=False,extra={'related_batches':[str(batch)]})

    def bundle(self, path):
        """Read local, explicitly scoped observations; no embedded customer cases."""
        path = Path(path).resolve()
        data = read(path)
        self.evidence(path, 'bundle', '本地规范化历史记录；不是本次业务复核')
        prepared = []
        for kind, entries in [('record', data.get('records', [])), ('decision', data.get('decisions', []))]:
            for entry in entries:
                source = Path(entry['source'])
                if not source.is_absolute():
                    source = path.parent / source
                source = source.resolve()
                if not source.is_file() or digest(source) != entry['sha256']:
                    raise ValueError('historical_source_missing_or_changed: '+str(source))
                proof = self.evidence(source, entry['locator'], '已读取本地历史来源；保留原结论及范围')
                prepared.append((kind, entry, proof))
        for kind, entry, proof in prepared:
            if kind == 'decision':
                self.s.decision(entry['object'], entry['instruction'], proof, entry.get('decided_at'))
                continue
            value = dict(entry['record'])
            raw_time = value.get('checked_at')
            try:
                checked = time_value(raw_time) if raw_time else None
            except ValueError:
                checked = None
            value.update(origin='historical_import', checked_at=checked,
                         historical_time_raw=raw_time,
                         historical_time_note='历史未知或无时区的核对时间留空；不以导入或批次完成时间代替',
                         evidence=[*value.get('evidence', []), *proof])
            value.setdefault('event_key', proof[0]['sha256']+':'+str(entry['locator'])+':'+value['stage']+':'+value['status'])
            self.s.record(self.run, value)
            self.count += 1
        return data.get('history_scope_reviewed') is True

    def execute(self, records=None):
        try:
            with self.s.transaction():
                self.s.db.execute("INSERT OR REPLACE INTO meta VALUES('history_import_complete','false')")
            self.batches()
            complete = self.bundle(records) if records else False
            for path, sha in self.sources.items():
                if digest(path) != sha:
                    raise ValueError('historical_source_changed_during_import: '+path)
            with self.s.transaction():
                self.s.db.execute("INSERT OR REPLACE INTO meta VALUES('history_import_complete',?)",
                                  ('true' if complete else 'false',))
            self.s.finish(self.run, 'completed')
            result = self.s.export()
            result.update(run=self.run, import_attempts=self.count, sources=len(self.sources),
                          kind='historical_import', time=now(), history_scope_reviewed=complete)
            from delivery_state import atomic_text
            atomic_text(self.s.root/'历史导入清单.json', json.dumps({'summary':result, 'sources':self.sources}, ensure_ascii=False, indent=2))
            return result
        except BaseException:
            self.s.finish(self.run, 'failed')
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True)
    p.add_argument('--records', help='Local normalized historical records and scoped decisions JSON')
    p.add_argument('--state-dir', default=str(DEFAULT_ROOT))
    a = p.parse_args()
    s = State(a.state_dir, create=True)
    try:
        print(json.dumps(Importer(s, a.workspace).execute(a.records), ensure_ascii=False))
    finally:
        s.close()


if __name__ == '__main__':
    main()
