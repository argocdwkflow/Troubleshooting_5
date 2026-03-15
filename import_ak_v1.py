#!/usr/bin/env python3
import csv
import os
import shlex
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

ORG = ""

AK_CSV = "activation_keys.csv"
OVERRIDE_CSV = "activation_key_overrides.csv"

REPORT_CSV = f"ak_import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
LOG_FILE = f"ak_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


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


def pick(row, *keys):
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return ""


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def ensure_files():
    for path in (AK_CSV, OVERRIDE_CSV):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing required file: {path}")


def normalize_bool(v: str) -> str:
    s = (v or "").strip().lower()
    if s in ("true", "yes", "1"):
        return "yes"
    if s in ("false", "no", "0"):
        return "no"
    return ""


def get_all_activation_keys():
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


def get_ak_id_by_name(ak_name):
    for row in get_all_activation_keys():
        if row["name"] == ak_name:
            return row["id"]
    return ""


def create_activation_key(name, description="", unlimited_hosts="", max_hosts="", auto_attach=""):
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
    if normalize_bool(auto_attach):
        cmd += ["--auto-attach", "true" if normalize_bool(auto_attach) == "yes" else "false"]
    return run_cmd(cmd, check=False)


def update_activation_key(ak_name, row):
    description = pick(row, "description")
    lifecycle_environment = pick(row, "lifecycle_environment")
    content_view = pick(row, "content_view")
    content_view_environment = pick(row, "content_view_environment")
    release_version = pick(row, "release_version")
    unlimited_hosts = pick(row, "unlimited_hosts")
    max_hosts = pick(row, "max_hosts")
    auto_attach = pick(row, "auto_attach")

    cmd = [
        "hammer",
        "activation-key",
        "update",
        "--organization",
        ORG,
        "--name",
        ak_name,
    ]

    if description:
        cmd += ["--description", description]

    # Mode classique CV + Lifecycle Environment
    if lifecycle_environment and content_view:
        cmd += ["--lifecycle-environment", lifecycle_environment, "--content-view", content_view]
    # Fallback moderne content-view-environments
    elif content_view_environment:
        cmd += ["--content-view-environments", content_view_environment]

    if release_version:
        cmd += ["--release-version", release_version]

    if normalize_bool(unlimited_hosts) == "yes":
        cmd += ["--unlimited-hosts", "true"]
    elif max_hosts:
        cmd += ["--max-hosts", max_hosts]

    if normalize_bool(auto_attach):
        cmd += ["--auto-attach", "true" if normalize_bool(auto_attach) == "yes" else "false"]

    return run_cmd(cmd, check=False)


def get_target_product_content_map(ak_name):
    rows = hammer_csv(
        ["activation-key", "product-content", "--organization", ORG, "--name", ak_name]
    )
    by_label = {}
    by_name = defaultdict(list)

    for row in rows:
        content_label = pick(row, "Content Label", "Content label", "Label", "content_label")
        content_name = pick(row, "Name", "Repository Name", "Content Name", "name")
        product_name = pick(row, "Product", "product")
        if content_label:
            by_label[content_label] = {
                "content_label": content_label,
                "content_name": content_name,
                "product_name": product_name,
            }
        if content_name:
            by_name[content_name].append(
                {
                    "content_label": content_label,
                    "content_name": content_name,
                    "product_name": product_name,
                }
            )
    return by_label, by_name


def apply_override(ak_name, content_label, state):
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


def write_report(rows):
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "step",
                "activation_key_name",
                "status",
                "message",
                "target_id",
                "content_name",
                "content_label",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    ensure_files()

    ak_rows = load_csv(AK_CSV)
    override_rows = load_csv(OVERRIDE_CSV)
    report = []

    # 1. create / update AK
    for row in ak_rows:
        ak_name = pick(row, "name")
        if not ak_name:
            continue

        ak_id = get_ak_id_by_name(ak_name)
        if not ak_id:
            result = create_activation_key(
                name=ak_name,
                description=pick(row, "description"),
                unlimited_hosts=pick(row, "unlimited_hosts"),
                max_hosts=pick(row, "max_hosts"),
                auto_attach=pick(row, "auto_attach"),
            )
            ak_id = get_ak_id_by_name(ak_name)
            if result.returncode == 0 and ak_id:
                report.append(
                    {
                        "step": "create_ak",
                        "activation_key_name": ak_name,
                        "status": "CREATED",
                        "message": "Activation key created",
                        "target_id": ak_id,
                        "content_name": "",
                        "content_label": "",
                    }
                )
            else:
                report.append(
                    {
                        "step": "create_ak",
                        "activation_key_name": ak_name,
                        "status": "ERROR",
                        "message": "Failed to create activation key",
                        "target_id": "",
                        "content_name": "",
                        "content_label": "",
                    }
                )
                continue
        else:
            report.append(
                {
                    "step": "create_ak",
                    "activation_key_name": ak_name,
                    "status": "OK_EXISTS",
                    "message": "Activation key already exists",
                    "target_id": ak_id,
                    "content_name": "",
                    "content_label": "",
                }
            )

        result = update_activation_key(ak_name, row)
        report.append(
            {
                "step": "update_ak",
                "activation_key_name": ak_name,
                "status": "UPDATED" if result.returncode == 0 else "ERROR",
                "message": "Activation key updated" if result.returncode == 0 else "Failed to update activation key",
                "target_id": get_ak_id_by_name(ak_name),
                "content_name": "",
                "content_label": "",
            }
        )

    # 2. apply overrides
    overrides_by_ak = defaultdict(list)
    for row in override_rows:
        ak_name = pick(row, "activation_key_name")
        if ak_name:
            overrides_by_ak[ak_name].append(row)

    for ak_name, rows in overrides_by_ak.items():
        ak_id = get_ak_id_by_name(ak_name)
        if not ak_id:
            report.append(
                {
                    "step": "override",
                    "activation_key_name": ak_name,
                    "status": "ERROR",
                    "message": "Activation key not found on target",
                    "target_id": "",
                    "content_name": "",
                    "content_label": "",
                }
            )
            continue

        by_label, by_name = get_target_product_content_map(ak_name)

        for row in rows:
            exported_label = pick(row, "content_label")
            exported_name = pick(row, "content_name")
            state = pick(row, "override_state").lower()

            if state not in ("enabled", "disabled"):
                continue

            target_label = ""

            if exported_label and exported_label in by_label:
                target_label = exported_label
            elif exported_name and exported_name in by_name:
                matches = by_name[exported_name]
                if matches:
                    target_label = matches[0]["content_label"]

            if not target_label:
                report.append(
                    {
                        "step": "override",
                        "activation_key_name": ak_name,
                        "status": "ERROR",
                        "message": f"No target content label found for content '{exported_name}'",
                        "target_id": ak_id,
                        "content_name": exported_name,
                        "content_label": exported_label,
                    }
                )
                continue

            result = apply_override(ak_name, target_label, state)
            report.append(
                {
                    "step": "override",
                    "activation_key_name": ak_name,
                    "status": "APPLIED" if result.returncode == 0 else "ERROR",
                    "message": f"Override {state} applied" if result.returncode == 0 else f"Failed to apply override {state}",
                    "target_id": ak_id,
                    "content_name": exported_name,
                    "content_label": target_label,
                }
            )

    write_report(report)

    log("==============================================================")
    log(f"Import finished")
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