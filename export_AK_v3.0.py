#!/usr/bin/env python3
import csv
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from typing import Dict, List

ORG = ""

OUT_DIR = f"ak_ui_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
AK_CSV = os.path.join(OUT_DIR, "activation_keys.csv")
AK_REPO_CSV = os.path.join(OUT_DIR, "activation_key_repository_sets.csv")
LOG_FILE = os.path.join(OUT_DIR, "export.log")


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


def hammer_text(args: List[str]) -> str:
    result = run_cmd(["hammer"] + args, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout


def pick(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return ""


def normalize_bool(v: str) -> str:
    s = (v or "").strip().lower()
    if s in ("true", "yes", "1"):
        return "yes"
    if s in ("false", "no", "0"):
        return "no"
    return ""


def normalize_override_state(value: str) -> str:
    s = (value or "").strip().lower()
    if s in ("1", "true", "yes", "enabled", "enable", "enabled (overridden)", "override to enabled"):
        return "enabled"
    if s in ("0", "false", "no", "disabled", "disable", "disabled (overridden)", "override to disabled"):
        return "disabled"
    if s in ("default", "reset", "reset to default", ""):
        return "default"
    return s


def parse_info(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = left.strip()
        val = right.strip()
        if key not in data:
            data[key] = val
    return data


def get_product_content_rows(ak_name: str) -> List[Dict[str, str]]:
    rows = hammer_csv(
        ["activation-key", "product-content", "--organization", ORG, "--name", ak_name]
    )
    out: List[Dict[str, str]] = []

    for row in rows:
        content_label = pick(row, "Content Label", "Content label", "Label", "content_label")
        content_name = pick(row, "Name", "Repository Name", "Content Name", "name")
        product_name = pick(row, "Product", "Product Name", "product")
        repo_path = pick(row, "Repository Path", "Path", "Repository path", "repository_path")
        override_raw = pick(
            row,
            "Override",
            "Override Value",
            "Status",
            "Enabled",
            "Value",
            "override",
        )
        state = normalize_override_state(override_raw)

        out.append(
            {
                "content_label": content_label,
                "content_name": content_name,
                "product_name": product_name,
                "repository_path": repo_path,
                "override_state": state,
            }
        )
    return out


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    ak_rows: List[Dict[str, str]] = []
    repo_rows: List[Dict[str, str]] = []

    aks = hammer_csv(["activation-key", "list", "--organization", ORG])
    if not aks:
        log("No activation keys found.")
        return 0

    for ak in aks:
        ak_id = pick(ak, "Activation Key ID", "Id", "ID")
        ak_name = pick(ak, "Name", "name")
        if not ak_name:
            continue

        log(f"Processing activation key: {ak_name}")

        info_text = hammer_text(
            ["activation-key", "info", "--organization", ORG, "--name", ak_name]
        )
        if not info_text:
            log(f"WARN: cannot read activation-key info for {ak_name}")
            continue

        info = parse_info(info_text)

        description = info.get("Description", "")
        release_version = info.get("Release Version", "")
        lifecycle_environment = info.get("Lifecycle Environment", "") or info.get("Environment", "")
        content_view = info.get("Content View", "")
        service_level = info.get("Service Level", "")
        usage = info.get("Usage", "") or info.get("Usage Type", "") or info.get("Purpose Usage", "")
        role = info.get("Role", "") or info.get("Purpose Role", "")
        unlimited_hosts = normalize_bool(info.get("Unlimited Hosts", "") or info.get("Unlimited Content Hosts", ""))
        max_hosts = info.get("Maximum Hosts", "") or info.get("Max Hosts", "")

        ak_rows.append(
            {
                "activation_key_id": ak_id,
                "name": ak_name,
                "description": description,
                "service_level": service_level,
                "usage": usage,
                "role": role,
                "release_version": release_version,
                "lifecycle_environment": lifecycle_environment,
                "content_view": content_view,
                "unlimited_hosts": unlimited_hosts,
                "max_hosts": max_hosts,
            }
        )

        for row in get_product_content_rows(ak_name):
            if row["override_state"] not in ("enabled", "disabled"):
                continue

            repo_rows.append(
                {
                    "activation_key_name": ak_name,
                    "content_label": row["content_label"],
                    "repository_name": row["content_name"],
                    "product_name": row["product_name"],
                    "repository_path": row["repository_path"],
                    "status": row["override_state"],
                }
            )

    with open(AK_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "activation_key_id",
                "name",
                "description",
                "service_level",
                "usage",
                "role",
                "release_version",
                "lifecycle_environment",
                "content_view",
                "unlimited_hosts",
                "max_hosts",
            ],
        )
        writer.writeheader()
        writer.writerows(ak_rows)

    with open(AK_REPO_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "activation_key_name",
                "content_label",
                "repository_name",
                "product_name",
                "repository_path",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(repo_rows)

    log("==============================================================")
    log("Export finished")
    log(f"Output dir                  : {OUT_DIR}")
    log(f"activation_keys.csv         : {AK_CSV}")
    log(f"activation_key_repository_sets.csv : {AK_REPO_CSV}")
    log("==============================================================")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {exc}")
        sys.exit(1)