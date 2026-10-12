"""Pure distribution planning from reviewed records; never writes business workbooks."""
import argparse
import copy
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

FIELDS = ('project', 'seller', 'plan_date', 'material', 'brand', 'model', 'spec', 'length', 'mode')
COILS = {'盘螺', '高线', '线材'}
TOL = Decimal('0.001')  # Workbook ton precision, NOT the receipt loss threshold.


def text(value):
    if value is None:
        return ''
    return unicodedata.normalize('NFKC', str(value)).strip()


def number(value):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('missing_or_invalid_number') from None
    if not n.is_finite():
        raise ValueError('non_finite_number')
    return n


def iso(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('missing_or_invalid_date')
    date.fromisoformat(value)
    return value


def key(row):
    result = tuple(text(row.get(f)) for f in FIELDS)
    if not all(result):
        raise ValueError('missing_identity_or_material_field')
    iso(row['plan_date'])
    if row['mode'] not in ('factory', 'self_pickup'):
        raise ValueError('invalid_mode')
    return result


def quantities(row):
    tons, pcs = number(row.get('tons')), number(row.get('pieces'))
    if tons <= 0 or pcs <= 0 or pcs != pcs.to_integral():
        raise ValueError('invalid_tons_or_pieces')
    return tons, pcs


def loss_check(material, outbound, received=None):
    if material not in COILS:
        return {'status': 'not_applicable'}
    if received is None or received == '':
        return {'status': 'skipped_no_received_weight'}
    try:
        out, rec = number(outbound), number(received)
    except ValueError:
        return {'status': 'invalid_weight'}
    if out <= 0 or rec < 0:
        return {'status': 'invalid_weight'}
    ratio = (out-rec)/out
    return {'status': 'over_limit' if ratio > Decimal('0.003') else 'within_limit',
            'ratio': str(ratio), 'per_mille': str(ratio*1000)}


def stock_order(row):
    match = re.fullmatch(r'A-(\d+)', text(row.get('stock_id')))
    if not match:
        raise ValueError('unsupported_stock_number')
    return int(match[1])


def totals(rows):
    return tuple(sum((quantities(r)[i] for r in rows), Decimal(0)) for i in (0, 1))


def same_totals(a, b):
    return a[0].quantize(TOL,rounding=ROUND_HALF_UP) == b[0].quantize(TOL,rounding=ROUND_HALF_UP) and a[1] == b[1]


def plan(data):
    data = copy.deepcopy(data)
    stocks = data.get('stocks', [])
    existing = data.get('existing', [])
    legacy = data.get('legacy', [])
    incoming = data.get('incoming', [])
    stock_by_id, stock_groups = {}, defaultdict(list)
    used_pieces = defaultdict(Decimal)
    for s in stocks:
        k = key(s); quantities(s); stock_order(s)
        if s['stock_id'] in stock_by_id:
            raise ValueError('duplicate_stock_id')
        stock_by_id[s['stock_id']] = s
        stock_groups[k].append(s)
    for e in existing + legacy:
        key(e); quantities(e); iso(e.get('arrival_date'))
        if not isinstance(e.get('note_no'), str) or not text(e['note_no']):
            raise ValueError('note_number_must_be_reviewed_text')
    for e in existing:
        s = stock_by_id.get(e.get('stock_id'))
        if not s or key(s) != key(e):
            raise ValueError('existing_row_stock_identity_conflict')
        used_pieces[e['stock_id']] += number(e['pieces'])
    groups, errors, source_ids = defaultdict(list), [], set()
    for r in incoming:
        try:
            k = key(r); quantities(r); iso(r.get('arrival_date'))
            if not isinstance(r.get('note_no'), str) or not text(r['note_no']):
                raise ValueError('note_number_must_be_reviewed_text')
            if not text(r.get('line_id')) or r['line_id'] in source_ids:
                raise ValueError('missing_or_duplicate_source_line')
            source_ids.add(r['line_id'])
            groups[(text(r['note_no']), k)].append(r)
        except (ValueError, TypeError) as exc:
            errors.append({'status': 'blocked', 'note_no':text(r.get('note_no')), 'line_ids': [r.get('line_id')], 'reason': str(exc)})
    # Reject invalid repeated source IDs globally: do not allow the first copy to proceed.
    if any(e['reason'] == 'missing_or_duplicate_source_line' for e in errors):
        raise ValueError('missing_or_duplicate_source_line')
    arrivals_by_note = defaultdict(set)
    existing_arrivals = defaultdict(set)
    for (note, _), rows in groups.items():
        arrivals_by_note[note].update(r['arrival_date'] for r in rows)
    for r in existing:
        existing_arrivals[text(r['note_no'])].add(r['arrival_date'])
    results, proposals = list(errors), defaultdict(list)
    for (note, k), rows in groups.items():
        result = {'note_no': note, 'line_ids': [r['line_id'] for r in rows], 'status': 'blocked',
                  'loss_checks': [loss_check(r['material'], r['tons'], r.get('received_tons')) for r in rows]}
        results.append(result)
        if any(e.get('note_no') == note for e in errors):
            result['reason'] = 'other_detail_of_same_note_invalid'; continue
        arrivals = arrivals_by_note[note]
        if len(arrivals) != 1:
            result['reason'] = 'inconsistent_arrival_within_note'; continue
        arrival = next(iter(arrivals)); amount = totals(rows)
        if existing_arrivals[note] and existing_arrivals[note] != {arrival}:
            result['reason'] = 'existing_detail_difference_correct_do_not_append'; continue
        detail_signatures = [(r['arrival_date'],*quantities(r)) for r in rows]
        if len(set(detail_signatures)) != len(detail_signatures) and not all(r.get('repeated_detail_reviewed') is True for r in rows):
            result['reason'] = 'possible_duplicate_source_details'; continue
        same_number = [r for r in existing if text(r['note_no']) == note]
        same = [r for r in same_number if key(r) == k]
        if same:
            if all(r['arrival_date'] == arrival for r in same) and same_totals(totals(same), amount):
                result['status'] = 'already_synced'
            else:
                result['reason'] = 'existing_detail_difference_correct_do_not_append'
            continue
        # Same material under the same note but a changed plan/project is a correction candidate.
        if any(tuple(text(r[f]) for f in ('material','brand','model','spec','length')) ==
               tuple(text(rows[0][f]) for f in ('material','brand','model','spec','length')) for r in same_number):
            result['reason'] = 'same_number_identity_or_plan_difference'; continue
        old = [r for r in legacy if text(r['note_no']) == note]
        if old:
            result['status'] = 'legacy_record_exists'; result['reason'] = 'review_old_ledger_before_migration'; continue
        other = defaultdict(list)
        # Keep each dataset separate: an already-synced incoming row is not a second shipment.
        for dataset, r in [(label,r) for label,records in enumerate((existing,legacy,incoming)) for r in records]:
            # Invalid source rows are reported above and must not crash independent clear groups.
            try:
                if text(r.get('note_no')) != note and key(r) == k and r.get('arrival_date') == arrival:
                    quantities(r); other[(dataset,text(r.get('note_no')))].append(r)
            except (ValueError, TypeError):
                continue
        if any(same_totals(totals(v), amount) for v in other.values()) and not all(r.get('distinct_note_reviewed') is True for r in rows):
            result['reason'] = 'possible_duplicate_other_number'; continue
        if any(x['status'] == 'invalid_weight' for x in result['loss_checks']):
            result['reason'] = 'invalid_received_weight'; continue
        if not stock_groups[k]:
            result['reason'] = 'no_exact_inbound_match'; continue
        proposals[k].append((rows, result))

    for k, proposed in proposals.items():
        lots = sorted(stock_groups[k], key=stock_order)
        old = [e for e in existing if key(e) == k]
        new = [r for rows, _ in proposed for r in rows]
        pt, pp = totals(lots); dt, dp = totals(old+new)
        reason = None
        if any(used_pieces[s['stock_id']] > number(s['pieces']) for s in lots):
            reason = 'existing_stock_overdelivered'
        elif dp > pp:
            reason = 'batch_exceeds_remaining_pieces'
        elif k[3] in COILS:
            expected = pt*dp/pp
            if abs(dt-expected) > TOL:
                reviewed = any(key(r) == k and text(r.get('reason')) and
                               (number(r.get('delivered_tons')), number(r.get('delivered_pieces')),
                                number(r.get('purchase_tons')), number(r.get('purchase_pieces'))) == (dt,dp,pt,pp)
                               for r in data.get('estimate_reviews', []))
                if not reviewed:
                    reason = 'estimate_review_required'
        elif dp == pp and abs(dt-pt) > TOL:
            reason = 'purchase_weight_review_required'
        elif dp < pp:
            # Partial rebar/routine rigid material: compare with the actual FIFO lots, not a global average.
            remaining, expected = dp, Decimal(0)
            for lot in lots:
                take = min(remaining, number(lot['pieces']))
                expected += number(lot['tons'])*take/number(lot['pieces'])
                remaining -= take
            if abs(dt-expected) > TOL:
                reason = 'purchase_weight_review_required'
        if reason:
            for _, result in proposed:
                result['reason'] = reason
            continue
        trial = dict(used_pieces)
        group_allocations = []
        for rows, result in sorted(proposed, key=lambda pair:(pair[0][0]['arrival_date'],pair[1]['note_no'])):
            tons, pcs = totals(rows); remaining, used_tons = pcs, Decimal(0); allocation = []
            for lot in lots:
                sid = lot['stock_id']; capacity = number(lot['pieces'])-trial.get(sid, Decimal(0))
                take = min(capacity, remaining)
                if take <= 0: continue
                part = tons-used_tons if take == remaining else (tons*take/pcs).quantize(TOL, rounding=ROUND_HALF_UP)
                if part <= 0:
                    reason = 'split_weight_below_precision'; break
                allocation.append({'stock_id':sid,'tons':str(part),'pieces':int(take)})
                trial[sid] = trial.get(sid,Decimal(0))+take
                remaining -= take; used_tons += part
                if remaining == 0: break
            if reason or remaining != 0:
                reason = reason or 'insufficient_capacity'; break
            group_allocations.append((result, allocation))
        if reason:
            for _, result in proposed: result['reason'] = reason
            continue
        used_pieces.update(trial)
        for result, allocation in group_allocations:
            result.update(status='ready', allocations=allocation)
    statuses = []
    for s in stocks:
        used = used_pieces[s['stock_id']]; pcs = number(s['pieces'])
        status = 'invalid_overdelivery' if used > pcs else 'none' if used == 0 else 'complete' if used == pcs else 'partial'
        statuses.append({'stock_id':s['stock_id'],'delivered_pieces':str(used),'status':status})
    return {'results':results,'stock_status_candidates':statuses,'read_only':True,
            'counts':dict((s,sum(r['status']==s for r in results)) for s in sorted({r['status'] for r in results}))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True); parser.add_argument('--report', required=True)
    args = parser.parse_args()
    src, out = Path(args.input).resolve(), Path(args.report).resolve()
    if out == src or out.exists(): raise FileExistsError('Choose a new report path')
    settings = json.loads((Path(__file__).parent.parent/'assets/settings.json').read_text(encoding='utf-8-sig'))
    for root_key in ('pending_root','ledger_root','primary_archive_root','settlement_archive_root'):
        if out.is_relative_to(Path(settings[root_key]).resolve()): raise ValueError('Report must be outside business roots')
    result = plan(json.loads(src.read_text(encoding='utf-8-sig')))
    with out.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result['counts'],ensure_ascii=False))
