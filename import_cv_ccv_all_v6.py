#!/usr/bin/env python3
import csv
import os
import shlex
import subprocess
import sys
from datetime import datetime

ORG = ""

CV_CSV = "content_views_full.csv"
CV_REPO_CSV = "content_view_repositories.csv"
CCV_COMPONENTS_CSV = "ccv_components.csv"

REPORT_CSV = f"import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
LOG_FILE = f"import_all_cv_ccv_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_cmd(cmd, check=False):
    log(f"CMD: {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(cmd, text=True, capture_output=True)

    if result.stdout and result.stdout.strip():
        log(f"STDOUT:\n{result.stdout.strip()}")
    if result.stderr and result.stderr.strip():
        log(f"STDERR:\n{result.stderr.strip()}")

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed rc={result.returncode}: {' '.join(cmd)}"
        )
    return result


def hammer_csv(args):
    result = run_cmd(["hammer", "--csv"] + args, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return list(csv.DictReader(result.stdout.splitlines()))


def pick(row, *keys):
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return ""


def ensure_files():
    for path in (CV_CSV, CV_REPO_CSV, CCV_COMPONENTS_CSV):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing required file: {path}")


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_all_content_views():
    rows = hammer_csv(["content-view", "list", "--organization", ORG])
    out = []
    for row in rows:
        out.append(
            {
                "id": pick(row, "Content View ID", "Id", "ID"),
                "name": pick(row, "Name"),
                "label": pick(row, "Label"),
                "composite": pick(row, "Composite").lower(),
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


def get_repo_candidates_by_name(repo_name):
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
    candidates = []
    for row in rows:
        candidates.append(
            {
                "id": pick(row, "Repository ID", "Id", "ID"),
                "name": pick(row, "Name"),
                "label": pick(row, "Label"),
                "product": pick(row, "Product"),
            }
        )
    return candidates


def get_repo_id_by_name(repo_name):
    candidates = get_repo_candidates_by_name(repo_name)
    for c in candidates:
        if c["id"]:
            return c["id"]
    return ""


def cv_has_repository(cv_id, repo_id):
    result = run_cmd(
        ["hammer", "content-view", "info", "--organization", ORG, "--id", cv_id],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Id:"):
            val = stripped.split("Id:", 1)[1].strip()
            if val == repo_id:
                return True
        elif ") Id:" in stripped:
            val = stripped.split(") Id:", 1)[1].strip()
            if val == repo_id:
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
            "--composite-content-view-id",
            ccv_id,
        ]
    )
    for row in rows:
        name = pick(row, "Name", "Content View")
        if name == component_name:
            return True
    return False


def create_content_view(name, label, description="", composite=False):
    cmd = [
        "hammer",
        "content-view",
        "create",
        "--organization",
        ORG,
        "--name",
        name,
        "--label",
        label,
    ]
    if description:
        cmd += ["--description", description]
    if composite:
        cmd += ["--composite"]

    return run_cmd(cmd, check=False)


def attach_repository_to_cv(cv_id, repo_id):
    cmd = [
        "hammer",
        "content-view",
        "add-repository",
        "--organization",
        ORG,
        "--id",
        cv_id,
        "--repository-id",
        repo_id,
    ]
    return run_cmd(cmd, check=False)


def attach_component_to_ccv(ccv_id, component_cv_id):
    cmd = [
        "hammer",
        "content-view",
        "component",
        "add",
        "--organization",
        ORG,
        "--composite-content-view-id",
        ccv_id,
        "--component-content-view-id",
        component_cv_id,
        "--latest",
    ]
    return run_cmd(cmd, check=False)


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


def create_simple_cvs(cv_rows, report_rows):
    log("========== STEP 1 - CREATE SIMPLE CV ==========")

    for row in cv_rows:
        src_id = pick(row, "content_view_id")
        cv_name = pick(row, "name")
        cv_label = pick(row, "label")
        composite = pick(row, "composite").lower()
        description = pick(row, "description")

        if not cv_name:
            continue
        if composite == "yes":
            continue

        existing_by_name = get_cv_id_by_name(cv_name)
        existing_by_label = get_cv_id_by_label(cv_label)

        if existing_by_name or existing_by_label:
            if existing_by_name and existing_by_label and existing_by_name == existing_by_label:
                report_rows.append(
                    {
                        "step": "create_cv",
                        "object_type": "CV",
                        "name": cv_name,
                        "label": cv_label,
                        "source_id": src_id,
                        "target_id": existing_by_name,
                        "status": "OK_EXISTS",
                        "message": "CV already exists with same name and label",
                    }
                )
            else:
                report_rows.append(
                    {
                        "step": "create_cv",
                        "object_type": "CV",
                        "name": cv_name,
                        "label": cv_label,
                        "source_id": src_id,
                        "target_id": "",
                        "status": "CONFLICT",
                        "message": f"name_id={existing_by_name or 'none'} label_id={existing_by_label or 'none'}",
                    }
                )
            continue

        result = create_content_view(
            name=cv_name,
            label=cv_label,
            description=description,
            composite=False,
        )
        new_id = get_cv_id_by_name(cv_name)

        if result.returncode == 0 and new_id:
            report_rows.append(
                {
                    "step": "create_cv",
                    "object_type": "CV",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_id,
                    "target_id": new_id,
                    "status": "CREATED",
                    "message": "CV created",
                }
            )
        else:
            report_rows.append(
                {
                    "step": "create_cv",
                    "object_type": "CV",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_id,
                    "target_id": "",
                    "status": "ERROR",
                    "message": f"Failed to create CV rc={result.returncode}",
                }
            )


def attach_repositories(cv_repo_rows, report_rows):
    log("========== STEP 2 - ATTACH REPOSITORIES ==========")

    for row in cv_repo_rows:
        src_cv_id = pick(row, "content_view_id")
        src_repo_id = pick(row, "repository_id")
        cv_name = pick(row, "content_view_name")
        cv_label = pick(row, "content_view_label")
        repo_name = pick(row, "repository_name")

        if not cv_name or not repo_name:
            continue

        target_cv_id = get_cv_id_by_name(cv_name)
        if not target_cv_id:
            report_rows.append(
                {
                    "step": "attach_repo",
                    "object_type": "CV_REPOSITORY",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_repo_id,
                    "target_id": "",
                    "status": "ERROR",
                    "message": f"Target CV not found: {cv_name}",
                }
            )
            continue

        repo_candidates = get_repo_candidates_by_name(repo_name)
        if not repo_candidates:
            report_rows.append(
                {
                    "step": "attach_repo",
                    "object_type": "CV_REPOSITORY",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_repo_id,
                    "target_id": target_cv_id,
                    "status": "ERROR",
                    "message": f"Target repository not found by name: {repo_name}",
                }
            )
            continue

        if len(repo_candidates) > 1:
            chosen_repo_id = repo_candidates[0]["id"]
            msg = (
                f"Multiple repositories found by name '{repo_name}', "
                f"using first id={chosen_repo_id}"
            )
            log(f"WARN: {msg}")
        else:
            chosen_repo_id = repo_candidates[0]["id"]
            msg = f"Repository matched by name: {repo_name}"

        if not chosen_repo_id:
            report_rows.append(
                {
                    "step": "attach_repo",
                    "object_type": "CV_REPOSITORY",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_repo_id,
                    "target_id": target_cv_id,
                    "status": "ERROR",
                    "message": f"No usable repository ID found for: {repo_name}",
                }
            )
            continue

        if cv_has_repository(target_cv_id, chosen_repo_id):
            report_rows.append(
                {
                    "step": "attach_repo",
                    "object_type": "CV_REPOSITORY",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_repo_id,
                    "target_id": chosen_repo_id,
                    "status": "OK_EXISTS",
                    "message": f"Repository already attached: {repo_name}",
                }
            )
            continue

        result = attach_repository_to_cv(target_cv_id, chosen_repo_id)
        if result.returncode == 0:
            report_rows.append(
                {
                    "step": "attach_repo",
                    "object_type": "CV_REPOSITORY",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_repo_id,
                    "target_id": chosen_repo_id,
                    "status": "ATTACHED",
                    "message": msg,
                }
            )
        else:
            report_rows.append(
                {
                    "step": "attach_repo",
                    "object_type": "CV_REPOSITORY",
                    "name": cv_name,
                    "label": cv_label,
                    "source_id": src_repo_id,
                    "target_id": chosen_repo_id,
                    "status": "ERROR",
                    "message": f"Failed to attach repository: {repo_name}",
                }
            )


def create_ccvs(cv_rows, report_rows):
    log("========== STEP 3 - CREATE CCV ==========")

    for row in cv_rows:
        src_id = pick(row, "content_view_id")
        ccv_name = pick(row, "name")
        ccv_label = pick(row, "label")
        composite = pick(row, "composite").lower()
        description = pick(row, "description")

        if not ccv_name:
            continue
        if composite != "yes":
            continue

        existing_by_name = get_cv_id_by_name(ccv_name)
        existing_by_label = get_cv_id_by_label(ccv_label)

        if existing_by_name or existing_by_label:
            if existing_by_name and existing_by_label and existing_by_name == existing_by_label:
                report_rows.append(
                    {
                        "step": "create_ccv",
                        "object_type": "CCV",
                        "name": ccv_name,
                        "label": ccv_label,
                        "source_id": src_id,
                        "target_id": existing_by_name,
                        "status": "OK_EXISTS",
                        "message": "CCV already exists with same name and label",
                    }
                )
            else:
                report_rows.append(
                    {
                        "step": "create_ccv",
                        "object_type": "CCV",
                        "name": ccv_name,
                        "label": ccv_label,
                        "source_id": src_id,
                        "target_id": "",
                        "status": "CONFLICT",
                        "message": f"name_id={existing_by_name or 'none'} label_id={existing_by_label or 'none'}",
                    }
                )
            continue

        result = create_content_view(
            name=ccv_name,
            label=ccv_label,
            description=description,
            composite=True,
        )
        new_id = get_cv_id_by_name(ccv_name)

        if result.returncode == 0 and new_id:
            report_rows.append(
                {
                    "step": "create_ccv",
                    "object_type": "CCV",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": src_id,
                    "target_id": new_id,
                    "status": "CREATED",
                    "message": "CCV created",
                }
            )
        else:
            report_rows.append(
                {
                    "step": "create_ccv",
                    "object_type": "CCV",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": src_id,
                    "target_id": "",
                    "status": "ERROR",
                    "message": f"Failed to create CCV rc={result.returncode}",
                }
            )


def attach_ccv_components(ccv_component_rows, report_rows):
    log("========== STEP 4 - ATTACH CCV COMPONENTS ==========")

    for row in ccv_component_rows:
        ccv_name = pick(row, "ccv_name")
        ccv_label = pick(row, "ccv_label")
        component_name = pick(row, "component_cv_name")

        if not ccv_name or not component_name:
            continue

        target_ccv_id = get_cv_id_by_name(ccv_name)
        if not target_ccv_id:
            report_rows.append(
                {
                    "step": "attach_component",
                    "object_type": "CCV_COMPONENT",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": "",
                    "target_id": "",
                    "status": "ERROR",
                    "message": f"Target CCV not found: {ccv_name}",
                }
            )
            continue

        component_id = get_cv_id_by_name(component_name)
        if not component_id:
            report_rows.append(
                {
                    "step": "attach_component",
                    "object_type": "CCV_COMPONENT",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": "",
                    "target_id": target_ccv_id,
                    "status": "ERROR",
                    "message": f"Component CV not found: {component_name}",
                }
            )
            continue

        if ccv_has_component(target_ccv_id, component_name):
            report_rows.append(
                {
                    "step": "attach_component",
                    "object_type": "CCV_COMPONENT",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": component_id,
                    "target_id": target_ccv_id,
                    "status": "OK_EXISTS",
                    "message": f"Component already attached: {component_name}",
                }
            )
            continue

        result = attach_component_to_ccv(target_ccv_id, component_id)
        if result.returncode == 0:
            report_rows.append(
                {
                    "step": "attach_component",
                    "object_type": "CCV_COMPONENT",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": component_id,
                    "target_id": target_ccv_id,
                    "status": "ATTACHED",
                    "message": f"Component attached: {component_name}",
                }
            )
        else:
            report_rows.append(
                {
                    "step": "attach_component",
                    "object_type": "CCV_COMPONENT",
                    "name": ccv_name,
                    "label": ccv_label,
                    "source_id": component_id,
                    "target_id": target_ccv_id,
                    "status": "ERROR",
                    "message": f"Failed to attach component: {component_name}",
                }
            )


def main():
    ensure_files()

    cv_rows = load_csv(CV_CSV)
    cv_repo_rows = load_csv(CV_REPO_CSV)
    ccv_component_rows = load_csv(CCV_COMPONENTS_CSV)

    report_rows = []

    create_simple_cvs(cv_rows, report_rows)
    attach_repositories(cv_repo_rows, report_rows)
    create_ccvs(cv_rows, report_rows)
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