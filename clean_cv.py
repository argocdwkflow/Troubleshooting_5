#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ============================================================
# CONFIG PAR DEFAUT
# ============================================================

DEFAULT_ORG = ""
DEFAULT_KEEP_CCV = "ccv_test2"
DEFAULT_KEEP_LIFECYCLE = "Library"

# Tu peux garder aussi certains CV composants si nécessaire
DEFAULT_KEEP_CONTENT_VIEWS = [
    "ccv_test2",   # le CCV final conservé
]

# Si tu veux rattacher certains CV vers ccv_test2 avant nettoyage
# Mets ici les noms exacts des CV que tu veux injecter dans ccv_test2
DEFAULT_ATTACH_TO_CCV_TEST2 = [
    # "cv_rhel94",
    # "cv_satellite_capsule_rhel9",
]

# Si True, on ignore Default Organization View
SKIP_DEFAULT_ORGANIZATION_VIEW = True

# ============================================================
# OUTILS
# ============================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg: str):
    print(f"[{now()}] {msg}")

def run_cmd(cmd: List[str], dry_run: bool = False) -> subprocess.CompletedProcess:
    log("CMD: " + " ".join(shlex.quote(x) for x in cmd))
    if dry_run:
        class Dummy:
            returncode = 0
            stdout = ""
            stderr = ""
        return Dummy()
    return subprocess.run(cmd, text=True, capture_output=True)

def hammer_csv(args: List[str], dry_run: bool = False) -> List[Dict[str, str]]:
    res = run_cmd(["hammer", "--csv"] + args, dry_run=dry_run)
    if dry_run:
        return []
    if res.returncode != 0:
        raise RuntimeError(f"hammer csv failed: {' '.join(args)}\n{res.stderr}")
    if not res.stdout.strip():
        return []
    return list(csv.DictReader(res.stdout.splitlines()))

def hammer_text(args: List[str], dry_run: bool = False) -> str:
    res = run_cmd(["hammer"] + args, dry_run=dry_run)
    if dry_run:
        return ""
    if res.returncode != 0:
        raise RuntimeError(f"hammer failed: {' '.join(args)}\n{res.stderr}")
    return res.stdout

def pick(row: Dict[str, str], *keys: str) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return ""

def safe_int(v: str, default: int = -1) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default

# ============================================================
# SATELLITE CLEANER
# ============================================================

