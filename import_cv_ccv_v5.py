#!/usr/bin/env python3
import csv
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime

ORG = "xxxxxx"

CV_CSV = "content_views_full.csv"
CV_REPO_CSV = "content_view_repositories.csv"
CCV_COMPONENTS_CSV = "ccv_components.csv"

REPORT_CSV = f"import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
LOG_FILE = f"import_all_cv_ccv_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_cmd(cmd, check=False, capture=True):
    log(f"CMD: {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=capture,
    )
    if capture:
        if result.stdout:
            log(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr:
            log(f"STDERR:\n{result.stderr.strip()}")
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed rc={result.returncode}: {' '.join(cmd)}\n{result.stderr}"
        )
    return result


def hammer_csv(command_args):
    cmd = ["hammer", "--csv"] + command_args
    result = run_cmd(cmd, check=False, capture=True)
    if result.returncode != 0:
        return []
    content = result.stdout.strip()
    if not content:
        return []
    reader = csv.DictReader(content.splitlines())
    return list(reader)


def hammer_text(command_args):
    cmd = ["hammer"] + command_args
    result = run_cmd(cmd, check=False, capture=True)
    if result.returncode != 0:
        return ""
    return result.stdout


def ensure_files():
    for path in (CV_CSV, CV_REPO_CSV, CCV_COMPONENTS_CSV):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing required file: {path}")


def normalize(value):
    if value is None:
        return ""
    return str(value).strip()


def pick(row, *keys):
    for key in keys:
        if key in row and row[key] is not None:
            return normalize(row[key])
    return ""


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_all_content_views():
    rows = hammer_csv(["content-view", "list", "--organization", ORG])
    out = []
    for row in rows:
        cv_id = pick(row, "Content View ID", "Id", "ID")
        name = pick(row, "Name", "name")
        label = pick(row, "Label", "label")
        composite = pick(row, "Composite", "composite").lower()
        out.append(
            {
                "id": cv_id,
                "name": name,
                "label": label,
                "composite": composite,
            }
        )
    return out


def get_cv_id_by_name(cv_name):
    for row in get_all_content_views():
        if row["name"] == cv_name:
            return row["id"]
    return ""


def get_cv_id_by_label(cv_label):
    for row in get_all_content_views():
        if row["label"] == cv_label:
            return row["id"]
    return ""


def get_repo_id_by_name(repo_name):
    rows = hammer_csv(
        [
            "repository",
            "list",
            "--organization",
            ORG,
            "--search",
            f'name="{repo_name}"',
        ]
    )
    for row in rows:
        repo_id = pick(row, "Repository ID", "Id", "ID")
        if repo_id:
            return repo_id
    return ""


def parse_cv_info_text(info_text):
    data = {
        "Id": "",
        "Name": "",
        "Label": "",
        "Composite": "",
        "Description": "",
    }
    for line in info_text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = left.strip()
        value = right.strip()
        if key in data and not data[key]:
            data[key] = value
    return data


def cv_has_repository(cv_id, repo_id):
    info = hammer_text(["content-view", "info", "--organization", ORG, "--id", cv_id])
    if not info:
        return False

    for line in info.splitlines():
        stripped = line.strip()
        if stripped.startswith("Id:"):
            current = stripped.replace("Id:", "", 1).strip()
            if current == repo_id:
                return True
        elif ") Id:" in stripped:
            current = stripped.split(") Id:", 1)[1].strip()
            if current == repo_id:
                return True
    return False


def ccv_has_component(ccv_id, component_name):
    rows = hammer_csv(
        [
            "content-view",
            "component",
            "list",
            "--organization",
            ORG,
            "--content-view-id",
            ccv_id,
        ]
    )
    for row in rows:
        name = pick(row, "Name", "Content View", "content_view_name")
        if name == component_name:
            return True
    return False


