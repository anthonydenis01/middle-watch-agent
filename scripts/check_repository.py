"""Scan tracked/source build files and history without printing matched content."""
import json, re, subprocess
from pathlib import Path

def git(*args):
    return subprocess.check_output(['git', *args])

tracked = git('ls-files', '-z').decode().split('\0')
untracked = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
paths = [Path(p) for p in set(tracked + untracked) if p] + list(Path('web/dist').rglob('*'))
forbidden = re.compile('|'.join(re.escape(x) for x in ['M' + 'SC', 'Mediter' + 'ranean', 'top-' + 'five', 'cal' + 'endly', 'pi' + 'lot', '$1,' + '950', 'pri' + 'cing']), re.I)
secret = re.compile(r'(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|postgres(?:ql)?(?:\+psycopg)?://[^\s:/]+:[^\s@]+@)')
hits, secrets, wording = [], [], []
for path in paths:
    if not path.is_file(): continue
    content = path.read_text(encoding='utf-8', errors='replace')
    for line, text in enumerate(content.splitlines(), 1):
        if forbidden.search(text): hits.append(f'{path}:{line}')
        if secret.search(text): secrets.append(f'{path}:{line}')
        if ('deployed in ' + 'production') in text.lower(): wording.append(f'{path}:{line}')
history = git('log', 'HEAD', '-p', '--all-match', '--format=commit %h').decode(errors='replace')
history_hits = len(secret.findall(history))
assert git('check-ignore', '.env').strip() == b'.env'
assert all(not line.split('=', 1)[1].strip() for line in Path('.env.example').read_text().splitlines() if '=' in line and not line.startswith('#'))
print(json.dumps({'clean_room_hits': hits, 'secret_locations': secrets, 'history_secret_hits': history_hits, 'wording_hits': wording, 'env_ignored_and_example_empty': True}, indent=2))
assert not (hits or secrets or history_hits or wording)
