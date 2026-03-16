#!/usr/bin/env python3
import csv
import os
import shlex
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

ORG = ""

AK_CSV = "activation_keys.csv"
AK_REPO_CSV = "activation_key_repository_sets.csv"

REPORT_CSV = f"ak_ui_import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
LOG_FILE = f"ak_ui_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_cmd(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
    log(f"CMD: {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout and result.stdout.strip():
        log(f"STDOUT:\n{result.stdout.strip()}")
    if result.stderr and result.stderr.strip():
        log(f"STDERR:\n{result.stderr.strip()}")
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed rc={result.returncode}: {' '.join(cmd)}")
    return result


def hammer_csv(args: List[str]) -> List[Dict[str, str]]:
    result = run_cmd(["hammer", "--csv"] + args, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return list(csv.DictReader(result.stdout.splitlines()))


def pick(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return ""


def load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def ensure_files() -> None:
    for path in (AK_CSV, AK_REPO_CSV):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing required file: {path}")


def normalize_bool(v: str) -> str:
    s = (v or "").strip().lower()
    if s in ("true", "yes", "1"):
        return "yes"
    if s in ("false", "no", "0"):
        return "no"
    return ""


def get_all_activation_keys() -> List[Dict[str, str]]:
    rows = hammer_csv(["activation-key", "list", "--organization", ORG])
    out = []
    for row in rows:
        out.append(
            {
                "id": pick(row, "Activation Key ID", "Id", "ID"),
                "name": pick(row, "Name", "name"),
            }
        )
    return out


def get_ak_id_by_name(ak_name: str) -> str:
    for row in get_all_activation_keys():
        if row["name"] == ak_name:
            return row["id"]
    return ""


def create_activation_key(row: Dict[str, str]) -> subprocess.CompletedProcess:
    name = pick(row, "name")
    description = pick(row, "description")
    unlimited_hosts = pick(row, "unlimited_hosts")
    max_hosts = pick(row, "max_hosts")

    cmd = [
        "hammer",
        "activation-key",
        "create",
        "--organization",
        ORG,
        "--name",
        name,
    ]

    if description:
        cmd += ["--description", description]

    if normalize_bool(unlimited_hosts) == "yes":
        cmd += ["--unlimited-hosts", "true"]
    elif max_hosts:
        cmd += ["--max-hosts", max_hosts]

    return run_cmd(cmd, check=False)


def update_activation_key(row: Dict[str, str]) -> subprocess.CompletedProcess:
    name = pick(row, "name")
    description = pick(row, "description")
    release_version = pick(row, "release_version")
    lifecycle_environment = pick(row, "lifecycle_environment")
    content_view = pick(row, "content_view")
    service_level = pick(row, "service_level")
    usage = pick(row, "usage")
    role = pick(row, "role")
    unlimited_hosts = pick(row, "unlimited_hosts")
    max_hosts = pick(row, "max_hosts")

    cmd = [
        "hammer",
        "activation-key",
        "update",
        "--organization",
        ORG,
        "--name",
        name,
    ]

    if description:
        cmd += ["--description", description]

    if content_view and lifecycle_environment:
        cmd += ["--content-view", content_view, "--lifecycle-environment", lifecycle_environment]

    if release_version:
        cmd += ["--release-version", release_version]

    if service_level:
        cmd += ["--service-level", service_level]

    if usage:
        cmd += ["--purpose-usage", usage]

    if role:
        cmd += ["--purpose-role", role]

    if normalize_bool(unlimited_hosts) == "yes":
        cmd += ["--unlimited-hosts", "true"]
    elif max_hosts:
        cmd += ["--max-hosts", max_hosts]

    return run_cmd(cmd, check=False)


def get_target_product_content_map(ak_name: str) -> Tuple[Dict[str, Dict[str, str]], Dict[Tuple[str, str], List[Dict[str, str]]], Dict[str, List[Dict[str, str]]]]:
    rows = hammer_csv(
        ["activation-key", "product-content", "--organization", ORG, "--name", ak_name]
    )

    by_label: Dict[str, Dict[str, str]] = {}
    by_name_product: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    by_name: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    for row in rows:
        entry = {
            "content_label": pick(row, "Content Label", "Content label", "Label", "content_label"),
            "repository_name": pick(row, "Name", "Repository Name", "Content Name", "name"),
            "product_name": pick(row, "Product", "Product Name", "product"),
            "repository_path": pick(row, "Repository Path", "Path", "Repository path"),
        }

        if entry["content_label"]:
            by_label[entry["content_label"]] = entry
        if entry["repository_name"]:
            by_name[entry["repository_name"]].append(entry)
        if entry["repository_name"] and entry["product_name"]:
            by_name_product[(entry["repository_name"], entry["product_name"])].append(entry)

    return by_label, by_name_product, by_name


def choose_target_label(exported_label: str, exported_repo_name: str, exported_product_name: str, by_label: Dict[str, Dict[str, str]], by_name_product: Dict[Tuple[str, str], List[Dict[str, str]]], by_name: Dict[str, List[Dict[str, str]]]) -> Tuple[str, str]:
    if exported_label and exported_label in by_label:
        return by_label[exported_label]["content_label"], "matched by content_label"

    if exported_repo_name and exported_product_name:
        matches = by_name_product.get((exported_repo_name, exported_product_name), [])
        if len(matches) == 1:
            return matches[0]["content_label"], "matched by repository_name + product_name"
        if len(matches) > 1:
            return matches[0]["content_label"], "multiple matches by repository_name + product_name, first used"

    if exported_repo_name:
        matches = by_name.get(exported_repo_name, [])
        if len(matches) == 1:
            return matches[0]["content_label"], "matched by repository_name"
        if len(matches) > 1:
            return matches[0]["content_label"], "multiple matches by repository_name, first used"

    return "", "no matching target content found"


def apply_override(ak_name: str, content_label: str, state: str) -> subprocess.CompletedProcess:
    value = "1" if state == "enabled" else "0"
    cmd = [
        "hammer",
        "activation-key",
        "content-override",
        "--organization",
        ORG,
        "--name",
        ak_name,
        "--content-label",
        content_label,
        "--value",
        value,
    ]
    return run_cmd(cmd, check=False)


def write_report(rows: List[Dict[str, str]]) -> None:
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "step",
                "activation_key_name",
                "status",
                "message",
                "target_id",
                "repository_name",
                "product_name",
                "content_label",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ensure_files()

    ak_rows = load_csv(AK_CSV)
    repo_rows = load_csv(AK_REPO_CSV)
    report: List[Dict[str, str]] = []

    # create / update AK
    for row in ak_rows:
        ak_name = pick(row, "name")
        if not ak_name:
            continue

        ak_id = get_ak_id_by_name(ak_name)
        if not ak_id:
            res = create_activation_key(row)
            ak_id = get_ak_id_by_name(ak_name)
            report.append(
                {
                    "step": "create_ak",
                    "activation_key_name": ak_name,
                    "status": "CREATED" if res.returncode == 0 and ak_id else "ERROR",
                    "message": "Activation key created" if res.returncode == 0 and ak_id else "Failed to create activation key",
                    "target_id": ak_id,
                    "repository_name": "",
                    "product_name": "",
                    "content_label": "",
                }
            )
            if not ak_id:
                continue
        else:
            report.append(
                {
                    "step": "create_ak",
                    "activation_key_name": ak_name,
                    "status": "OK_EXISTS",
                    "message": "Activation key already exists",
                    "target_id": ak_id,
                    "repository_name": "",
                    "product_name": "",
                    "content_label": "",
                }
            )

        upd = update_activation_key(row)
        report.append(
            {
                "step": "update_ak",
                "activation_key_name": ak_name,
                "status": "UPDATED" if upd.returncode == 0 else "ERROR",
                "message": "Activation key updated" if upd.returncode == 0 else "Failed to update activation key",
                "target_id": get_ak_id_by_name(ak_name),
                "repository_name": "",
                "product_name": "",
                "content_label": "",
            }
        )

    # apply repo overrides
    repo_rows_by_ak: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in repo_rows:
        ak_name = pick(row, "activation_key_name")
        if ak_name:
            repo_rows_by_ak[ak_name].append(row)

    for ak_name, rows in repo_rows_by_ak.items():
        ak_id = get_ak_id_by_name(ak_name)
        if not ak_id:
            report.append(
                {
                    "step": "repo_override",
                    "activation_key_name": ak_name,
                    "status": "ERROR",
                    "message": "Activation key not found on target",
                    "target_id": "",
                    "repository_name": "",
                    "product_name": "",
                    "content_label": "",
                }
            )
            continue

        by_label, by_name_product, by_name = get_target_product_content_map(ak_name)

        for row in rows:
            exported_label = pick(row, "content_label")
            exported_repo_name = pick(row, "repository_name")
            exported_product_name = pick(row, "product_name")
            state = pick(row, "status").lower()

            if state not in ("enabled", "disabled"):
                continue

            target_label, reason = choose_target_label(
                exported_label,
                exported_repo_name,
                exported_product_name,
                by_label,
                by_name_product,
                by_name,
            )

            if not target_label:
                report.append(
                    {
                        "step": "repo_override",
                        "activation_key_name": ak_name,
                        "status": "ERROR",
                        "message": reason,
                        "target_id": ak_id,
                        "repository_name": exported_repo_name,
                        "product_name": exported_product_name,
                        "content_label": exported_label,
                    }
                )
                continue

            res = apply_override(ak_name, target_label, state)
            report.append(
                {
                    "step": "repo_override",
                    "activation_key_name": ak_name,
                    "status": "APPLIED" if res.returncode == 0 else "ERROR",
                    "message": f"Override {state} applied; {reason}" if res.returncode == 0 else f"Failed to apply override {state}; {reason}",
                    "target_id": ak_id,
                    "repository_name": exported_repo_name,
                    "product_name": exported_product_name,
                    "content_label": target_label,
                }
            )

    write_report(report)

    log("==============================================================")
    log("Import finished")
    log(f"Report CSV : {REPORT_CSV}")
    log(f"Log file   : {LOG_FILE}")
    log("==============================================================")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"FATAL: {exc}")
        sys.exit(1)