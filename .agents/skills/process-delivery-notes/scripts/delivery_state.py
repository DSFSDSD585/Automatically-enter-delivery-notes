"""Durable, scoped delivery observations. Never edits business workbooks or photos."""
import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))
SKILL = Path(__file__).resolve().parents[1]
RULES = SKILL / 'references' / '送货单业务逻辑规则.md'
def default_root():
    settings = SKILL / 'assets' / 'settings.json'
    if settings.is_file():
        config = json.loads(settings.read_text(encoding='utf-8-sig'))
        if config.get('state_root'):
            root = Path(config['state_root'])
            if not root.is_absolute():
                raise ValueError('state_root_requires_absolute_path')
            return root
    return Path.home() / '.delivery-processing-state'


DEFAULT_ROOT = default_root()
LABELS = {'ok': '没有问题', 'problem': '存在问题', 'not_checked': '尚未核对',
          'modified_unverified': '已修改待验证', 'resolved': '已解决',
          'false_positive': '撤销误报', 'not_applicable': '不适用／未计算'}
OPEN = ('problem', 'not_checked', 'modified_unverified')
STAGES = {'photo', 'transport', 'distribution', 'procurement', 'inbound', 'arrival',
          'plan_date', 'identity', 'quantity', 'specification', 'weighing',
          'archive_primary', 'archive_settlement', 'local_save', 'release',
          'cloud_sync', 'source_cleanup', 'backup_cleanup', 'history_conflict', 'rule_conflict'}
PROOFS = {'photo_visual', 'workbook_disk_read', 'procurement_read', 'archive_hash',
          'local_save_verification', 'release_check', 'cloud_sync_check',
          'source_absence_check', 'cross_check'}


def now():
    return datetime.now(BEIJING).isoformat(timespec='seconds')


