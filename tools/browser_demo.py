"""Finite synthetic UI smoke setup; server exits when interrupted by tester."""
from importlib.resources import files
from pathlib import Path
import resource
import signal

from termfinder import Project, FakeProvider
from termfinder.config import starter_recipe
from termfinder.web import serve


if __name__=="__main__":
    # A finite test server; it never becomes an unattended persistent job.
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.alarm(300)
    root=Path(__file__).resolve().parents[1]
    project=Project(root/"verification"/"browser-project")
    project.configure(starter_recipe("cultural"),"fake")
    project.ingest([files("termfinder").joinpath("fixtures","cultural.md")],metadata={"language":"mul","community":"multilingual-community"})
    project.collect(FakeProvider())
    serve(project,port=8765,allow_paid=False)