def write_report(rows):
    fieldnames = [
        "step",
        "object_type",
        "name",
        "label",
        "source_id",
        "target_id",
        "status",
        "message",
    ]
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def create_cv_objects(cv_rows, report_rows):
    log("========== STEP 1 - CREATE SIMPLE CV ==========")
    for row in cv_rows:
        cv_name = pick(row, "name", "Name")
        cv_label = pick(row, "label", "Label")
        cv_desc = pick(row, "description", "Description")
        cv_composite = pick(row, "composite", "Composite").lower()
        src_id = pick(row, "content_view_id", "cv_id", "Content View ID", "Id")

        if not cv_name:
            continue
        if cv_composite == "yes":
            continue

        existing_by_name = get_cv_id_by_name(cv_name)
        existing_by_label = get_cv_id_by_label(cv_label)

        if existing_by_name or existing_by_label:
            if existing_by_name and existing_by_label and existing_by_name == existing_by_label:
                msg = "Already exists with same name and label"
                log(f"CV OK EXISTS: {cv_name} ({existing_by_name})")
                report_rows.append({
                    "step": "create_cv",
                    "object_type": "CV",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_id,
                    "target_id": existing_by_name,
                    "status": "OK_EXISTS",
                    "message": msg,
                })
            else:
                msg = f"Conflict detected name_id={existing_by_name or 'none'} label_id={existing_by_label or 'none'}"
                log(f"CV CONFLICT: {cv_name} / {cv_label}")
                report_rows.append({
                    "step": "create_cv",
                    "object_type": "CV",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_id,
                    "target_id": "",
                    "status": "CONFLICT",
                    "message": msg,
                })
            continue

        cmd = [
            "hammer",
            "content-view",
            "create",
            "--organization",
            ORG,
            "--name",
            cv_name,
            "--label",
            cv_label,
        ]
        if cv_desc:
            cmd += ["--description", cv_desc]

        result = run_cmd(cmd, check=False, capture=True)
        target_id = get_cv_id_by_name(cv_name)

        if result.returncode == 0 and target_id:
            report_rows.append({
                "step": "create_cv",
                "object_type": "CV",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_id,
                "target_id": target_id,
                "status": "CREATED",
                "message": "CV created",
            })
        else:
            report_rows.append({
                "step": "create_cv",
                "object_type": "CV",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_id,
                "target_id": "",
                "status": "ERROR",
                "message": f"Failed to create CV rc={result.returncode}",
            })


def attach_repositories(cv_repo_rows, report_rows):
    log("========== STEP 2 - ATTACH REPOSITORIES TO CV ==========")
    for row in cv_repo_rows:
        cv_name = pick(row, "content_view_name", "cv_name", "name")
        cv_label = pick(row, "content_view_label", "cv_label", "label")
        repo_name = pick(row, "repository_name", "repo_name", "name")
        src_cv_id = pick(row, "content_view_id", "cv_id")
        src_repo_id = pick(row, "repository_id", "repo_id")

        if not cv_name or not repo_name:
            continue

        target_cv_id = get_cv_id_by_name(cv_name)
        if not target_cv_id:
            report_rows.append({
                "step": "attach_repo",
                "object_type": "CV_REPOSITORY",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_cv_id,
                "target_id": "",
                "status": "ERROR",
                "message": f"Target CV not found: {cv_name}",
            })
            continue

        target_repo_id = get_repo_id_by_name(repo_name)
        if not target_repo_id:
            report_rows.append({
                "step": "attach_repo",
                "object_type": "CV_REPOSITORY",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_repo_id,
                "target_id": target_cv_id,
                "status": "ERROR",
                "message": f"Target repository not found by name: {repo_name}",
            })
            continue

        if cv_has_repository(target_cv_id, target_repo_id):
            report_rows.append({
                "step": "attach_repo",
                "object_type": "CV_REPOSITORY",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_repo_id,
                "target_id": target_repo_id,
                "status": "OK_EXISTS",
                "message": f"Repository already attached: {repo_name}",
            })
            continue

        cmd = [
            "hammer",
            "content-view",
            "add-repository",
            "--organization",
            ORG,
            "--id",
            target_cv_id,
            "--repository-id",
            target_repo_id,
        ]
        result = run_cmd(cmd, check=False, capture=True)

        if result.returncode == 0:
            report_rows.append({
                "step": "attach_repo",
                "object_type": "CV_REPOSITORY",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_repo_id,
                "target_id": target_repo_id,
                "status": "ATTACHED",
                "message": f"Repository attached: {repo_name}",
            })
        else:
            report_rows.append({
                "step": "attach_repo",
                "object_type": "CV_REPOSITORY",
                "name": cv_name,
                "label": cv_label,
                "source_id": src_repo_id,
                "target_id": target_repo_id,
                "status": "ERROR",
                "message": f"Failed to attach repository: {repo_name}",
            })


