#!/bin/bash
set -Eeuo pipefail

ORG="xxxxxx"

OUT_DIR="sat_export_$(date +%Y%m%d_%H%M%S)"
RAW_DIR="${OUT_DIR}/raw_content_views"
LOG_FILE="${OUT_DIR}/export.log"

CV_CSV="${OUT_DIR}/content_views_full.csv"
CV_REPO_CSV="${OUT_DIR}/content_view_repositories.csv"
CCV_COMPONENTS_CSV="${OUT_DIR}/ccv_components.csv"

mkdir -p "${OUT_DIR}" "${RAW_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

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

extract_field() {
  local key="$1"
  local file="$2"
  awk -F': *' -v k="$key" '$1 == k {sub($1 FS, ""); print; exit}' "$file"
}

echo '"content_view_id","name","label","composite","description","content_host_count","solve_dependencies","organization"' > "${CV_CSV}"
echo '"content_view_id","content_view_name","content_view_label","repository_id","repository_name","repository_label"' > "${CV_REPO_CSV}"
echo '"ccv_name","ccv_label","component_cv_name"' > "${CCV_COMPONENTS_CSV}"

echo "=============================================================="
echo " Export CV / CCV"
echo " Organization : ${ORG}"
echo " Output dir   : ${OUT_DIR}"
echo " Started at   : $(date)"
echo "=============================================================="

mapfile -t CV_LINES < <(
  hammer --csv content-view list --organization "${ORG}" | tail -n +2
)

if [ "${#CV_LINES[@]}" -eq 0 ]; then
  echo "No Content Views found in ${ORG}"
  exit 0
fi

SUCCESS=0
FAILED=0

for line in "${CV_LINES[@]}"; do
  IFS=',' read -r CV_ID CV_NAME CV_LABEL CV_COMPOSITE _REST <<< "${line}"

  CV_ID="$(echo "${CV_ID:-}" | sed 's/^"//;s/"$//' | xargs)"
  CV_NAME="$(echo "${CV_NAME:-}" | sed 's/^"//;s/"$//' | xargs)"
  CV_LABEL="$(echo "${CV_LABEL:-}" | sed 's/^"//;s/"$//' | xargs)"
  CV_COMPOSITE="$(echo "${CV_COMPOSITE:-}" | sed 's/^"//;s/"$//' | xargs | tr '[:upper:]' '[:lower:]')"

  [ -z "${CV_ID}" ] && continue
  [ -z "${CV_NAME}" ] && continue

  echo
  echo "--------------------------------------------------------------"
  echo "Processing CV: ${CV_NAME} (ID=${CV_ID})"
  echo "--------------------------------------------------------------"

  SAFE_NAME="$(sanitize_name "${CV_NAME}")"
  RAW_FILE="${RAW_DIR}/${CV_ID}_${SAFE_NAME}.txt"

  if ! hammer content-view info \
      --organization "${ORG}" \
      --id "${CV_ID}" > "${RAW_FILE}" 2>/dev/null; then
    echo "ERROR: unable to read content-view info for ${CV_NAME}"
    FAILED=$((FAILED + 1))
    continue
  fi

  NAME_VAL="$(extract_field "Name" "${RAW_FILE}")"
  LABEL_VAL="$(extract_field "Label" "${RAW_FILE}")"
  COMPOSITE_VAL="$(extract_field "Composite" "${RAW_FILE}")"
  DESC_VAL="$(extract_field "Description" "${RAW_FILE}")"
  HOST_COUNT_VAL="$(extract_field "Content Host Count" "${RAW_FILE}")"
  SOLVE_DEPS_VAL="$(extract_field "Solve Dependencies" "${RAW_FILE}")"
  ORG_VAL="$(extract_field "Organisation" "${RAW_FILE}")"
  [ -z "${ORG_VAL}" ] && ORG_VAL="$(extract_field "Organization" "${RAW_FILE}")"

  [ -z "${NAME_VAL}" ] && NAME_VAL="${CV_NAME}"
  [ -z "${LABEL_VAL}" ] && LABEL_VAL="${CV_LABEL}"
  [ -z "${COMPOSITE_VAL}" ] && COMPOSITE_VAL="${CV_COMPOSITE}"

  case "$(echo "${COMPOSITE_VAL}" | tr '[:upper:]' '[:lower:]')" in
    yes|true) COMPOSITE_VAL="yes" ;;
    *) COMPOSITE_VAL="no" ;;
  esac

  printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$(csv_escape "${CV_ID}")" \
    "$(csv_escape "${NAME_VAL}")" \
    "$(csv_escape "${LABEL_VAL}")" \
    "$(csv_escape "${COMPOSITE_VAL}")" \
    "$(csv_escape "${DESC_VAL}")" \
    "$(csv_escape "${HOST_COUNT_VAL}")" \
    "$(csv_escape "${SOLVE_DEPS_VAL}")" \
    "$(csv_escape "${ORG_VAL:-$ORG}")" \
    >> "${CV_CSV}"

  awk -v cv_id="${CV_ID}" -v cv_name="${NAME_VAL}" -v cv_label="${LABEL_VAL}" '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    function csvq(s) { gsub(/"/, "\"\"", s); return "\"" s "\"" }

    /^Yum Repositories:/ { inrepos=1; next }
    inrepos && /^[^[:space:]]/ { inrepos=0 }

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

        if (repo_id != "" && repo_name != "") {
          print csvq(cv_id) "," csvq(cv_name) "," csvq(cv_label) "," \
                csvq(repo_id) "," csvq(repo_name) "," csvq(repo_label)
        }

        repo_id=""
        repo_name=""
        repo_label=""
      }
    }
  ' "${RAW_FILE}" >> "${CV_REPO_CSV}"

  if [ "${COMPOSITE_VAL}" = "yes" ]; then
    echo "Collecting components for CCV: ${NAME_VAL}"

    hammer --csv content-view component list \
      --organization "${ORG}" \
      --content-view-id "${CV_ID}" 2>/dev/null | tail -n +2 | \
    while IFS=',' read -r COMP_ID COMP_NAME _REST2; do
      COMP_NAME="$(echo "${COMP_NAME:-}" | sed 's/^"//;s/"$//' | xargs)"
      [ -z "${COMP_NAME}" ] && continue

      printf '%s,%s,%s\n' \
        "$(csv_escape "${NAME_VAL}")" \
        "$(csv_escape "${LABEL_VAL}")" \
        "$(csv_escape "${COMP_NAME}")" \
        >> "${CCV_COMPONENTS_CSV}"
    done
  fi

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
echo "CCV CSV     : ${CCV_COMPONENTS_CSV}"
echo "Raw files   : ${RAW_DIR}"
echo "Log file    : ${LOG_FILE}"
echo "=============================================================="