def time_value(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return dt.astimezone(BEIJING).isoformat(timespec='seconds')


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class State:
    def __init__(self, root=DEFAULT_ROOT, create=False):
        self.root = Path(root)
        self.path = self.root / 'state.sqlite3'
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not create and not self.path.is_file():
            raise ValueError('state_missing_initialize_and_import_history_first')
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')
        if create:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES('schema_version','1');
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY,kind TEXT NOT NULL,started_at TEXT NOT NULL,
              ended_at TEXT,status TEXT NOT NULL,scope TEXT NOT NULL,
              rules_sha256 TEXT,read_at TEXT,context_revision INTEGER);
            CREATE TABLE IF NOT EXISTS issues(
              id TEXT PRIMARY KEY,object_key TEXT NOT NULL,check_name TEXT NOT NULL,
              object_json TEXT NOT NULL,status TEXT NOT NULL,first_seen_at TEXT,
              latest_seq INTEGER,version INTEGER NOT NULL DEFAULT 1,
              UNIQUE(object_key,check_name));
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,
              run_id TEXT NOT NULL REFERENCES runs(id),issue_id TEXT REFERENCES issues(id),
              recorded_at TEXT NOT NULL,checked_at TEXT,imported_at TEXT,
              source_kind TEXT NOT NULL,object_json TEXT NOT NULL,stage TEXT NOT NULL,
              status TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(
              id TEXT PRIMARY KEY,object_json TEXT NOT NULL,instruction TEXT NOT NULL,
              decided_at TEXT,recorded_at TEXT NOT NULL,evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(
              id TEXT PRIMARY KEY,created_at TEXT NOT NULL,rules_path TEXT NOT NULL,
              rules_sha256 TEXT NOT NULL,context_revision INTEGER NOT NULL,
              page_count INTEGER NOT NULL,notes TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipt_pages(
              receipt_id TEXT NOT NULL REFERENCES receipts(id),page INTEGER NOT NULL,
              body TEXT NOT NULL,shown_at TEXT,PRIMARY KEY(receipt_id,page));
            ''')
        try:
            version = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != '1':
                raise ValueError('unsupported_state_schema')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def revision(self):
        return self.db.execute('SELECT (SELECT COALESCE(MAX(seq),0) FROM events)+(SELECT COUNT(*) FROM decisions)').fetchone()[0]

    def begin(self, kind, scope, receipt=None):
        if kind not in ('processing', 'history_import', 'maintenance'):
            raise ValueError('invalid_run_kind')
        with self.transaction():
            r = None
            if kind == 'processing':
                r = self.db.execute('SELECT * FROM receipts WHERE id=?', (receipt,)).fetchone()
                if self.db.execute('SELECT 1 FROM meta WHERE key=?', ('receipt_consumed:'+str(receipt),)).fetchone():
                    raise ValueError('read_receipt_already_used_read_again')
                if not r or r['context_revision'] != self.revision():
                    raise ValueError('context_missing_or_changed_read_again')
                count = self.db.execute('SELECT COUNT(*) FROM receipt_pages WHERE receipt_id=? AND shown_at IS NOT NULL', (receipt,)).fetchone()[0]
                if count != r['page_count'] or digest(r['rules_path']) != r['rules_sha256']:
                    raise ValueError('rules_not_fully_read_or_changed')
            run = 'RUN-' + uuid.uuid4().hex
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)',
                            (run, kind, now(), None, 'running', dump(scope),
                             r['rules_sha256'] if r else None, now() if r else None,
                             r['context_revision'] if r else None))
            if r:
                self.db.execute('INSERT INTO meta VALUES(?,?)', ('receipt_consumed:'+receipt,run))
        return run

    def finish(self, run, status):
        if status not in ('completed', 'interrupted', 'failed'):
            raise ValueError('invalid_run_status')
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM runs WHERE id=?', (run,)).fetchone():
                raise ValueError('unknown_run')
            self.db.execute('UPDATE runs SET status=?,ended_at=? WHERE id=?', (status, now(), run))

    def require_run(self, run, rules=RULES):
        r = self.db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
        if not r or r['kind'] != 'processing' or r['status'] != 'running' or not r['read_at']:
            raise ValueError('active_processing_run_with_full_read_required')
        if digest(rules) != r['rules_sha256']:
            raise ValueError('rules_changed_read_context_and_start_new_run')
        own = self.db.execute('SELECT COUNT(*) FROM events WHERE run_id=?', (run,)).fetchone()[0]
        if self.revision() != r['context_revision'] + own:
            raise ValueError('shared_state_changed_read_context_again')
        return r

    def record(self, run, value, rules=RULES):
        v = dict(value)
        obj = v.get('object', {})
        if not obj.get('key') or not obj.get('scope') or not obj.get('note'):
            raise ValueError('object_requires_stable_key_note_and_scope')
        if v.get('stage') not in STAGES or v.get('status') not in LABELS:
            raise ValueError('invalid_stage_or_status')
        for field in ('check', 'result', 'action', 'next', 'evidence', 'event_key'):
            if field not in v:
                raise ValueError('missing_' + field)
        r = self.db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
        if not r or r['status'] != 'running':
            raise ValueError('run_not_active')
        historical = r['kind'] == 'history_import'
        if not historical and r['kind'] != 'processing':
            raise ValueError('maintenance_cannot_assert_business_observations')
        checked = time_value(v['checked_at']) if v.get('checked_at') else None
        if not historical:
            self.require_run(run, rules)
            if v['status'] in ('problem', 'modified_unverified') and v.get('track_issue') is False:
                raise ValueError('actual_problem_must_remain_tracked')
            if v['status'] != 'not_checked' and not checked:
                raise ValueError('actual_observation_requires_checked_at')
            if checked and checked > now():
                raise ValueError('future_checked_at')
            if v['status'] in ('ok', 'resolved', 'false_positive'):
                proofs = v['evidence']
                if v.get('verified') is not True or not proofs:
                    raise ValueError('verification_required')
                for proof in proofs:
                    if proof.get('kind') not in PROOFS or not proof.get('observation') or not proof.get('path'):
                        raise ValueError('concrete_verification_evidence_required')
                    p = Path(proof['path'])
                    if not p.is_file():
                        raise ValueError('verification_evidence_file_missing')
                    if proof.get('sha256') != digest(p):
                        raise ValueError('verification_evidence_changed')
                required = {'photo': {'photo_visual'}, 'cloud_sync': {'cloud_sync_check'},
                            'release': {'release_check'}, 'archive_primary': {'archive_hash'},
                            'archive_settlement': {'archive_hash'},
                            'local_save': {'local_save_verification'},
                            'distribution': {'workbook_disk_read', 'cross_check'},
                            'transport': {'workbook_disk_read', 'cross_check'}}.get(v['stage'])
                if required and not any(p['kind'] in required for p in proofs):
                    raise ValueError('evidence_does_not_verify_this_stage')
        elif not v['evidence'] or v.get('origin') != 'historical_import':
            raise ValueError('historical_import_requires_source_and_origin')
        if v['status'] == 'not_applicable' and not v['result']:
            raise ValueError('not_applicable_requires_reason')
        v['checked_at'] = checked
        with self.transaction():
            if not historical:
                self.require_run(run, rules)
            old_event = self.db.execute('SELECT seq,data FROM events WHERE event_key=?', (v['event_key'],)).fetchone()
            if old_event:
                old_data = json.loads(old_event['data']); old_data.pop('transition', None)
                if dump(old_data) != dump(v):
                    raise ValueError('event_key_reused_with_different_content')
                return old_event['seq']
            issue = self.db.execute('SELECT * FROM issues WHERE object_key=? AND check_name=?', (obj['key'], v['check'])).fetchone()
            if issue and issue['latest_seq']:
                prior_stage = self.db.execute('SELECT stage FROM events WHERE seq=?', (issue['latest_seq'],)).fetchone()[0]
                if prior_stage != v['stage']:
                    raise ValueError('issue_stage_mismatch_create_separate_check')
            needs_issue = v.get('track_issue', v['status'] in OPEN or v['status'] in ('resolved', 'false_positive'))
            if issue and v['status'] in ('ok', 'not_applicable') and issue['status'] in OPEN:
                raise ValueError('explicit_resolution_required_for_open_issue')
            if not issue and v['status'] in ('resolved', 'false_positive'):
                raise ValueError('cannot_close_nonexistent_issue')
            issue_id = issue['id'] if issue else None
            if not issue and needs_issue:
                issue_id = 'ISS-' + hashlib.sha256((obj['key']+'\0'+v['check']).encode()).hexdigest()[:16]
                self.db.execute('INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)',
                                (issue_id, obj['key'], v['check'], dump(obj), v['status'], checked, None, 1))
            seq = self.db.execute('''INSERT INTO events(event_key,run_id,issue_id,recorded_at,checked_at,
                imported_at,source_kind,object_json,stage,status,data) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (v['event_key'], run, issue_id, now(), checked, now() if historical else None,
                 'historical_import' if historical else 'actual_check', dump(obj), v['stage'], v['status'], dump(v))).lastrowid
            if issue_id:
                replace = True
                if issue and issue['latest_seq']:
                    prior = self.db.execute('SELECT * FROM events WHERE seq=?', (issue['latest_seq'],)).fetchone()
                    if historical:
                        # Unknown-time imports never overwrite real checks or known-time conclusions.
                        replace = prior['source_kind'] != 'actual_check' and (checked or '') >= (prior['checked_at'] or '')
                    else:
                        replace = (checked or '') >= (prior['checked_at'] or '')
                    if replace and prior['status'] in ('resolved', 'false_positive') and v['status'] in OPEN:
                        v['transition'] = 'reopened'
                        self.db.execute('UPDATE events SET data=? WHERE seq=?', (dump(v), seq))
                if replace:
                    self.db.execute('UPDATE issues SET status=?,latest_seq=?,version=version+1 WHERE id=?', (v['status'], seq, issue_id))
        return seq

    def decision(self, object_, instruction, evidence, decided_at=None):
        if not object_.get('note') or not object_.get('scope') or not instruction or not evidence:
            raise ValueError('scoped_decision_required')
        at = time_value(decided_at) if decided_at else None
        key = hashlib.sha256(dump([object_, instruction, evidence, at]).encode()).hexdigest()
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)',
                            (key, dump(object_), instruction, at, now(), dump(evidence)))
        return key

    def open_issues(self):
        return [dict(r) for r in self.db.execute('''SELECT i.*,e.data,e.checked_at,e.recorded_at,e.imported_at
             FROM issues i JOIN events e ON e.seq=i.latest_seq
             WHERE i.status IN ('problem','not_checked','modified_unverified')
             ORDER BY json_extract(i.object_json,'$.project'),json_extract(i.object_json,'$.note'),i.check_name,i.id''')]

    def context(self, notes=()):
        latest = self.db.execute("SELECT * FROM runs WHERE kind='processing' ORDER BY started_at DESC,rowid DESC LIMIT 1").fetchone()
        last_history = self.db.execute("SELECT * FROM runs WHERE kind='history_import' ORDER BY started_at DESC,rowid DESC LIMIT 1").fetchone()
        events = [dict(r) for r in self.db.execute('SELECT * FROM events WHERE run_id=? ORDER BY seq', (latest['id'],))] if latest else []
        relevant = []
        for row in self.db.execute('SELECT * FROM events ORDER BY seq'):
            if json.loads(row['object_json']).get('note') in notes:
                relevant.append(dict(row))
        decisions = [dict(r) for r in self.db.execute('SELECT * FROM decisions ORDER BY recorded_at,id')]
        return {'latest_processing': dict(latest) if latest else None, 'latest_processing_events': events,
                'latest_history_import': dict(last_history) if last_history else None,
                'open_issues': self.open_issues(), 'scoped_history': relevant, 'decisions': decisions}

    def prepare_read(self, rules=RULES, notes=(), page_chars=10000):
        if page_chars < 100 or page_chars > 20000:
            raise ValueError('page_chars_out_of_range')
        content = Path(rules).read_text(encoding='utf-8-sig')
        rules_hash = digest(rules)
        with self.transaction():
            context = self.context(notes)
            # Read every actual status field and evidence reference, without copying
            # entire archived source datasets again into each issue's startup text.
            for collection in ('latest_processing_events','open_issues','scoped_history'):
                compact=[]
                for row in context[collection]:
                    item={k:row.get(k) for k in ('id','issue_id','seq','status','checked_at','recorded_at','imported_at') if row.get(k) is not None}
                    data=json.loads(row['data'])
                    data.pop('original_record',None)
                    item.update(data);compact.append(item)
                context[collection]=compact
            body = '【业务规则全文】\n' + content + '\n【最新实际处理、全部未解决问题及专项历史】\n' + json.dumps(context, ensure_ascii=False, indent=2)
            pages = [body[i:i+page_chars] for i in range(0, len(body), page_chars)]
            receipt = 'READ-' + uuid.uuid4().hex
            self.db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?)',
                            (receipt, now(), str(Path(rules).resolve()), rules_hash, self.revision(), len(pages), dump(list(notes))))
            self.db.executemany('INSERT INTO receipt_pages VALUES(?,?,?,NULL)', [(receipt, i+1, p) for i,p in enumerate(pages)])
        return {'receipt': receipt, 'pages': len(pages), 'characters': len(body), 'rules_sha256': rules_hash,
                'instruction': '逐页调用 read-page，实际读完全部输出后再 begin；仅生成此清单不算读取。'}

    def page(self, receipt, page):
        r = self.db.execute('SELECT body FROM receipt_pages WHERE receipt_id=? AND page=?', (receipt, page)).fetchone()
        if not r:
            raise ValueError('unknown_read_page')
        return r['body']

    def mark_shown(self, receipt, page):
        with self.transaction():
            self.db.execute('UPDATE receipt_pages SET shown_at=? WHERE receipt_id=? AND page=?', (now(), receipt, page))

    def export(self):
        # Hold the transaction through view writes: a concurrent older exporter
        # must not overwrite a newer snapshot after releasing its read lock.
        with self.transaction():
            return self._export_locked()

    def _export_locked(self):
        context = self.context()
        all_events = [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY seq')]
        runs = [dict(r) for r in self.db.execute('SELECT * FROM runs ORDER BY started_at,rowid')]
        revision = self.revision()
        stamp = now()
        intro = f'生成时间：{stamp}；状态版本：{revision}。\n\n历史导入不代表本次重新核查原单或台账。\n'
        def render(e):
            d = json.loads(e['data']); obj = d['object']
            lines = [f"### {obj.get('note')} · {d['check']}",
                     f"对象：{obj.get('project','')}；范围：{obj['scope']}",
                     f"结果：{LABELS[d['status']]}；核对时间：{e.get('checked_at') or '时间不详'}；记录时间：{e['recorded_at']}",
                     f"来源：{'历史结果导入' if e.get('imported_at') else '实际检查'}；导入时间：{e.get('imported_at') or '不适用'}",
                     f"具体结果：{d['result']}", f"已做处理：{d['action']}", f"后续事项：{d['next']}",
                     '核对依据：'+dump(d['evidence'])]
            if e.get('id'): lines.insert(1,'问题编号：'+e['id'])
            if d.get('transition'): lines.append('状态变化：重新打开问题')
            return '\n\n'.join(lines)+'\n\n'
        issues = context['open_issues']
        atomic_text(self.root/'未解决问题清单.md', '# 未解决问题清单\n\n'+intro+f'\n未解决问题：{len(issues)} 项。\n\n'+''.join(render(e) for e in issues))
        latest = context['latest_processing']
        rows = context['latest_processing_events']
        if latest:
            heading = f"最新实际处理开始：{latest['started_at']}；状态：{latest['status']}；范围：{latest['scope']}\n\n"
        else:
            heading = '尚无本机制记录的实际业务复核。本次仅整理历史结果；未解决问题见独立清单。\n\n'
        atomic_text(self.root/'最新处理状态.md', '# 最新处理状态\n\n'+intro+'\n'+heading+''.join(render(e) for e in rows)+f'\n持续保留 {len(issues)} 项未解决问题。\n')
        for run in runs:
            name = run['started_at'].replace(':','').replace('+0800','')+'-'+run['id']+'.md'
            rows = [e for e in all_events if e['run_id'] == run['id']]
            atomic_text(self.root/'阶段报告'/name, '# 阶段处理记录\n\n'+intro+'\n'+dump(run)+'\n\n'+''.join(render(e) for e in rows))
        atomic_text(self.root/'状态索引.json', json.dumps({'generated_at':stamp,'revision':revision,'open_issues':len(issues),'runs':runs},ensure_ascii=False,indent=2))
        return {'revision':revision,'open_issues':len(issues),'reports':str(self.root)}


def cleanup_blockers(root, batch, notes):
    try:
        state = State(root)
    except (OSError, sqlite3.Error, TypeError) as exc:
        raise ValueError('state_unavailable: '+str(exc)) from exc
    try:
        ready = state.db.execute("SELECT value FROM meta WHERE key='history_import_complete'").fetchone()
        if not ready or ready[0] != 'true':
            raise ValueError('history_import_not_complete')
        result = []
        for row in state.open_issues():
            d = json.loads(row['data']); obj = d['object']
            if obj.get('note') in notes or str(batch) in d.get('related_batches', []):
                result.append(row['id']+':'+d['check'])
        return result
    except sqlite3.Error as exc:
        raise ValueError('state_unavailable: '+str(exc)) from exc
    finally:
        state.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', default=str(DEFAULT_ROOT))
    p.add_argument('--rules', default=str(RULES))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    q = sub.add_parser('read-context'); q.add_argument('--notes', nargs='*', default=[]); q.add_argument('--page-chars', type=int, default=10000)
    q = sub.add_parser('read-page'); q.add_argument('--receipt', required=True); q.add_argument('--page', required=True, type=int)
    q = sub.add_parser('begin'); q.add_argument('--receipt', required=True); q.add_argument('--scope', required=True)
    q = sub.add_parser('record'); q.add_argument('--run', required=True); q.add_argument('--input', required=True)
    q = sub.add_parser('finish'); q.add_argument('--run', required=True); q.add_argument('--status', choices=['completed','interrupted','failed'], required=True)
    q = sub.add_parser('guard'); q.add_argument('--run', required=True)
    q = sub.add_parser('cleanup-check'); q.add_argument('--batch', required=True); q.add_argument('--notes', nargs='*', default=[])
    sub.add_parser('export')
    a = p.parse_args()
    s = State(a.state_dir, create=a.command=='init')
    try:
        result = None
        if a.command == 'read-context': result = s.prepare_read(a.rules, a.notes, a.page_chars)
        elif a.command == 'read-page':
            print(s.page(a.receipt, a.page), flush=True)
            s.mark_shown(a.receipt, a.page)
            return
        elif a.command == 'begin': result = {'run':s.begin('processing', a.scope, a.receipt)}
        elif a.command == 'record':
            seq = s.record(a.run, json.loads(Path(a.input).read_text(encoding='utf-8-sig')), a.rules)
            result = {'sequence':seq, 'reports':s.export()}
        elif a.command == 'finish': s.finish(a.run, a.status); result = s.export()
        elif a.command == 'guard': s.require_run(a.run, a.rules); result = {'ready':True}
        elif a.command == 'export': result = s.export()
        elif a.command == 'cleanup-check':
            blockers = cleanup_blockers(a.state_dir, a.batch, a.notes)
            if blockers: raise ValueError('unresolved_related_issues: '+','.join(blockers))
            result = {'ready':True}
        else: result = {'initialized':str(s.path)}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        s.close()


if __name__ == '__main__':
    main()