def create_ccv_objects(cv_rows, report_rows):
    log("========== STEP 3 - CREATE CCV ==========")
    for row in cv_rows:
        ccv_name = pick(row, "name", "Name")
        ccv_label = pick(row, "label", "Label")
        ccv_desc = pick(row, "description", "Description")
        composite = pick(row, "composite", "Composite").lower()
        src_id = pick(row, "content_view_id", "cv_id", "Content View ID", "Id")

        if not ccv_name:
            continue
        if composite != "yes":
            continue

        existing_by_name = get_cv_id_by_name(ccv_name)
        existing_by_label = get_cv_id_by_label(ccv_label)

        if existing_by_name or existing_by_label:
            if existing_by_name and existing_by_label and existing_by_name == existing_by_label:
                msg = "Already exists with same name and label"
                log(f"CCV OK EXISTS: {ccv_name} ({existing_by_name})")
                report_rows.append({
                    "step": "create_ccv",
                    "object_type": "CCV",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": src_id,
                    "target_id": existing_by_name,
                    "status": "OK_EXISTS",
                    "message": msg,
                })
            else:
                msg = f"Conflict detected name_id={existing_by_name or 'none'} label_id={existing_by_label or 'none'}"
                log(f"CCV CONFLICT: {ccv_name} / {ccv_label}")
                report_rows.append({
                    "step": "create_ccv",
                    "object_type": "CCV",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": src_id,
                    "target_id": "",
                    "status": "CONFLICT",
                    "message": msg,
                })
            continue

        cmd = [
            "hammer",
            "content-view",
            "create",
            "--organization",
            ORG,
            "--name",
            ccv_name,
            "--label",
            ccv_label,
            "--composite",
        ]
        if ccv_desc:
            cmd += ["--description", ccv_desc]

        result = run_cmd(cmd, check=False, capture=True)
        target_id = get_cv_id_by_name(ccv_name)

        if result.returncode == 0 and target_id:
            report_rows.append({
                "step": "create_ccv",
                "object_type": "CCV",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": src_id,
                "target_id": target_id,
                "status": "CREATED",
                "message": "CCV created",
            })
        else:
            report_rows.append({
                "step": "create_ccv",
                "object_type": "CCV",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": src_id,
                "target_id": "",
                "status": "ERROR",
                "message": f"Failed to create CCV rc={result.returncode}",
            })


def attach_ccv_components(ccv_component_rows, report_rows):
    log("========== STEP 4 - ATTACH COMPONENTS TO CCV ==========")
    for row in ccv_component_rows:
        ccv_name = pick(row, "ccv_name", "name")
        ccv_label = pick(row, "ccv_label", "label")
        component_name = pick(row, "component_cv_name", "component_name")

        if not ccv_name or not component_name:
            continue

        target_ccv_id = get_cv_id_by_name(ccv_name)
        if not target_ccv_id:
            report_rows.append({
                "step": "attach_component",
                "object_type": "CCV_COMPONENT",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": "",
                "target_id": "",
                "status": "ERROR",
                "message": f"Target CCV not found: {ccv_name}",
            })
            continue

        component_id = get_cv_id_by_name(component_name)
        if not component_id:
            report_rows.append({
                "step": "attach_component",
                "object_type": "CCV_COMPONENT",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": "",
                "target_id": target_ccv_id,
                "status": "ERROR",
                "message": f"Component CV not found: {component_name}",
            })
            continue

        if ccv_has_component(target_ccv_id, component_name):
            report_rows.append({
                "step": "attach_component",
                "object_type": "CCV_COMPONENT",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": component_id,
                "target_id": target_ccv_id,
                "status": "OK_EXISTS",
                "message": f"Component already attached: {component_name}",
            })
            continue

        cmd = [
            "hammer",
            "content-view",
            "component",
            "add",
            "--organization",
            ORG,
            "--composite-content-view-id",
            target_ccv_id,
            "--content-view-id",
            component_id,
            "--latest",
        ]
        result = run_cmd(cmd, check=False, capture=True)

        if result.returncode == 0:
            report_rows.append({
                "step": "attach_component",
                "object_type": "CCV_COMPONENT",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": component_id,
                "target_id": target_ccv_id,
                "status": "ATTACHED",
                "message": f"Component attached: {component_name}",
            })
        else:
            report_rows.append({
                "step": "attach_component",
                "object_type": "CCV_COMPONENT",
                "name": ccv_name,
                "label": ccv_label,
                "source_id": component_id,
                "target_id": target_ccv_id,
                "status": "ERROR",
                "message": f"Failed to attach component: {component_name}",
            })


def main():
    ensure_files()

    cv_rows = load_csv(CV_CSV)
    cv_repo_rows = load_csv(CV_REPO_CSV)
    ccv_component_rows = load_csv(CCV_COMPONENTS_CSV)

    report_rows = []

    create_cv_objects(cv_rows, report_rows)
    attach_repositories(cv_repo_rows, report_rows)
    create_ccv_objects(cv_rows, report_rows)
    attach_ccv_components(ccv_component_rows, report_rows)

    write_report(report_rows)

    log("==============================================================")
    log(f"Import finished at : {datetime.now()}")
    log(f"Report CSV         : {REPORT_CSV}")
    log(f"Log file           : {LOG_FILE}")
    log("==============================================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FATAL: {exc}")
        sys.exit(1)