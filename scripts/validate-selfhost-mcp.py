"""Opt-in REAL GitHub/MCP acceptance using only synthetic material in a private TEST repo.
Usage: python scripts/validate-selfhost-mcp.py --repo OWNER/PRIVATE_TEST_REPO
Does not create the repo or touch installed client config. Not a human/member acceptance.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def run(args, **kwargs):
    result=subprocess.run(args,capture_output=True,text=True,timeout=60,**kwargs)
    if result.returncode:raise RuntimeError('test prerequisite failed; private diagnostics withheld')
    return result.stdout


async def validate(repo):
    import re
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('OWNER/REPO required')
    meta=json.loads(run(['gh','api','repos/'+repo]))
    if not meta.get('private') or not meta.get('permissions',{}).get('push'):raise ValueError('private writable TEST repo required')
    marker=subprocess.run(['gh','api','repos/'+repo+'/contents/.team-memory.yml?ref=main'],capture_output=True,text=True,timeout=30,check=False)
    if marker.returncode and '(HTTP 404)' not in marker.stderr:raise RuntimeError('marker check failed')
    if marker.returncode:
        payload={'message':'Initialize synthetic validation memory','branch':'main','content':base64.b64encode(b'team_name: SYNTHETIC VALIDATION\nversion: "0.1.0"\ntool: team-memory\n').decode()}
        run(['gh','api','--method','PUT','repos/'+repo+'/contents/.team-memory.yml','--input','-'],input=json.dumps(payload))
    proof={'materials':'synthetic only','native_model_tool_trigger':'NOT_TESTED','human_members':'NOT_TESTED','authors':{}}
    with tempfile.TemporaryDirectory(prefix='team-memory-live-mcp-') as tmp:
        root=Path(tmp);root.chmod(0o700)
        for author,source in [('alice','codex'),('bob','claude')]:
            cache=root/author
            run(['git','clone','--quiet','https://github.com/'+repo+'.git',str(cache)])
            env={**os.environ,'TEAM_MEMORY_ROOT':str(cache),'TEAM_MEMORY_AUTHOR':author,
                 'TEAM_MEMORY_OUTBOX':str(root/(author+'-outbox')),'TEAM_MEMORY_AUTO_SYNC':'1',
                 'TEAM_MEMORY_UPLOAD_ENABLED':'1','TEAM_MEMORY_GITHUB_REPO':repo,'TEAM_MEMORY_GH':shutil.which('gh')}
            args=StdioServerParameters(command=sys.executable,args=['-m','team_memory.shared_mcp'],env=env)
            async with stdio_client(args) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    payload={'title':'SYNTHETIC self-host acceptance '+author,'source':source,
                       'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL,repo+':v0.5.0-candidate.1:'+author)),
                       'summary':{
                          'purpose':'SYNTHETIC: verify isolated MCP to private GitHub; not a real team decision.',
                          'process':'Use installed candidate MCP through stdio, archive once and retry same ID.',
                          'results':'This record is a test input, not evidence that human Feishu acceptance passed.',
                          'insights':'Preserve authors and source versions; transport success is distinct from native model triggering.',
                          'applications':'Repeatable synthetic acceptance only.',
                          'discussions':'Real independent Feishu app, participant confirmation and Ubuntu deployment remain pending.'},
                       'source_refs':['synthetic:selfhost-v0.5.0-candidate.1']}
                    result=await session.call_tool('archive_shared_memory',payload)
                    def decode(value):
                        if value.isError:raise RuntimeError('MCP error')
                        return json.loads(next(c.text for c in value.content if c.type=='text'))
                    first=decode(result);assert first.get('uploaded')
                    duplicate=decode(await session.call_tool('archive_shared_memory',payload));assert duplicate.get('duplicate')
                    readback=decode(await session.call_tool('get_shared_memory',{'memory_id':first['id']}))
                    assert readback['record']['author']==author and 'SYNTHETIC' in readback['record']['body']
                    search=decode(await session.call_tool('search_shared_memory',{'query':'SYNTHETIC'}));assert search['results']
                    proof['authors'][author]={'archive':True,'retry_deduplicated':True,'query_and_readback':True,'source':source}
    proof['status']='PASS'
    return proof

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=asyncio.run(validate(a.repo));a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
