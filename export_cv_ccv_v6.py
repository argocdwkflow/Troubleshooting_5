#!/usr/bin/env python3
import csv
import os
import shlex
import subprocess
import sys
from datetime import datetime

ORG = ""

OUT_DIR = f"sat_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
RAW_DIR = os.path.join(OUT_DIR, "raw_content_views")

CV_CSV = os.path.join(OUT_DIR, "content_views_full.csv")
CV_REPO_CSV = os.path.join(OUT_DIR, "content_view_repositories.csv")
CCV_COMPONENTS_CSV = os.path.join(OUT_DIR, "ccv_components.csv")
LOG_FILE = os.path.join(OUT_DIR, "export.log")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_cmd(cmd, check=False):
    log(f"CMD: {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout.strip():
        log(f"STDOUT:\n{result.stdout.strip()}")
    if result.stderr.strip():
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


def hammer_text(args):
    result = run_cmd(["hammer"] + args, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout


def pick(row, *keys):
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return ""


def sanitize_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "unnamed"


def parse_simple_fields(info_text: str):
    data = {
        "Id": "",
        "Name": "",
        "Label": "",
        "Composite": "",
        "Description": "",
        "Content Host Count": "",
        "Solve Dependencies": "",
        "Organization": "",
        "Organisation": "",
    }
    for line in info_text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = left.strip()
        val = right.strip()
        if key in data and not data[key]:
            data[key] = val
    return data


def parse_repositories_from_cv_info(info_text: str):
    repos = []
    in_repos = False
    current = {}

    for raw_line in info_text.splitlines():
        line = raw_line.rstrip()

        if line.startswith("Yum Repositories:"):
            in_repos = True
            continue

        if in_repos and not line.startswith(" "):
            break

        if not in_repos:
            continue

        stripped = line.strip()
        if not stripped:
            continue

        if ") Id:" in stripped:
            if current.get("repository_id") and current.get("repository_name"):
                repos.append(current)
            current = {
                "repository_id": stripped.split(") Id:", 1)[1].strip(),
                "repository_name": "",
                "repository_label": "",
            }
        elif stripped.startswith("Id:"):
            if current.get("repository_id") and current.get("repository_name"):
                repos.append(current)
            current = {
                "repository_id": stripped.split("Id:", 1)[1].strip(),
                "repository_name": "",
                "repository_label": "",
            }
        elif stripped.startswith("Name:"):
            current["repository_name"] = stripped.split("Name:", 1)[1].strip()
        elif stripped.startswith("Label:"):
            current["repository_label"] = stripped.split("Label:", 1)[1].strip()
            if current.get("repository_id") and current.get("repository_name"):
                repos.append(current)
                current = {}

    if current.get("repository_id") and current.get("repository_name"):
        repos.append(current)

    return repos


def get_all_content_views():
    rows = hammer_csv(["content-view", "list", "--organization", ORG])
    out = []
    for row in rows:
        out.append(
            {
                "content_view_id": pick(row, "Content View ID", "Id", "ID"),
                "name": pick(row, "Name"),
                "label": pick(row, "Label"),
                "composite": pick(row, "Composite").lower(),
            }
        )
    return out


def get_ccv_components(cv_id):
    rows = hammer_csv(
        [
            "content-view",
            "component",
            "list",
            "--organization",
            ORG,
            "--composite-content-view-id",
            cv_id,
        ]
    )
    components = []
    for row in rows:
        comp_id = pick(row, "Content View ID", "Id", "ID")
        comp_name = pick(row, "Name", "Content View")
        if comp_id or comp_name:
            components.append(
                {
                    "component_cv_id": comp_id,
                    "component_cv_name": comp_name,
                }
            )
    return components


def main():
    os.makedirs(RAW_DIR, exist_ok=True)

    cv_rows = []
    cv_repo_rows = []
    ccv_component_rows = []

    content_views = get_all_content_views()
    if not content_views:
        log("No Content Views found.")
        return 1

    for cv in content_views:
        cv_id = cv["content_view_id"]
        cv_name = cv["name"]
        cv_label = cv["label"]
        composite = "yes" if cv["composite"] in ("yes", "true") else "no"

        if not cv_id or not cv_name:
            continue

        log(f"Processing CV: {cv_name} (ID={cv_id})")

        info_text = hammer_text(
            ["content-view", "info", "--organization", ORG, "--id", cv_id]
        )
        if not info_text:
            log(f"WARN: cannot read content-view info for {cv_name}")
            continue

        raw_file = os.path.join(RAW_DIR, f"{cv_id}_{sanitize_name(cv_name)}.txt")
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write(info_text)

        info = parse_simple_fields(info_text)
        org_value = info["Organization"] or info["Organisation"]

        cv_rows.append(
            {
                "content_view_id": cv_id,
                "name": info["Name"] or cv_name,
                "label": info["Label"] or cv_label,
                "composite": "yes" if (info["Composite"] or composite).lower() in ("yes", "true") else "no",
                "description": info["Description"],
                "content_host_count": info["Content Host Count"],
                "solve_dependencies": info["Solve Dependencies"],
                "organization": org_value or ORG,
            }
        )

        repos = parse_repositories_from_cv_info(info_text)
        for repo in repos:
            cv_repo_rows.append(
                {
                    "content_view_id": cv_id,
                    "content_view_name": info["Name"] or cv_name,
                    "content_view_label": info["Label"] or cv_label,
                    "repository_id": repo.get("repository_id", ""),
                    "repository_name": repo.get("repository_name", ""),
                    "repository_label": repo.get("repository_label", ""),
                }
            )

        if (info["Composite"] or composite).lower() in ("yes", "true"):
            components = get_ccv_components(cv_id)
            for comp in components:
                ccv_component_rows.append(
                    {
                        "ccv_name": info["Name"] or cv_name,
                        "ccv_label": info["Label"] or cv_label,
                        "component_cv_name": comp.get("component_cv_name", ""),
                    }
                )

    with open(CV_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "content_view_id",
                "name",
                "label",
                "composite",
                "description",
                "content_host_count",
                "solve_dependencies",
                "organization",
            ],
        )
        writer.writeheader()
        writer.writerows(cv_rows)

    with open(CV_REPO_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "content_view_id",
                "content_view_name",
                "content_view_label",
                "repository_id",
                "repository_name",
                "repository_label",
            ],
        )
        writer.writeheader()
        writer.writerows(cv_repo_rows)

    with open(CCV_COMPONENTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ccv_name",
                "ccv_label",
                "component_cv_name",
            ],
        )
        writer.writeheader()
        writer.writerows(ccv_component_rows)

    log("==============================================================")
    log("Export finished")
    log(f"Output dir            : {OUT_DIR}")
    log(f"content_views_full    : {CV_CSV}")
    log(f"content_view_repos    : {CV_REPO_CSV}")
    log(f"ccv_components        : {CCV_COMPONENTS_CSV}")
    log(f"raw files             : {RAW_DIR}")
    log("==============================================================")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {exc}")
        sys.exit(1)