class SatelliteCleaner:
    def __init__(
        self,
        org: str,
        keep_ccv: str,
        keep_lifecycle: str,
        keep_content_views: List[str],
        attach_to_ccv_test2: List[str],
        dry_run: bool = False,
        sleep_seconds: int = 1,
    ):
        self.org = org
        self.keep_ccv = keep_ccv
        self.keep_lifecycle = keep_lifecycle
        self.keep_content_views = list(set(keep_content_views + [keep_ccv]))
        self.attach_to_ccv_test2 = attach_to_ccv_test2
        self.dry_run = dry_run
        self.sleep_seconds = sleep_seconds

    # --------------------------------------------------------
    # INVENTAIRE
    # --------------------------------------------------------

    def list_content_views(self) -> List[Dict[str, str]]:
        rows = hammer_csv(["content-view", "list", "--organization", self.org], dry_run=self.dry_run)
        out = []
        for r in rows:
            out.append({
                "id": pick(r, "Content View ID", "Id", "ID"),
                "name": pick(r, "Name", "name"),
                "label": pick(r, "Label", "label"),
                "composite": pick(r, "Composite", "composite").lower(),
            })
        return out

    def get_cv_by_name(self, name: str) -> Optional[Dict[str, str]]:
        for cv in self.list_content_views():
            if cv["name"] == name:
                return cv
        return None

    def get_cv_info(self, name: str) -> str:
        return hammer_text(
            ["content-view", "info", "--organization", self.org, "--name", name],
            dry_run=self.dry_run
        )

    def get_cv_versions(self, name: str) -> List[Dict[str, str]]:
        rows = hammer_csv(
            ["content-view", "version", "list", "--organization", self.org, "--content-view", name],
            dry_run=self.dry_run
        )
        out = []
        for r in rows:
            out.append({
                "id": pick(r, "Content View Version ID", "Id", "ID"),
                "version": pick(r, "Version", "version"),
                "environments": pick(r, "Lifecycle Environments", "Environments", "Environment"),
            })
        return sorted(out, key=lambda x: safe_int(x["id"]), reverse=True)

    def get_ccv_components(self, ccv_name: str) -> List[Dict[str, str]]:
        """
        Selon version Satellite, --composite-content-view-id ou autre peut varier.
        On se base sur content-view info pour parser la section Components.
        """
        info = self.get_cv_info(ccv_name)
        components = []
        in_components = False
        current = {}

        for raw in info.splitlines():
            line = raw.rstrip()

            if line.strip() == "Components:":
                in_components = True
                continue

            if in_components:
                if not line.strip():
                    continue

                if line.strip().startswith("Activation Keys:"):
                    break

                s = line.strip()

                if s.startswith("Id:"):
                    if current:
                        components.append(current)
                        current = {}
                    current["id"] = s.split(":", 1)[1].strip()
                elif s.startswith("Name:"):
                    current["name"] = s.split(":", 1)[1].strip()
                elif s.startswith("Latest version:"):
                    current["latest_version"] = s.split(":", 1)[1].strip()
                elif s.startswith("Not yet published:"):
                    current["not_yet_published"] = s.split(":", 1)[1].strip()
                elif s.startswith("Always update to the latest:"):
                    current["always_latest"] = s.split(":", 1)[1].strip()

        if current:
            components.append(current)

        return components

    # --------------------------------------------------------
    # REAFFECTATION VERS ccv_test2
    # --------------------------------------------------------

    def ensure_ccv_exists(self):
        ccv = self.get_cv_by_name(self.keep_ccv)
        if not ccv:
            raise RuntimeError(f"CCV à conserver introuvable: {self.keep_ccv}")
        if ccv["composite"] not in ("yes", "true"):
            raise RuntimeError(f"{self.keep_ccv} existe mais n'est pas un CCV")

    def ccv_has_component(self, ccv_name: str, cv_name: str) -> bool:
        comps = self.get_ccv_components(ccv_name)
        for c in comps:
            if c.get("name") == cv_name:
                return True
        return False

    def add_component_to_ccv(self, ccv_name: str, cv_name: str):
        if self.ccv_has_component(ccv_name, cv_name):
            log(f"Composant déjà présent dans {ccv_name}: {cv_name}")
            return

        log(f"Ajout du CV {cv_name} dans le CCV {ccv_name}")
        # Sur beaucoup de versions Satellite :
        # hammer content-view component add --composite-content-view <ccv> --content-view <cv> --latest
        res = run_cmd([
            "hammer", "content-view", "component", "add",
            "--organization", self.org,
            "--composite-content-view", ccv_name,
            "--content-view", cv_name,
            "--latest"
        ], dry_run=self.dry_run)

        if not self.dry_run and res.returncode != 0:
            raise RuntimeError(f"Echec ajout composant {cv_name} -> {ccv_name}\n{res.stderr}")

    # --------------------------------------------------------
    # RETRAIT DE CV DE CHAQUE CCV
    # --------------------------------------------------------

    def remove_component_from_ccv(self, ccv_name: str, cv_name: str):
        log(f"Retrait du composant {cv_name} depuis {ccv_name}")
        res = run_cmd([
            "hammer", "content-view", "component", "remove",
            "--organization", self.org,
            "--composite-content-view", ccv_name,
            "--content-view", cv_name
        ], dry_run=self.dry_run)

        if not self.dry_run and res.returncode != 0:
            raise RuntimeError(f"Echec retrait composant {cv_name} de {ccv_name}\n{res.stderr}")

    def detach_all_components_from_ccv(self, ccv_name: str, keep_if_in_whitelist: bool = False):
        components = self.get_ccv_components(ccv_name)
        if not components:
            log(f"Aucun composant trouvé dans {ccv_name}")
            return

        for comp in components:
            comp_name = comp.get("name", "")
            if keep_if_in_whitelist and comp_name in self.keep_content_views:
                log(f"Composant conservé dans {ccv_name}: {comp_name}")
                continue
            self.remove_component_from_ccv(ccv_name, comp_name)
            time.sleep(self.sleep_seconds)

    # --------------------------------------------------------
    # SUPPRESSION DE VERSIONS
    # --------------------------------------------------------

    def delete_all_versions_of_cv(self, cv_name: str):
        versions = self.get_cv_versions(cv_name)
        if not versions:
            log(f"Aucune version trouvée pour {cv_name}")
            return

        for v in versions:
            version_id = v["id"]
            version_name = v["version"]
            envs = v["environments"]

            if envs and envs.strip():
                log(f"Version {cv_name} {version_name} encore promue dans [{envs}] -> skip")
                continue

            log(f"Suppression version {version_name} (id={version_id}) de {cv_name}")
            res = run_cmd([
                "hammer", "content-view", "version", "delete",
                "--organization", self.org,
                "--id", version_id
            ], dry_run=self.dry_run)

            if not self.dry_run and res.returncode != 0:
                raise RuntimeError(f"Echec suppression version {version_name} de {cv_name}\n{res.stderr}")

            time.sleep(self.sleep_seconds)

    # --------------------------------------------------------
    # SUPPRESSION CV / CCV
    # --------------------------------------------------------

    def delete_cv(self, cv_name: str):
        if SKIP_DEFAULT_ORGANIZATION_VIEW and cv_name == "Default Organization View":
            log("Skip Default Organization View")
            return

        if cv_name in self.keep_content_views:
            log(f"Conservé (whitelist): {cv_name}")
            return

        log(f"Suppression Content View: {cv_name}")
        res = run_cmd([
            "hammer", "content-view", "delete",
            "--organization", self.org,
            "--name", cv_name
        ], dry_run=self.dry_run)

        if not self.dry_run and res.returncode != 0:
            raise RuntimeError(f"Echec suppression Content View {cv_name}\n{res.stderr}")

    # --------------------------------------------------------
    # FLOW PRINCIPAL
    # --------------------------------------------------------

    def print_inventory(self):
        cvs = self.list_content_views()
        log("=== INVENTAIRE CONTENT VIEWS ===")
        for cv in cvs:
            log(json.dumps(cv, ensure_ascii=False))

    def attach_selected_cvs_to_ccv_test2(self):
        if not self.attach_to_ccv_test2:
            log("Aucun CV à rattacher vers ccv_test2")
            return

        self.ensure_ccv_exists()

        for cv_name in self.attach_to_ccv_test2:
            cv = self.get_cv_by_name(cv_name)
            if not cv:
                log(f"CV introuvable, impossible à rattacher: {cv_name}")
                continue
            if cv["composite"] in ("yes", "true"):
                log(f"Skip: {cv_name} est un CCV, pas un CV composant")
                continue
            self.add_component_to_ccv(self.keep_ccv, cv_name)
            time.sleep(self.sleep_seconds)

    def cleanup_all_other_ccvs(self):
        cvs = self.list_content_views()

        # 1) nettoyer d'abord les CCV autres que keep_ccv
        for cv in cvs:
            if cv["composite"] not in ("yes", "true"):
                continue
            name = cv["name"]

            if name == self.keep_ccv:
                log(f"CCV conservé: {name}")
                continue

            log(f"Nettoyage du CCV {name}: retrait de tous ses composants")
            self.detach_all_components_from_ccv(name)
            time.sleep(self.sleep_seconds)

            log(f"Suppression des versions non promues de {name}")
            self.delete_all_versions_of_cv(name)
            time.sleep(self.sleep_seconds)

            self.delete_cv(name)
            time.sleep(self.sleep_seconds)

    def cleanup_all_other_cvs(self):
        cvs = self.list_content_views()

        # 2) puis supprimer les CV simples non whitelistés
        for cv in cvs:
            if cv["composite"] in ("yes", "true"):
                continue

            name = cv["name"]
            if name in self.keep_content_views:
                log(f"CV conservé: {name}")
                continue

            log(f"Suppression des versions non promues de {name}")
            self.delete_all_versions_of_cv(name)
            time.sleep(self.sleep_seconds)

            self.delete_cv(name)
            time.sleep(self.sleep_seconds)

    def run(self):
        self.print_inventory()

        log("=== ETAPE 1: rattacher certains CV vers ccv_test2 si demandé ===")
        self.attach_selected_cvs_to_ccv_test2()

        log("=== ETAPE 2: nettoyer tous les autres CCV ===")
        self.cleanup_all_other_ccvs()

        log("=== ETAPE 3: nettoyer tous les autres CV ===")
        self.cleanup_all_other_cvs()

        log("=== ETAPE 4: inventaire final ===")
        self.print_inventory()

# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Nettoyage Satellite: retirer CV des CCV, garder ccv_test2, supprimer les autres CV/CCV"
    )
    parser.add_argument("--organization", default=DEFAULT_ORG)
    parser.add_argument("--keep-ccv", default=DEFAULT_KEEP_CCV)
    parser.add_argument("--keep-lifecycle", default=DEFAULT_KEEP_LIFECYCLE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-seconds", type=int, default=1)
    parser.add_argument(
        "--keep-cv",
        action="append",
        default=[],
        help="CV/CCV supplémentaire à conserver; option répétable"
    )
    parser.add_argument(
        "--attach-to-ccv-test2",
        action="append",
        default=[],
        help="CV simple à ajouter dans ccv_test2 avant nettoyage; option répétable"
    )

    args = parser.parse_args()

    keep_content_views = list(set(DEFAULT_KEEP_CONTENT_VIEWS + args.keep_cv))
    attach_to_ccv_test2 = list(set(DEFAULT_ATTACH_TO_CCV_TEST2 + args.attach_to_ccv_test2))

    cleaner = SatelliteCleaner(
        org=args.organization,
        keep_ccv=args.keep_ccv,
        keep_lifecycle=args.keep_lifecycle,
        keep_content_views=keep_content_views,
        attach_to_ccv_test2=attach_to_ccv_test2,
        dry_run=args.dry_run,
        sleep_seconds=args.sleep_seconds,
    )

    try:
        cleaner.run()
        log("Nettoyage terminé avec succès")
    except Exception as exc:
        log(f"ERREUR: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()