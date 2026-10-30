#!/usr/bin/env python3
"""
Populates Baserow table from a timeline.json file.
Usage: python3 populate_baserow.py <path_to_timeline.json>
"""

import json
import sys
import subprocess

BASEROW_TOKEN = '4QrZH5MkTLHKtGqTG97Gz2yQTAIhknMq'
TABLE_ID = '1100194'
API_BASE = 'https://api.baserow.io/api'

def curl(method, path, data=None):
    url = API_BASE + path
    cmd = ['curl', '-s', '-X', method, url,
           '-H', f'Authorization: Token {BASEROW_TOKEN}',
           '-H', 'Content-Type: application/json']
    if data:
        cmd += ['-d', json.dumps(data)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)

def get_all_row_ids():
    rows = []
    page = 1
    while True:
        data = curl('GET', f'/database/rows/table/{TABLE_ID}/?user_field_names=true&size=200&page={page}')
        rows += [r['id'] for r in data.get('results', [])]
        if not data.get('next'):
            break
        page += 1
    return rows

def delete_all_rows(ids):
    for rid in ids:
        curl('DELETE', f'/database/rows/table/{TABLE_ID}/{rid}/')
        print(f'  Deleted row {rid}')

def create_rows(items):
    result = curl('POST', f'/database/rows/table/{TABLE_ID}/batch/?user_field_names=true', {'items': items})
    return result.get('items', [])

def main():
    if len(sys.argv) < 2:
        print('Usage: python3 populate_baserow.py <path_to_timeline.json>')
        sys.exit(1)

    timeline_path = sys.argv[1]
    with open(timeline_path, 'r', encoding='utf-8') as f:
        timeline = json.load(f)

    segments = timeline.get('visual_timeline', [])
    if not segments:
        print('No segments found in timeline.json')
        sys.exit(1)

    print(f'Found {len(segments)} segments in timeline.json')

    print('Fetching existing rows...')
    existing_ids = get_all_row_ids()
    if existing_ids:
        print(f'Deleting {len(existing_ids)} existing rows...')
        delete_all_rows(existing_ids)
    else:
        print('Table is already empty.')

    print('Creating new rows...')
    items = []
    for seg in segments:
        prompt = seg.get('ia_prompt', seg.get('prompt_or_query', '')).strip()
        seg_id = seg.get('segment_id', '')
        description = seg.get('scene_description_es', '')
        dur = round(seg.get('end_seconds', 0) - seg.get('start_seconds', 0), 1)
        items.append({
            'Image Prompt': prompt,
            'VEO Prompt': f"Slow cinematic zoom in, {description}",
            'Mode': 'Imagegen',
            'Status': 'pending'
        })

    created = create_rows(items)
    print(f'\n✓ Created {len(created)} rows in Baserow:')
    for row in created:
        print(f"  Row {row['id']} — {row.get('Image Prompt', '')[:60]}")

    print('\nDone. Open Flow and start the extension to generate images.')

if __name__ == '__main__':
    main()
