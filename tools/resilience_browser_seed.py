"""Create only a fresh synthetic verification seed for bounded browser testing."""
import json
import argparse
from pathlib import Path
import time

from termfinder import Project, FakeProvider, Response
from termfinder.config import starter_recipe
from termfinder.engine import Engine
from termfinder.providers import ProviderError
from termfinder.sources import parse_document


class Clock:
    def __init__(self): self.value=time.time()
    def time(self): return self.value
    def monotonic(self): return self.value
    def sleep(self,seconds): self.value+=seconds


class Provider(FakeProvider):
    def __init__(self): super().__init__([])
    def complete(self,request):
        if request["expert"]["model"]=="glm": raise ProviderError("synthetic_timeout",uncertain=True,retryable=True)
        expression=request["text"].split()[0]
        proposal={"expression":expression,"language":"en","sense":"a fictional pause",
                  "context":request["text"],"start":0,"attributes":{},"definition_quote":None,"translation":None}
        return Response(json.dumps({"candidates":[proposal],"coverage_complete":True}),20,10,"stop","synthetic-browser-v1")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=Path("verification/resilience-ui-seed"))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    path=(root/args.out).resolve()
    if not path.is_relative_to(root/"verification"): raise ValueError("Seed must stay under verification")
    if path.exists(): raise ValueError("Use a fresh verification seed; existing outputs stay preserved")
    project=Project(path);recipe=starter_recipe("neologisms")
    recipe["execution"]["resilience"].update(jitter_fraction=0,min_request_interval_seconds=0)
    project.configure(recipe,"fake")
    for number in range(70):
        text=f"moonstep{number:03d} means a fictional pause in this synthetic community."
        project.add_source(parse_document(text.encode(),"text/plain",f"synthetic-{number}.txt",
            {"language":"en","community":"Gaming","domain":"browser-fixture","constraints":{"content_origin":"synthetic_fixture"}}))
    state=Engine(project,Provider(),clock=Clock(),random=lambda:0).run()
    assert state["degraded"] and state["counts"]["records"]==70
    print(json.dumps({"seed":str(path.resolve()),"status":state["status"],"records":70,"synthetic_only":True,"paid_requests":0}))
