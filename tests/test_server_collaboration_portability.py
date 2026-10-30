from dataclasses import replace
import hashlib
import json

import pytest

from team_share.collaboration.__main__ import init
from team_share.collaboration.config import Settings
from team_share.collaboration.onboarding import configure_feishu


def test_versioned_configuration_rejects_unsupported_version_and_team_id(tmp_path):
    root = tmp_path / 'instance'
    init(root, ['alice', 'bob'])
    path = root / 'config.json'
    settings = Settings.load(path)
    assert settings.config_version == 2
    assert [m.id for m in settings.members] == ['alice', 'bob']
    with pytest.raises(ValueError, match='team_id'):
        replace(settings, team_id='../outside')
    data = json.loads(path.read_text())
    data['config_version'] = 99
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='unsupported'):
        Settings.load(path)


def test_noninteractive_onboarding_cannot_change_private_configuration(tmp_path, monkeypatch):
    root = tmp_path / 'instance'
    init(root, ['alice', 'bob'])
    path = root / 'config.json'
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(ValueError, match='interactive'):
        configure_feishu(path)
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
