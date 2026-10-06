"""Check the independently installed wheel, CLI and offline notebook in isolation."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import termfinder

root=Path(__file__).resolve().parents[1]
package=Path(termfinder.__file__).resolve()
assert '.venv-v7' in package.parts and 'site-packages' in package.parts, package
assert termfinder.__version__=='7.0.0'
with tempfile.TemporaryDirectory(prefix='v7-installed-') as d:
    out=Path(d)/'demo'
    cli=Path(sys.executable).parent/'quarry-study'
    result=subprocess.run([str(cli),'demo','--out',str(out)],cwd=d,check=True,stdout=subprocess.PIPE,text=True)
    summary=json.loads(result.stdout)
    assert summary['paid_requests']==0 and summary['report_reproduces_without_calls']
    report=out/'recomputed.json'
    subprocess.run([str(cli),'compare',str(out/'comparison.json'),'--out',str(report)],cwd=d,check=True)
    assert json.loads(report.read_text())==json.loads((out/'occurrence-report.json').read_text())
    subprocess.run([str(cli),'--help'],cwd=d,check=True,stdout=subprocess.DEVNULL)
    subprocess.run([str(Path(sys.executable).parent/'termfinder'),'--help'],cwd=d,check=True,stdout=subprocess.DEVNULL)
    notebook=json.loads((root/'examples/v7/researcher_workflow.ipynb').read_text())
    namespace={}
    for cell in notebook['cells']:
        if cell['cell_type']=='code':
            exec(compile(''.join(cell['source']),'<reviewed-v7-notebook>','exec'),namespace)
    namespace['demo_directory'].cleanup()
    print(json.dumps({'installed_version':termfinder.__version__,'package_file':str(package),
       'source_pythonpath_used':False,'demo_arms':summary['arms'],'cli_roundtrip':True,
       'notebook_code_cells_executed':sum(c['cell_type']=='code' for c in notebook['cells'])},sort_keys=True))
