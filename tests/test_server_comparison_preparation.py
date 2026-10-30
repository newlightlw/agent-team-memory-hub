import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'experiments/tencent/prepare.py'
    spec=importlib.util.spec_from_file_location('comparison_preparation',path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_comparison_is_loopback_namespaced_and_does_not_start_docker(tmp_path,monkeypatch):
    prepare=module()
    upstream=tmp_path/'upstream'
    scripts=upstream/'deploy/global-images'
    scripts.mkdir(parents=True)
    (scripts/'.env.example').write_text('MEMORY_CORE_PORT=8420\nPANEL_PORT=8125\nKNOWLEDGE_PORT=8424\nPROXY_PORT=8096\nMEMORY_CORE_VOLUME=tdai-memory-core-data\nPANEL_VOLUME=tdai-panel-data\nKNOWLEDGE_PUBLIC_BASE_URL=http://localhost:8424/v3\n')
    (scripts/'start-all.sh').write_text('set -euo pipefail\n# 打印 Claude Code / proxy 使用命令\necho "$ADMIN_KEY"\n')
    (scripts/'start-memory-core.sh').write_text('set -euo pipefail\nCONTAINER=tdai-memory-core\nNETWORK=tdai-memory-stack\ndocker run -p "${MEMORY_CORE_PORT}:8420"\necho /tmp/init-admin.$$\n')
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=prepare.PIN+'\n')
    monkeypatch.setattr(prepare.subprocess,'run',run)
    workspace=tmp_path/'comparison'
    result=prepare.prepare(upstream,workspace)
    assert result['state']=='PREPARED_NOT_DEPLOYED' and not result['docker_started']
    assert len(calls)==1 and calls[0][0]=='git'
    core=(workspace/'scripts/start-memory-core.sh').read_text()
    assert '-p "127.0.0.1:${MEMORY_CORE_PORT}:8420"' in core
    assert 'CONTAINER=team-share-compare-memory-core' in core
    assert '/tmp/init-admin' not in core and 'umask 077' in core
    assert 'ADMIN_KEY' not in (workspace/'scripts/start-all.sh').read_text()
    with pytest.raises(ValueError,match='new'):
        prepare.prepare(upstream,workspace)


def test_wrong_upstream_commit_never_creates_workspace(tmp_path,monkeypatch):
    prepare=module()
    monkeypatch.setattr(prepare.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='different\n'))
    destination=tmp_path/'must-not-exist'
    with pytest.raises(ValueError,match='pinned'):
        prepare.prepare(tmp_path,destination)
    assert not destination.exists()
