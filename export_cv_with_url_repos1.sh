#!/bin/bash
set -Eeuo pipefail

ORG="MON_ORGANIZATION"
OUT_DIR="/var/tmp/sat_cv_repo_export_$(date +%F_%H%M%S)"
OUT_CSV="${OUT_DIR}/cv_repositories_published_at.csv"
LOG="${OUT_DIR}/export.log"

mkdir -p "${OUT_DIR}"
exec > >(tee -a "${LOG}") 2>&1

command -v hammer >/dev/null 2>&1 || {
  echo "ERROR: hammer not found"
  exit 1
}

csv_escape() {
  local s="${1:-}"
  s="${s//\"/\"\"}"
  printf '"%s"' "$s"
}

extract_field() {
  local key="$1"
  local text="$2"
  echo "${text}" | awk -F': *' -v k="$key" '$1 == k {sub($1 FS, ""); print; exit}'
}

echo '"cv_name","cv_label","repo_id","repo_name","product_name","content_type","published_at","relative_path","download_policy","mirroring_policy"' > "${OUT_CSV}"

echo "Listing content views from organization: ${ORG}"
mapfile -t CVS < <(
  hammer --csv content-view list \
    --organization "${ORG}" \
    --fields "Id,Name,Label" | tail -n +2
)

for cv_line in "${CVS[@]}"; do
  CV_ID="$(echo "${cv_line}" | awk -F, '{print $1}' | xargs)"
  CV_NAME="$(echo "${cv_line}" | awk -F, '{print $2}' | sed 's/^"//;s/"$//' | xargs)"
  CV_LABEL="$(echo "${cv_line}" | awk -F, '{print $3}' | sed 's/^"//;s/"$//' | xargs)"

  echo
  echo "Processing CV: ${CV_NAME} (ID=${CV_ID})"

  CV_INFO="$(hammer content-view info \
    --organization "${ORG}" \
    --id "${CV_ID}" 2>/dev/null || true)"

  if [ -z "${CV_INFO}" ]; then
    echo "WARN: unable to read content-view info for ${CV_NAME}"
    continue
  fi

  # Récupère la section Repositories de manière simple
  REPO_LINES="$(echo "${CV_INFO}" | awk '
    /^Repositories:/ {flag=1; next}
    /^[^[:space:]].*:$/ && flag==1 {exit}
    flag==1 {print}
  ')"

  if [ -z "${REPO_LINES}" ]; then
    echo "INFO: no repositories found in ${CV_NAME} (possible CCV or empty CV)"
    continue
  fi

  while IFS= read -r repo_name; do
    repo_name="$(echo "${repo_name}" | sed 's/^[[:space:]-]*//' | xargs)"
    [ -z "${repo_name}" ] && continue

    # On cherche le repo par nom dans l'orga.
    # S'il existe plusieurs homonymes, on boucle sur tous.
    mapfile -t REPO_IDS < <(
      hammer --csv repository list \
        --organization "${ORG}" \
        --search "name=\"${repo_name}\"" \
        --fields "Id" | tail -n +2 | xargs -n1 echo
    )

    for REPO_ID in "${REPO_IDS[@]}"; do
      [ -z "${REPO_ID}" ] && continue

      REPO_INFO="$(hammer repository info \
        --organization "${ORG}" \
        --id "${REPO_ID}" 2>/dev/null || true)"

      [ -z "${REPO_INFO}" ] && continue

      REPO_NAME="$(extract_field "Name" "${REPO_INFO}")"
      PRODUCT_NAME="$(extract_field "Product" "${REPO_INFO}")"
      CONTENT_TYPE="$(extract_field "Content type" "${REPO_INFO}")"
      PUBLISHED_AT="$(extract_field "Published at" "${REPO_INFO}")"
      RELATIVE_PATH="$(extract_field "Relative path" "${REPO_INFO}")"
      DOWNLOAD_POLICY="$(extract_field "Download policy" "${REPO_INFO}")"
      MIRRORING_POLICY="$(extract_field "Mirroring policy" "${REPO_INFO}")"

      printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$(csv_escape "${CV_NAME}")" \
        "$(csv_escape "${CV_LABEL}")" \
        "$(csv_escape "${REPO_ID}")" \
        "$(csv_escape "${REPO_NAME}")" \
        "$(csv_escape "${PRODUCT_NAME}")" \
        "$(csv_escape "${CONTENT_TYPE}")" \
        "$(csv_escape "${PUBLISHED_AT}")" \
        "$(csv_escape "${RELATIVE_PATH}")" \
        "$(csv_escape "${DOWNLOAD_POLICY}")" \
        "$(csv_escape "${MIRRORING_POLICY}")" \
        >> "${OUT_CSV}"
    done
  done <<< "${REPO_LINES}"
done

echo
echo "Done"
echo "CSV : ${OUT_CSV}"
echo "LOG : ${LOG}"