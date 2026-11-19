import json
import subprocess

vol = 'harness-harness-local-dev-home-319fc425-cf45-4307-b4a9-b693fe67cad9'
f = subprocess.check_output([
    'docker', 'run', '--rm', '-v', f'{vol}:/data:ro', 'alpine', 'sh',
    '-c', 'ls -S /data/storages/session_projcache/sessions/*.json | head -1',
]).decode().strip()
data = subprocess.check_output(['docker', 'run', '--rm', '-v', f'{vol}:/data:ro', 'alpine', 'cat', f])
d = json.loads(data)
rows = d['record']['rows']
print('ROWS:', list(rows.keys()))
for k, v in rows.items():
    s = json.dumps(v, ensure_ascii=False)
    print(f'--- {k} ({len(s)}) ---')
    print(s[:700])
