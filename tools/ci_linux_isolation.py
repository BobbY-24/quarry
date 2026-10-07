"""CI-only Ubuntu bubblewrap prerequisite diagnostics and additive provisioning.

Run with ``env -i`` and Python ``-I -S`` on a disposable hosted runner. This
helper executes only fixed system commands, never Quarry or supplied code.
The workflow installs official Ubuntu packages separately. No sysctl changes,
host-network fallback, or existing AppArmor profile replacement are supported.

Reviewed ABI-4.0 profile, identical in Ubuntu noble 24.04.9 and upstream v4.0.1:
https://gitlab.com/apparmor/apparmor/-/raw/v4.0.1/profiles/apparmor/profiles/extras/bwrap-userns-restrict
Ubuntu explains setup capabilities and the capability-denying child profile:
https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007
Bubblewrap retains setup capabilities until construction finishes:
https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import tempfile

PROFILE_PATH = Path("/usr/share/apparmor/extra-profiles/bwrap-userns-restrict")
PROFILE_SHA256 = "11d39094f044f0cda0febb3ad517b830301da6b2ce929664af09ee9e4dd264f9"
LOADED_PROFILES = Path("/sys/kernel/security/apparmor/profiles")
LOCAL_INCLUDES = (Path("/etc/apparmor.d/local/bwrap-userns-restrict"),
                  Path("/etc/apparmor.d/local/unpriv_bwrap"))
PARSER = "/usr/sbin/apparmor_parser"
OUTPUT_LIMIT = 65_536
READ_LIMIT = 1_048_576


def _run_trusted(command, *, timeout=15):
    """Private, bounded command output is parsed locally and never echoed."""
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_FSIZE, (READ_LIMIT, READ_LIMIT))
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                close_fds=True, start_new_session=True, preexec_fn=limits)
        except OSError:
            return {"exit_code": None, "timed_out": False, "output_bounded": True,
                    "output": "", "launch_failed": True}
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=2)
        output.seek(0)
        data = output.read(OUTPUT_LIMIT + 1)
    return {"exit_code": process.returncode, "timed_out": timed_out,
            "output_bounded": len(data) <= OUTPUT_LIMIT, "launch_failed": False,
            "output": data[:OUTPUT_LIMIT].decode("utf-8", errors="replace")}


def _metadata(result):
    return {key: result[key] for key in ("exit_code", "timed_out", "output_bounded", "launch_failed")}


def _read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > READ_LIMIT:
            raise ValueError("bounded regular file required")
        data = bytearray()
        while len(data) <= READ_LIMIT:
            chunk = os.read(fd, min(65_536, READ_LIMIT + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise ValueError("file exceeds bound")
    finally:
        os.close(fd)


def preflight():
    # Only distro /usr/bin/true runs. No application, project, home or generated
    # code is mounted; setup and application capability policy remain distinct.
    command = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
               "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev"]
    for path in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(path).exists():
            command.extend(["--ro-bind", path, path])
    command.append("/usr/bin/true")
    result = _run_trusted(command)
    text = result["output"].lower()
    if result["timed_out"]:
        category = "preflight_timeout"
    elif result["launch_failed"]:
        category = "preflight_launcher_unavailable"
    elif "loopback:" in text and ("rtm_newaddr" in text or "rtm_newlink" in text):
        category = "private_loopback_setup_failed"
    elif "bwrap:" in text and ("namespace" in text or "unshare" in text):
        category = "namespace_setup_failed"
    elif result["exit_code"] == 0 and result["output_bounded"]:
        category = "preflight_succeeded"
    else:
        category = "other_preflight_failure"
    return {**_metadata(result), "category": category}


def kernel_diagnostic():
    # Do not persist raw kernel lines, process identifiers, paths or addresses.
    result = _run_trusted(["/usr/bin/sudo", "-n", "/usr/bin/journalctl", "--kernel",
                           "--since", "5 minutes ago", "--no-pager", "--output=cat"], timeout=10)
    counts = {}
    for line in result["output"].splitlines():
        lower = line.lower()
        if 'apparmor="denied"' not in lower or 'comm="bwrap"' not in lower:
            continue
        if 'capname="net_admin"' in lower:
            category = "bwrap_cap_net_admin_denied"
        elif 'capname="sys_admin"' in lower:
            category = "bwrap_cap_sys_admin_denied"
        elif "userns" in lower and 'operation="userns_create"' in lower:
            category = "bwrap_user_namespace_denied"
        else:
            category = "bwrap_other_apparmor_denial"
        counts[category] = counts.get(category, 0) + 1
    return {**_metadata(result), "categories": counts,
            "audit_available": result["exit_code"] == 0 and result["output_bounded"]
                               and not result["timed_out"] and not result["launch_failed"]}


def _policy_states():
    # The kernel exposes public policy names only, not profile source contents.
    result = _run_trusted(["/usr/bin/sudo", "-n", "/usr/bin/cat", str(LOADED_PROFILES)], timeout=10)
    if result["exit_code"] != 0 or result["timed_out"] or not result["output_bounded"] or result["launch_failed"]:
        raise ValueError("loaded policy inventory unavailable")
    states = {}
    for line in result["output"].splitlines():
        name, separator, mode = line.rpartition(" (")
        if separator and mode.endswith(")"):
            states[name] = mode[:-1]
    return states


def provision():
    """Hash-bound package policy, ADD only; every unresolved outcome fails."""
    try:
        source = _read_regular(PROFILE_PATH)
    except (OSError, ValueError):
        return {"status": "blocked", "category": "reviewed_distro_profile_unavailable"}
    if hashlib.sha256(source).hexdigest() != PROFILE_SHA256:
        return {"status": "blocked", "category": "reviewed_distro_profile_hash_mismatch"}
    if any(path.exists() or path.is_symlink() for path in LOCAL_INCLUDES):
        return {"status": "blocked", "category": "unreviewed_local_profile_include"}
    try:
        names = _policy_states()
    except (OSError, ValueError, UnicodeError):
        return {"status": "blocked", "category": "loaded_policy_inventory_unavailable"}
    if any("bwrap" in name for name in names):
        return {"status": "blocked", "category": "existing_bwrap_policy_preserved"}
    # --add refuses name conflicts; never --replace, aa-disable, sysctl or a
    # write to /etc/apparmor.d. Package content is the sole policy input.
    result = _run_trusted(["/usr/bin/sudo", "-n", PARSER, "--add", str(PROFILE_PATH)], timeout=20)
    receipt = {**_metadata(result), "profile_sha256": PROFILE_SHA256,
               "policy_operation": "add_only"}
    if result["timed_out"] or not result["output_bounded"]:
        return {**receipt, "status": "uncertain", "category": "policy_load_outcome_unresolved"}
    if result["exit_code"] != 0 or result["launch_failed"]:
        return {**receipt, "status": "blocked", "category": "additive_policy_load_failed"}
    try:
        names = _policy_states()
    except (OSError, ValueError, UnicodeError):
        return {**receipt, "status": "uncertain", "category": "loaded_policy_verification_unavailable"}
    if any(names.get(name) != "enforce" for name in ("bwrap", "unpriv_bwrap")):
        return {**receipt, "status": "uncertain", "category": "loaded_policy_verification_failed"}
    return {**receipt, "status": "loaded", "category": "reviewed_distro_policy_added"}


def _write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".isolation-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush(); os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("diagnose", "provision"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--hosted-runner", action="store_true",
                        help="Operator declaration: this is a disposable hosted CI runner")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    destination = args.report.resolve()
    if not destination.is_relative_to(root / "verification" / "ci"):
        parser.error("Reports must stay inside repository verification/ci/")
    report = {"schema_version": 1, "command": args.command, "raw_diagnostics_exported": False,
              "credential_environment": "empty_for_system_commands", "stages": []}
    if not sys.platform.startswith("linux"):
        report["status"] = "unsupported_platform"
        _write_report(destination, report)
        return 2
    hosted = args.hosted_runner or (os.environ.get("GITHUB_ACTIONS") == "true"
                                   and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted")
    if args.command == "provision" and not hosted:
        report["status"] = "hosted_runner_declaration_required"
        _write_report(destination, report)
        return 2
    report["stages"].append({"stage": "preflight", **preflight()})
    report["stages"].append({"stage": "kernel_diagnostic", **kernel_diagnostic()})
    _write_report(destination, report)
    if args.command == "diagnose":
        report["status"] = "diagnosed"
        _write_report(destination, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    # Persist admission before the privileged effect, so an interrupted helper
    # does not falsely report that policy was never submitted.
    report["status"] = "policy_load_pending"
    _write_report(destination, report)
    receipt = provision()
    report["stages"].append({"stage": "provision", **receipt})
    report["status"] = receipt["status"]
    if receipt["status"] == "loaded":
        postflight = preflight()
        report["stages"].append({"stage": "postflight", **postflight})
        if postflight["category"] != "preflight_succeeded":
            report["status"] = "postflight_failed"
    _write_report(destination, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "loaded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
