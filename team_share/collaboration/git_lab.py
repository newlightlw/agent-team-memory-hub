"""Persistent, account-free local Git practice. Synthetic records; no network/worker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from .config import Member, Settings
from .projection import export, git
from .service import Collaboration


def _service(path: Path):
    members = tuple(Member(name, name, '',
        hashlib.sha256((name + ':DEMO_ONLY:publisher').encode()).hexdigest(),
        hashlib.sha256((name + ':DEMO_ONLY:reader').encode()).hexdigest())
        for name in ('demo_author', 'demo_observer'))
    return Collaboration(Settings(data_dir=path, members=members, team_id='git-lab')), members[0]


def run(destination: Path):
    root = destination.expanduser().absolute()
    if root.exists() or root.is_symlink():
        raise ValueError('Git practice requires a NEW directory; existing files are never replaced')
    root.mkdir(parents=True, mode=0o700)
    service, author = _service(root / 'versions')
    source = service.create(author, dict(kind='share', title='DEMO_ONLY raw source',
        body='Synthetic chat fragment; never included in Git.', project='git-lab'), source='local_synthetic_lab')
    topic = service.create(author, dict(kind='topic', title='DEMO_ONLY: Git 接入练习',
        body='合成资料 LANTERN：先检查来源，再共享指定片段。', project='git-lab',
        parents=[source['id']]), source='local_synthetic_lab')
    repo = export(service.store)
    first = git(repo, 'rev-parse', 'HEAD').strip()
    topic = service.revise(author, topic['id'], dict(revision=1, title=topic['title'],
        body='合成资料 LANTERN：先检查来源，再共享指定片段；查询结果保留作者与版本。'))
    export(service.store)
    second = git(repo, 'rev-parse', 'HEAD').strip()
    diff = git(repo, 'diff', first, second, '--', 'topic')
    assert first != second and 'revision' in diff and '查询结果保留作者与版本' in diff
    assert len(service.store.history(topic['id'])) == 2
    export(service.store)
    assert git(repo, 'rev-parse', 'HEAD').strip() == second  # Unchanged export is idempotent.
    proposal = service.create(author, dict(kind='decision', title='DEMO_ONLY: 未确认的示例提案',
        body='仅用于本机观察提案状态；没有真实成员确认。', project='git-lab',
        parents=[topic['id']]), source='local_synthetic_lab')
    export(service.store)
    files = git(repo, 'ls-files').splitlines()
    assert any(name == 'decision/' + proposal['id'] + '.md' for name in files)
    assert not any(name.startswith(('share/', 'memory/decisions/')) for name in files)
    assert service.detail(proposal['id'])['confirmed_by'] == []
    assert service.detail(proposal['id'])['status'] == 'pending_confirmation'
    assert git(repo, 'rev-list', '--count', 'HEAD').strip() == '3'
    assert not git(repo, 'remote').strip()

    # A SEPARATE disposable projection demonstrates the existing purge policy.
    # Keep the first repository's version history available for human inspection.
    withdrawal, other_author = _service(root / 'withdrawal')
    survivor = withdrawal.create(other_author, dict(kind='focus', title='DEMO_ONLY: 保留记录',
        body='无关记录应在清理后保留。', project='git-lab'), source='local_synthetic_lab')
    record = withdrawal.create(other_author, dict(kind='topic', title='DEMO_ONLY: 撤回样例',
        body='SYNTHETIC_PURGE_MARKER_20261030', project='git-lab'), source='local_synthetic_lab')
    purge_repo = export(withdrawal.store)
    old_commit = git(purge_repo, 'rev-parse', 'HEAD').strip()
    withdrawal.store.withdraw(record['id'], other_author.id)
    export(withdrawal.store, purge=True)
    assert not (purge_repo / 'topic' / (record['id'] + '.md')).exists()
    assert (purge_repo / 'focus' / (survivor['id'] + '.md')).is_file()
    assert not withdrawal.search('SYNTHETIC_PURGE_MARKER_20261030')['results']
    missing = subprocess.run(['git', '-C', str(purge_repo), 'cat-file', '-e', old_commit + '^{commit}'],
                             capture_output=True)
    assert missing.returncode != 0  # No old source object left in this dedicated projection.
    assert git(purge_repo, 'rev-list', '--count', 'HEAD').strip() == '1'
    assert not git(purge_repo, 'remote').strip()
    report = dict(mode='DEMO_ONLY', status='PASS', real_confirmations=0,
        network_calls=0, versions_repository=str(repo), withdrawal_repository=str(purge_repo),
        topic_id=topic['id'], proposal_id=proposal['id'], first_commit=first, second_commit=second,
        version_commits=3, raw_share_excluded=True, pending_proposal_not_consensus=True,
        unchanged_export_is_idempotent=True, withdrawal_old_git_object_removed=True,
        withdrawal_unrelated_record_preserved=True)
    (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (root / 'README.md').write_text(f'''# 本机 Git 接入练习（DEMO_ONLY）

这是合成记录，不是正式群数据，没有读取发布凭证，没有发送消息、推送远端或代替真人确认。

## 版本库

`versions/knowledge` 有三个提交：议题初版、议题修改、未确认提案。
原始消息不进 Git。`decision/` 中的 pending_confirmation 提案不代表双方共识；
只有双方真实确认的决策才能成为 `memory/decisions/` 中的有效决策。

```sh
git -C "{repo}" log --oneline
git -C "{repo}" diff {first} {second} -- topic
```

议题文件：`versions/knowledge/topic/{topic['id']}.md`。
也可用编辑器打开本练习目录查看 Markdown 和 report.json。

## 撤回库

`withdrawal/knowledge` 是单独的清理练习库。撤回样例及原 Git 对象已移除，无关记录保留。
当前实现会重建服务专属的本地投影仓库，因此普通版本历史与隐私清理是两种不同操作。
不能据此声称其他人的克隆、备份或未来远端也已清除。

## 正式接入的区别

正式内容由本人审阅发布到团队服务后，服务才生成 Git 投影；不能通过编辑这些 Markdown
反向修改权威记录。正式记录通过 reader MCP 查询。这个练习不修改现有 reader MCP 配置。
''', encoding='utf-8')
    return report
