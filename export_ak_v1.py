#!/usr/bin/env python3
import csv
import os
import shlex
import subprocess
import sys
from datetime import datetime

ORG = ""

OUT_DIR = f"ak_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
AK_CSV = os.path.join(OUT_DIR, "activation_keys.csv")
OVERRIDE_CSV = os.path.join(OUT_DIR, "activation_key_overrides.csv")
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
        raise RuntimeError(f"Command failed rc={result.returncode}: {' '.join(cmd)}")
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


def normalize_bool(v: str) -> str:
    s = (v or "").strip().lower()
    if s in ("true", "yes", "1"):
        return "yes"
    if s in ("false", "no", "0"):
        return "no"
    return ""


def parse_info(text: str):
    data = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = left.strip()
        val = right.strip()
        if key not in data:
            data[key] = val
    return data


def normalize_override_state(value: str) -> str:
    s = (value or "").strip().lower()
    if s in ("1", "true", "yes", "enabled", "enable", "override to enabled"):
        return "enabled"
    if s in ("0", "false", "no", "disabled", "disable", "override to disabled"):
        return "disabled"
    if s in ("default", "reset", "reset to default", ""):
        return "default"
    return s


def get_product_content_rows(ak_name: str):
    rows = hammer_csv(
        ["activation-key", "product-content", "--organization", ORG, "--name", ak_name]
    )
    out = []
    for row in rows:
        content_label = pick(row, "Content Label", "Content label", "Label", "content_label")
        content_name = pick(row, "Name", "Repository Name", "Content Name", "name")
        product_name = pick(row, "Product", "product")
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

        # On garde surtout enabled/disabled, mais on peut aussi garder default
        if content_label or content_name:
            out.append(
                {
                    "content_label": content_label,
                    "content_name": content_name,
                    "product_name": product_name,
                    "override_state": state,
                }
            )
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    ak_rows = []
    override_rows = []

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
        lifecycle_environment = (
            info.get("Lifecycle Environment")
            or info.get("Environment")
            or ""
        )
        content_view = info.get("Content View", "")
        content_view_environment = (
            info.get("Content View Environment")
            or info.get("Content View Environments")
            or ""
        )
        release_version = info.get("Release Version", "")
        unlimited_hosts = normalize_bool(
            info.get("Unlimited Hosts") or info.get("Unlimited Content Hosts", "")
        )
        max_hosts = info.get("Maximum Hosts") or info.get("Max Hosts") or ""
        auto_attach = normalize_bool(info.get("Auto Attach", ""))

        ak_rows.append(
            {
                "activation_key_id": ak_id,
                "name": ak_name,
                "description": description,
                "lifecycle_environment": lifecycle_environment,
                "content_view": content_view,
                "content_view_environment": content_view_environment,
                "release_version": release_version,
                "unlimited_hosts": unlimited_hosts,
                "max_hosts": max_hosts,
                "auto_attach": auto_attach,
            }
        )

        for row in get_product_content_rows(ak_name):
            if row["override_state"] not in ("enabled", "disabled"):
                continue
            override_rows.append(
                {
                    "activation_key_name": ak_name,
                    "content_label": row["content_label"],
                    "content_name": row["content_name"],
                    "product_name": row["product_name"],
                    "override_state": row["override_state"],
                }
            )

    with open(AK_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "activation_key_id",
                "name",
                "description",
                "lifecycle_environment",
                "content_view",
                "content_view_environment",
                "release_version",
                "unlimited_hosts",
                "max_hosts",
                "auto_attach",
            ],
        )
        writer.writeheader()
        writer.writerows(ak_rows)

    with open(OVERRIDE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "activation_key_name",
                "content_label",
                "content_name",
                "product_name",
                "override_state",
            ],
        )
        writer.writeheader()
        writer.writerows(override_rows)

    log("==============================================================")
    log(f"Export finished")
    log(f"Output dir            : {OUT_DIR}")
    log(f"activation_keys.csv   : {AK_CSV}")
    log(f"overrides.csv         : {OVERRIDE_CSV}")
    log("==============================================================")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {exc}")
        sys.exit(1)