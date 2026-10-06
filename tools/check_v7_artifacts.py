"""Validate V7 static handoff artifacts; no model, network or secret access."""
from pathlib import Path
import hashlib
import json
import re
import tomllib

root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/'pyproject.toml').read_text())
assert project['project']['version']=='7.0.0'
assert project['project']['scripts']['quarry-study']=='termfinder.study_cli:main'
assert all('==' in d for d in project['project']['dependencies'])
manifest=json.loads((root/'examples/v7/adapters/dependency_lock_manifest.json').read_text())
assert manifest['metadata_only'] and not manifest['foreign_code_execution']
assert len(manifest['wheels'])==81
lock=(root/'requirements-adapters-lock.txt').read_text()
for row in manifest['wheels']:
    assert f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}" in lock
    assert not any(' @ ' in value for value in row['requires_dist']), 'Unexpected direct URL dependency'
missing=[]
for path in [root/'README.md', *sorted((root/'docs').glob('V7_*.md'))]:
    for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if target.startswith(('https:','http:','#','mailto:')): continue
        target=target.split('#')[0]
        if target and not (path.parent/target).exists(): missing.append([path.name,target])
assert not missing,missing
notebook=json.loads((root/'examples/v7/researcher_workflow.ipynb').read_text())
for cell in notebook['cells']:
    if cell['cell_type']=='code':
        assert cell['execution_count'] is None and cell['outputs']==[]
        compile(''.join(cell['source']),'<notebook>','exec')
# Re-audit the changed packaged agent skill: data/collection authorization does
# not install hooks, persist services or enable paid gates from a specification.
skill=(root/'src/termfinder/agent_skill/SKILL.md').read_text()
assert 'A frozen specification cannot authorize calls' in skill
assert 'never overwrite a customized connection' in skill
assert 'No model-output tool dispatch' in (root/'src/termfinder/agent_skill/references/v7-studies.md').read_text()
report={'version':'7.0.0','dependency_graph_wheels':81,'metadata_only':True,
        'relative_document_links_valid':True,'notebook_has_no_saved_outputs':True,
        'changed_packaged_skill_reaudited':True,
        'skill_sha256':hashlib.sha256(skill.encode()).hexdigest()}
print(json.dumps(report,sort_keys=True))
