#!/bin/bash
set -Eeuo pipefail

ORG="BP2I Linux"
OUT_DIR="/var/tmp/export_cv_details_$(date +%F_%H%M%S)"
RAW_DIR="${OUT_DIR}/raw_content_views"
LOG_FILE="${OUT_DIR}/export.log"

CV_CSV="${OUT_DIR}/content_views_full.csv"
CV_REPO_CSV="${OUT_DIR}/content_view_repositories.csv"

mkdir -p "${OUT_DIR}" "${RAW_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=============================================================="
echo " Export Content Views details"
echo " Organization : ${ORG}"
echo " Output dir   : ${OUT_DIR}"
echo " Started at   : $(date)"
echo "=============================================================="

command -v hammer >/dev/null 2>&1 || {
  echo "ERROR: hammer command not found"
  exit 1
}

csv_escape() {
  local s="${1:-}"
  s="${s//\"/\"\"}"
  printf '"%s"' "$s"
}

sanitize_name() {
  echo "$1" | sed 's/[[:space:]]\+/_/g' | tr -cd '[:alnum:]_.-'
}

extract_simple_field() {
  local key="$1"
  local file="$2"
  awk -F': *' -v k="$key" '$1 == k {sub($1 FS, ""); print; exit}' "$file"
}

echo '"content_view_id","name","label","composite","description","content_host_count","solve_dependencies","organization"' > "${CV_CSV}"
echo '"content_view_id","content_view_name","content_view_label","repository_id","repository_name","repository_label"' > "${CV_REPO_CSV}"

echo
echo "Listing all Content Views..."

mapfile -t CV_LINES < <(
  hammer --csv content-view list --organization "${ORG}" | tail -n +2
)

if [ "${#CV_LINES[@]}" -eq 0 ]; then
  echo "No Content Views found in organization ${ORG}"
  exit 0
fi

SUCCESS=0
FAILED=0

for line in "${CV_LINES[@]}"; do
  IFS=',' read -r CV_ID CV_NAME CV_LABEL _REST <<< "${line}"

  CV_ID="$(echo "${CV_ID:-}" | sed 's/^"//;s/"$//' | xargs)"
  CV_NAME="$(echo "${CV_NAME:-}" | sed 's/^"//;s/"$//' | xargs)"
  CV_LABEL="$(echo "${CV_LABEL:-}" | sed 's/^"//;s/"$//' | xargs)"

  [ -z "${CV_ID}" ] && continue

  echo
  echo "--------------------------------------------------------------"
  echo "Processing CV: ${CV_NAME} (ID=${CV_ID})"
  echo "--------------------------------------------------------------"

  SAFE_NAME="$(sanitize_name "${CV_NAME}")"
  RAW_FILE="${RAW_DIR}/${CV_ID}_${SAFE_NAME}.txt"

  if ! hammer content-view info \
      --organization "${ORG}" \
      --id "${CV_ID}" > "${RAW_FILE}" 2>/dev/null; then
    echo "ERROR: unable to export info for CV ${CV_NAME} (ID=${CV_ID})"
    FAILED=$((FAILED + 1))
    continue
  fi

  NAME_VAL="$(extract_simple_field "Name" "${RAW_FILE}")"
  LABEL_VAL="$(extract_simple_field "Label" "${RAW_FILE}")"
  COMPOSITE_VAL="$(extract_simple_field "Composite" "${RAW_FILE}")"
  DESC_VAL="$(extract_simple_field "Description" "${RAW_FILE}")"
  HOST_COUNT_VAL="$(extract_simple_field "Content Host Count" "${RAW_FILE}")"
  SOLVE_DEPS_VAL="$(extract_simple_field "Solve Dependencies" "${RAW_FILE}")"
  ORG_VAL="$(extract_simple_field "Organisation" "${RAW_FILE}")"
  [ -z "${ORG_VAL}" ] && ORG_VAL="$(extract_simple_field "Organization" "${RAW_FILE}")"

  printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$(csv_escape "${CV_ID}")" \
    "$(csv_escape "${NAME_VAL}")" \
    "$(csv_escape "${LABEL_VAL}")" \
    "$(csv_escape "${COMPOSITE_VAL}")" \
    "$(csv_escape "${DESC_VAL}")" \
    "$(csv_escape "${HOST_COUNT_VAL}")" \
    "$(csv_escape "${SOLVE_DEPS_VAL}")" \
    "$(csv_escape "${ORG_VAL}")" \
    >> "${CV_CSV}"

  awk -v cv_id="${CV_ID}" -v cv_name="${NAME_VAL}" -v cv_label="${LABEL_VAL}" '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    function csv_escape(s) { gsub(/"/, "\"\"", s); return "\"" s "\"" }

    /^Yum Repositories:/ { inrepos=1; next }
    /^Lifecycle Environments:/ { inrepos=0 }
    /^Versions:/ { inrepos=0 }

    inrepos {
      if ($0 ~ /^[[:space:]]*[0-9]+\)[[:space:]]*Id:[[:space:]]*/) {
        line=$0
        sub(/^[[:space:]]*[0-9]+\)[[:space:]]*Id:[[:space:]]*/, "", line)
        repo_id=trim(line)
      }
      else if ($0 ~ /^[[:space:]]*Id:[[:space:]]*/) {
        line=$0
        sub(/^[[:space:]]*Id:[[:space:]]*/, "", line)
        repo_id=trim(line)
      }
      else if ($0 ~ /^[[:space:]]*Name:[[:space:]]*/) {
        line=$0
        sub(/^[[:space:]]*Name:[[:space:]]*/, "", line)
        repo_name=trim(line)
      }
      else if ($0 ~ /^[[:space:]]*Label:[[:space:]]*/) {
        line=$0
        sub(/^[[:space:]]*Label:[[:space:]]*/, "", line)
        repo_label=trim(line)

        print csv_escape(cv_id) "," \
              csv_escape(cv_name) "," \
              csv_escape(cv_label) "," \
              csv_escape(repo_id) "," \
              csv_escape(repo_name) "," \
              csv_escape(repo_label)

        repo_id=""
        repo_name=""
        repo_label=""
      }
    }
  ' "${RAW_FILE}" >> "${CV_REPO_CSV}"

  SUCCESS=$((SUCCESS + 1))
done

echo
echo "=============================================================="
echo "Finished at : $(date)"
echo "Success     : ${SUCCESS}"
echo "Failed      : ${FAILED}"
echo "Output dir  : ${OUT_DIR}"
echo "CV CSV      : ${CV_CSV}"
echo "Repo CSV    : ${CV_REPO_CSV}"
echo "Raw files   : ${RAW_DIR}"
echo "Log file    : ${LOG_FILE}"
echo "=============================================================="