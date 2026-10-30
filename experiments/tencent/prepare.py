"""Prepare an isolated copy of pinned upstream launch scripts. Does not start Docker or read model keys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

PIN = 'ecc01a545da0b2ac6cae2f0f0af0d39d41469793'


def prepare(upstream: Path, destination: Path, namespace='team-share-compare'):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,35}', namespace):
        raise ValueError('invalid namespace')
    result = subprocess.run(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True)
    if result.stdout.strip() != PIN:
        raise ValueError('upstream checkout does not match the pinned comparison commit')
    if destination.exists():
        raise ValueError('comparison workspace must be new; existing data will not be overwritten')
    destination.mkdir(parents=True, mode=0o700)
    scripts = destination / 'scripts'
    shutil.copytree(upstream / 'deploy/global-images', scripts)
    changes = []
    for path in scripts.glob('*.sh'):
        source = path.read_text()
        changed = source
        names={'tdai-memory-core-data':namespace+'-core-data', 'tdai-panel-data':namespace+'-panel-data',
               'tdai-memory-core':namespace+'-memory-core', 'tdai-memory-hub':namespace+'-memory-hub',
               'tdai-proxy':namespace+'-proxy', 'tdai-memory-stack':namespace+'-memory-stack',
               'tdai-mongo-local':namespace+'-mongo-local', 'mongo-local-db':namespace+'-mongo-db',
               'mongo-local-configdb':namespace+'-mongo-configdb', 'mongo-local-mongot':namespace+'-mongo-mongot'}
        for name in sorted(names,key=len,reverse=True):
            changed = changed.replace(name, names[name])
        # Upstream binds published ports on all interfaces. This experiment must stay loopback-only.
        changed = re.sub(r'-p "\$\{(MEMORY_CORE_PORT|PANEL_PORT|KNOWLEDGE_PORT|PROXY_PORT)\}:', r'-p "127.0.0.1:${\1}:', changed)
        changed = changed.replace('/tmp/init-admin.$$', '"$SCRIPT_DIR/.init-admin.$$"')
        changed = changed.replace('set -euo pipefail', 'set -euo pipefail\numask 077')
        if path.name == 'start-all.sh':
            marker = '# 打印 Claude Code / proxy 使用命令'
            if marker not in changed:
                raise ValueError('upstream credential output block changed; review before preparing')
            changed = changed.split(marker, 1)[0] + '\n# Credential output removed for this private comparison.\n'
        path.write_text(changed)
        changes.append({'file': path.name, 'upstream_sha256': hashlib.sha256(source.encode()).hexdigest(),
                        'prepared_sha256': hashlib.sha256(changed.encode()).hexdigest()})
    # Independent ports and volumes; no user credentials are inserted here.
    example = (scripts / '.env.example').read_text()
    for key, value in {'MEMORY_CORE_PORT':'18420', 'PANEL_PORT':'18125', 'KNOWLEDGE_PORT':'18424', 'PROXY_PORT':'18096',
                       'MEMORY_CORE_VOLUME':namespace+'-core-data', 'PANEL_VOLUME':namespace+'-panel-data',
                       'KNOWLEDGE_PUBLIC_BASE_URL':'http://memory-hub:8424/v3'}.items():
        example = re.sub(r'^'+key+r'=.*$', key+'='+value, example, flags=re.M)
    example += '\n# Review and pin these three image digests before starting.\nMEMORY_HUB_PROXY_PUBLIC_URL=http://127.0.0.1:18096\n'
    (scripts / '.env.example').write_text(example)
    manifest = {'source':'https://github.com/TencentCloud/TencentDB-Agent-Memory', 'commit':PIN, 'namespace':namespace,
                'state':'PREPARED_NOT_DEPLOYED', 'docker_started':False, 'changes':changes,
                'required_before_start':['baseline real-team acceptance', 'private model configuration', 'record image digests', 'review private startup logs']}
    (destination / 'preparation.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--namespace', default='team-share-compare')
    args=parser.parse_args()
    manifest=prepare(args.upstream.resolve(), args.workspace.resolve(), args.namespace)
    print(json.dumps({k:manifest[k] for k in ('commit','namespace','state','docker_started')}))
