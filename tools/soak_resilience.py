"""Bounded synthetic multi-source outage/resume/export rehearsal, not a quality benchmark.

Run only with the reviewed offline launcher. It performs no network/API requests,
reads no credentials, and writes only a temporary project plus an explicit report.
"""
from collections import Counter
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import resource
import tempfile
import time

from quarry import Project, FakeProvider, Response
from quarry.config import starter_recipe
from quarry.engine import Engine
from quarry.providers import ProviderError
from quarry.sources import parse_document


class Clock:
    def __init__(self): self.value=time.time()
    def time(self): return self.value
    def monotonic(self): return self.value
    def sleep(self,delay): self.value+=delay


class Provider(FakeProvider):
    def __init__(self,clock):
        super().__init__([])
        self.clock,self.failures,self.events=clock,2,[]
    def complete(self,request):
        alias=request["expert"]["model"]
        self.calls.append(request["job_id"])
        self.events.append((alias,self.clock.time()))
        if alias=="glm" and self.failures:
            self.failures-=1
            raise ProviderError("synthetic_timeout",uncertain=True,retryable=True)
        proposals=[]
        context="This synthetic community calls a pause moonstep."
        if context in request["text"]:
            proposals=[{"expression":"moonstep","language":"en","sense":"a pause",
                        "context":context,"start":None,"attributes":{},"definition_quote":None,"translation":None}]
        return Response(json.dumps({"candidates":proposals,"coverage_complete":True}),200,100,"stop","synthetic-soak-v1")


def checksum(path):
    result=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1048576),b""): result.update(block)
    return result.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources",type=int,default=2500)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.sources<=10000: parser.error("Use 1–10000 synthetic sources per rehearsal")
    started=time.monotonic();timings={}
    with tempfile.TemporaryDirectory(prefix="v6-resilience-soak-") as root:
        project=Project(Path(root)/"study")
        recipe=starter_recipe("neologisms")
        recipe["execution"]["resilience"].update(min_request_interval_seconds=0,jitter_fraction=0)
        project.configure(recipe,"fake")
        phase=time.monotonic()
        for index in range(args.sources):
            text=f"Source number {index}. This synthetic community calls a pause moonstep.\n"+"Ordinary filler sentence. "*150
            project.add_source(parse_document(text.encode(),"text/plain",f"fixture-{index}.txt",
                {"language":"en","community":"Gaming","domain":"synthetic-soak","constraints":{"content_origin":"synthetic_fixture"}}))
        timings["ingest_seconds"]=time.monotonic()-phase
        clock=Clock();provider=Provider(clock);phase=time.monotonic()
        first=Engine(project,provider,clock=clock,random=lambda:0).run(max_jobs=min(200,args.sources))
        assert first["jobs"]["pending"]>0
        project=Project(project.path)
        final=Engine(project,provider,clock=clock,random=lambda:0).run()
        assert final["coverage"]["partial"]==0 and not final["degraded"]
        calls=len(provider.calls)
        Engine(project,provider,clock=clock,random=lambda:0).run()
        assert len(provider.calls)==calls
        timings["collect_resume_cache_seconds"]=time.monotonic()-phase
        phase=time.monotonic()
        estimate=project.estimate();page=project.page_inventory(record_id=project.page_inventory()["records"][0]["record_id"])
        page_bytes=len(json.dumps(page,ensure_ascii=False).encode())
        assert len(page["occurrences"])<=50 and all("text" not in s for s in page["sources"])
        timings["estimate_and_page_seconds"]=time.monotonic()-phase
        phase=time.monotonic();version=project.snapshot("synthetic-thousands-source-soak")
        formats=["csv","jsonl","parquet","annotation"]
        one,two=Path(root)/"export-one",Path(root)/"export-two"
        project.export(version,one,formats);project.export(version,two,list(reversed(formats)))
        files={p.name:checksum(p) for p in one.iterdir() if p.is_file()}
        assert files=={p.name:checksum(p) for p in two.iterdir() if p.is_file()}
        timings["snapshot_double_export_seconds"]=time.monotonic()-phase
        backup=Path(root)/"backup"/"project.sqlite3";project.store.backup(backup)
        assert Project(backup.parent).status()["counts"]==project.status()["counts"]
        result={"synthetic_only":True,"network_calls":0,"provider_billing_usd":0,
                "source_count":args.sources,"parsed_characters":sum(len(s["text"]) for s in project.store.iter_rows("sources",batch_size=1)),
                "initial_interruption":first["stop_reason"],"final_coverage":final["coverage"],
                "coverage_by_model":final["last_run"]["coverage_by_model"],
                "attempts_by_model":dict(Counter(alias for alias,_ in provider.events)),
                "unknown_attempts":project.store.count("costs",where="json_extract(data,'$.status')='uncertain'"),
                "resume_extra_calls_after_completion":len(provider.calls)-calls,
                "browser_page_bytes":page_bytes,"export_files":len(files),"exports_byte_identical":True,
                "database_bytes":project.store.path.stat().st_size,"backup_restore_counts_match":True,
                "estimate_calls":estimate["scenarios"][0]["estimated_calls"],"timings":timings,
                "total_seconds":time.monotonic()-started,"peak_rss_platform_units":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_units":"bytes on macOS, KiB on Linux",
                "limits":"Synthetic transport does not measure real API latency, throughput, quotas, DNS, or quality."}
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
        print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__": main()
