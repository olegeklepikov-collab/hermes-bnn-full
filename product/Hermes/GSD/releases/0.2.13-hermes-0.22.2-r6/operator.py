#!/usr/bin/env python3
"""Owner commands are deliberately absent from Hermes model tools."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bn_gsd.bridge import Bridge


def main():
    p = argparse.ArgumentParser(description="Доверенное управление GSD Hermes BN")
    p.add_argument("--settings", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status"); status.add_argument("--sid", required=True)
    sub.add_parser("recover")
    resume = sub.add_parser("resume"); resume.add_argument("--family", required=True); resume.add_argument("--reason", required=True)
    attach = sub.add_parser("attach-case"); attach.add_argument("--sid", required=True); attach.add_argument("--run-id", required=True)
    grant = sub.add_parser("grant-artifact")
    grant.add_argument("--sid", required=True); grant.add_argument("--name", required=True)
    grant.add_argument("--content-file", required=True); grant.add_argument("--ttl", type=int, default=300)
    grant.add_argument("--reason", required=True)
    revoke = sub.add_parser("revoke-grant"); revoke.add_argument("--grant-id", required=True); revoke.add_argument("--reason", required=True)
    commit = sub.add_parser("commit-procedure")
    for name in ["job-id", "run-id", "payload-file", "request-id", "review-reason"]:
        commit.add_argument("--" + name, required=True)
    change = sub.add_parser("case-change")
    for name in ["sid", "run-id", "payload-file", "request-id"]: change.add_argument("--" + name, required=True)
    change.add_argument("--operation", choices=["accept_limited", "close", "stop", "insert_repair", "refresh"], required=True)
    change.add_argument("--store-revision", type=int, required=True)
    resume_case = sub.add_parser("resume-case")
    for name in ["sid", "run-id", "reason"]: resume_case.add_argument("--" + name, required=True)
    resume_case.add_argument("--store-revision", type=int, required=True)
    new_run = sub.add_parser("new-run")
    new_run.add_argument("--sid", required=True); new_run.add_argument("--input-file", required=True)
    grant_tool=sub.add_parser("grant-tool")
    for n in ["sid","name","arguments-file","reason"]:grant_tool.add_argument("--"+n,required=True)
    grant_tool.add_argument("--ttl",type=int,default=300)
    migrate=sub.add_parser("migrate-state");migrate.add_argument("--backup-path",required=True);migrate.add_argument("--apply",action="store_true")
    external=sub.add_parser("commit-external-procedure")
    for n in ["job-id","run-id","payload-file","request-id","review-reason"]:external.add_argument("--"+n,required=True)
    a = p.parse_args()
    bridge = Bridge(a.settings)
    if a.command=="grant-tool":
        result=bridge.call("issue_tool_grant",{"sid":a.sid,"name":a.name,"arguments":json.loads(Path(a.arguments_file).read_text()),"ttl":a.ttl,"reason":a.reason})
    elif a.command=="migrate-state":
        result=bridge.call("operator_migrate",{"backup_path":a.backup_path,"apply":a.apply})
    elif a.command=="commit-external-procedure":
        result=bridge.call("operator_external_commit",{"job_id":a.job_id,"run_id":a.run_id,"payload":json.loads(Path(a.payload_file).read_text()),"request_id":a.request_id,"review_reason":a.review_reason})
    elif a.command == "status":
        result = bridge.call("family_status", {"sid": a.sid})
    elif a.command == "recover":
        result = bridge.call("recover_dead")
    elif a.command == "resume":
        result = bridge.call("operator_resume", {"family_id": a.family, "reason": a.reason})
    elif a.command == "attach-case":
        result = bridge.call("operator_attach", {"sid": a.sid, "run_id": a.run_id})
    elif a.command == "grant-artifact":
        result = bridge.call("issue_grant", {"sid": a.sid, "arguments": {
            "name": a.name, "content": Path(a.content_file).read_text()}, "ttl": a.ttl, "reason": a.reason})
    elif a.command == "revoke-grant":
        result = bridge.call("revoke_grant", {"grant_id": a.grant_id, "reason": a.reason})
    elif a.command == "case-change":
        result = bridge.call("operator_case_change", {"sid": a.sid, "run_id": a.run_id,
            "operation": a.operation, "expected_store_revision": a.store_revision, "request_id": a.request_id,
            "payload": json.loads(Path(a.payload_file).read_text())})
    elif a.command == "resume-case":
        result = bridge.call("operator_case_resume", {"sid": a.sid, "run_id": a.run_id,
            "expected_store_revision": a.store_revision, "reason": a.reason})
    elif a.command == "new-run":
        result = bridge.call("operator_new_run", {"sid": a.sid, "arguments": json.loads(Path(a.input_file).read_text())})
    else:
        result = bridge.call("operator_commit", {"job_id": a.job_id, "run_id": a.run_id,
            "payload": json.loads(Path(a.payload_file).read_text()), "request_id": a.request_id,
            "review_reason": a.review_reason})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
