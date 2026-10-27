"""Summarize first-presentation traces from bounded Pi performance history."""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import math
from pathlib import Path
import statistics


METRICS = (
    'source_to_present_ms', 'publisher_to_present_ms', 'publisher_to_ingress_ms',
    'request_to_present_ms', 'core_to_present_ms', 'snapshot_to_present_ms',
    'ingress_to_core_ms', 'core_to_snapshot_ms', 'ingress_to_snapshot_ms',
    'snapshot_to_projection_ms', 'projection_to_publication_ms', 'publication_to_receive_ms',
    'decode_ms', 'client_prepare_ms', 'queue_ms', 'accept_ms', 'pane_prepare_ms',
    'visibility_wait_ms', 'present_ms', 'device_to_present_ms',
)


def summarize(records):
    traces = [row for row in records if row.get('kind') == 'latency']
    seen, first, duplicates = set(), [], 0
    for row in traces:
        if row.get('outcome') != 'presented':
            continue
        key = (row.get('device_id'), row.get('item_id'), row.get('trace_id'))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        first.append(row)
    groups = {}
    for source in sorted({row.get('source', '') for row in first}):
        selected = [row for row in first if row.get('source') == source]
        metrics = {}
        for key in METRICS:
            values = sorted(row[key] for row in selected if isinstance(row.get(key), (int, float))
                            and math.isfinite(row[key]) and row[key] >= 0 and row.get('clock_order_valid', True))
            if values:
                metrics[key] = {'count': len(values), 'p50_ms': statistics.median(values),
                                'min_ms': values[0], 'max_ms': values[-1],
                                'p95_ms': values[min(len(values)-1, int(len(values)*0.95))] if len(values) >= 20 else None}
        groups[source] = {'unique_presentations': len(selected), 'metrics': metrics}
    return {'trace_records': len(traces), 'outcomes': dict(Counter(row.get('outcome') for row in traces)),
            'unique_presentations': len(first), 'duplicate_presentations_excluded': duplicates,
            'invalid_clock_records': sum(not row.get('clock_order_valid', True) for row in traces),
            'sources': groups, 'first_presentations': first}


def load_records(paths):
    records = []
    for path in paths:
        with path.open(encoding='utf-8') as source:
            records.extend(json.loads(line) for line in source if line.strip())
    return records


def render_source_sections(sources):
    sections = []
    for source, group in sources.items():
        rows = ''.join(f'<tr><td>{html.escape(key)}</td><td>{value["count"]}</td><td>{value["p50_ms"]:.1f}</td>'
                       f'<td>{value["min_ms"]:.1f} - {value["max_ms"]:.1f}</td></tr>' for key, value in group['metrics'].items())
        sections.append(f'<section><h2>{html.escape(source)}</h2><p>{group["unique_presentations"]} unique first presentations.</p>'
                        f'<table><tr><th>Stage</th><th>Samples</th><th>Median ms</th><th>Range ms</th></tr>{rows}</table></section>')
    return ''.join(sections)


def render_fastcast_headline(sources):
    fastcast = sources.get('espn_fastcast', {})
    metrics = fastcast.get('metrics', {})
    if 'source_to_present_ms' in metrics and 'publisher_to_present_ms' in metrics:
        return ('<section><h2>Observed Fastcast path</h2><p><strong>'
                f'{metrics["source_to_present_ms"]["p50_ms"] / 1000:.3f} s receipt to display</strong> &#183; '
                f'{metrics["publisher_to_present_ms"]["p50_ms"] / 1000:.3f} s from the ESPN envelope timestamp.</p>'
                f'<p>Based on {fastcast["unique_presentations"]} unique first-presentation sample(s). '
                'Read the trial context before treating these values as production or typical latency.</p></section>')
    return ''


def render_event_rows(first_presentations):
    return ''.join('<tr>'+''.join(f'<td>{html.escape(str(row.get(key, "")))}</td>' for key in (
        'source','trace_id','source_to_present_ms','publisher_to_present_ms','ingress_to_snapshot_ms','device_to_present_ms'))+'</tr>'
        for row in first_presentations)


def render_html(result):
    headline = render_fastcast_headline(result['sources'])
    sections = render_source_sections(result['sources'])
    events = render_event_rows(result['first_presentations'])
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Input to display latency</title><style>body{font:15px system-ui;background:#101723;color:#e8edf5;max-width:1150px;margin:36px auto;padding:0 20px;line-height:1.6}section{background:#182334;border:1px solid #304158;border-radius:9px;padding:20px;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #304158;text-align:left;overflow-wrap:anywhere}p{color:#bdcce0}.note{color:#ffd59e}.scroll{overflow:auto}a{color:#9bceff}</style>
<h1>Input to display latency</h1><p>__CONTEXT__</p>__HEADLINE__
<section><strong>__COUNT__ unique first presentations</strong><p>Duplicate presentations excluded: __DUPLICATES__. Invalid clock-order records: __INVALID__.</p>
<p class="note">Fastcast's nested <code>ts</code> is a publication-envelope timestamp. It does not verify the time of the real-world play or a television broadcast. A single sample is a proof of the path, not a typical latency estimate.</p>
<p>The end boundary is successful frame-sink return. For the physical RGB matrix driver, this follows the vertical-sync swap. LED scan time is not measured.</p>
<p>Only the first presentation of each input trace is counted. Superseded updates and unchanged pixels do not produce a display latency. Tail percentiles require at least twenty samples.</p></section>
__SOURCES__<section class="scroll"><h2>First presentations</h2><table><tr><th>Source</th><th>Input trace</th><th>Input to display ms</th><th>Publisher to display ms</th><th>Input to snapshot ms</th><th>Device portion ms</th></tr>__EVENTS__</table></section></html>'''
    replacements = {'__CONTEXT__': html.escape(result['context']), '__COUNT__': str(result['unique_presentations']),
                    '__DUPLICATES__': str(result['duplicate_presentations_excluded']), '__INVALID__': str(result['invalid_clock_records']),
                    '__SOURCES__': ''.join(sections), '__EVENTS__': events, '__HEADLINE__': headline}
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', action='append', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Write JSON and a sibling HTML report.')
    parser.add_argument('--context', default='Pi runtime trace. Cross-host measurements require synchronized clocks.')
    args = parser.parse_args()
    result = summarize(load_records(args.log))
    result['context'] = args.context
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    args.output.with_suffix('.html').write_text(render_html(result), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('trace_records','unique_presentations','duplicate_presentations_excluded','invalid_clock_records')}, indent=2))


if __name__ == '__main__':
    main()
