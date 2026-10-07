"""One-time synthetic fixture builder using archived 7c3ddc7 sources.

Run through verify_offline.py without --source. This intentionally imports
the old implementation, never the working implementation being tested.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
BASELINE=ROOT/"verification/baseline-7c3ddc7/src"
sys.path.insert(0,str(BASELINE))
from termfinder import Project,FakeProvider
from termfinder.config import starter_recipe
from termfinder.sources import parse_document

def main():
    destination=ROOT/"tests/fixtures/legacy-6.6"
    destination.mkdir(parents=True,exist_ok=True)
    if (destination/"project.sqlite3").exists():raise ValueError("Legacy fixture already exists")
    with tempfile.TemporaryDirectory() as temporary:
        project=Project(Path(temporary)/"legacy")
        project.configure(starter_recipe("neologisms"),"fake")
        text="🧪 Café crews call a pause a moonstep. The anchor holds the checkpoint."
        project.add_source(parse_document(text.encode(),"text/plain","legacy-synthetic.txt",{"language":"en","community":"Gaming","constraints":{"content_origin":"synthetic_fixture"}}))
        provider=FakeProvider([{"expression":"moonstep","language":"en","sense":"a pause","context":text,"attributes":{}},
            {"expression":"anchor","language":"en","sense":"checkpoint holder","context":text,"attributes":{}},
            {"expression":"anchor","language":"en","sense":"last defender","context":text,"attributes":{}}])
        project.collect(provider)
        version=project.snapshot("legacy-synthetic-6.6")
        project.export(version,Path(temporary)/"export",["jsonl"])
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(temporary)/"export").iterdir()}
        project.store.backup(destination/"project.sqlite3")
    metadata={"builder_commit":"7c3ddc7","builder_package":"6.6.0","synthetic_only":True,
              "version_id":version,"source_count":1,"term_count":3,"occurrence_count":3,
              "database_sha256":hashlib.sha256((destination/"project.sqlite3").read_bytes()).hexdigest(),
              "jsonl_export_sha256":hashes,"builder":"tools/make_legacy_fixture.py imports archived old source; no current engine construction"}
    (destination/"receipt.json").write_text(json.dumps(metadata,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"created":True,"synthetic_only":True,"version_id":version,"sha256":metadata["database_sha256"]}))

if __name__=="__main__":main()
