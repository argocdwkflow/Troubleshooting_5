#!/bin/bash
set -euo pipefail

CSV="/root/export_import/repos_export_with_published_v2_2.csv"
ORG_TARGET="xxxx"

# yes = crée aussi la synchro
SYNC_AFTER_CREATE="no"

# yes = affiche les commandes sans les exécuter
DRY_RUN="no"

log() {
  echo "[$(date '+%F %T')] $*"
}

run_cmd() {
  if [[ "$DRY_RUN" == "yes" ]]; then
    printf '[DRY-RUN] '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

trim_quotes() {
  local v="$1"
  v="${v#\"}"
  v="${v%\"}"
  v="${v//\"\"/\"}"
  printf '%s' "$v"
}

product_exists() {
  local product="$1"
  hammer --no-headers product list \
    --organization "$ORG_TARGET" \
    --search "name=\"$product\"" | grep -q .
}

repo_exists() {
  local product="$1"
  local repo="$2"
  hammer --no-headers repository list \
    --organization "$ORG_TARGET" \
    --product "$product" \
    --search "name=\"$repo\"" | grep -q .
}

http_proxy_exists() {
  local proxy="$1"
  hammer --no-headers http-proxy list \
    --search "name=\"$proxy\"" | grep -q .
}

create_product_if_needed() {
  local product="$1"

  if product_exists "$product"; then
    log "Product déjà existant : $product"
  else
    log "Création product : $product"
    run_cmd hammer product create \
      --organization "$ORG_TARGET" \
      --name "$product"
  fi
}

create_repo_if_needed() {
  local name="$1"
  local label="$2"
  local content_type="$3"
  local mirroring_policy="$4"
  local published_at="$5"
  local download_policy="$6"
  local http_proxy_name="$7"
  local http_proxy_policy="$8"
  local product_name="$9"

  if repo_exists "$product_name" "$name"; then
    log "Repository déjà existant : [$product_name] / [$name]"
    return 0
  fi

  log "Création repository : [$product_name] / [$name]"
  log "  label             = $label"
  log "  content type      = $content_type"
  log "  mirroring policy  = $mirroring_policy"
  log "  download policy   = $download_policy"
  log "  http proxy name   = $http_proxy_name"
  log "  http proxy policy = $http_proxy_policy"
  log "  upstream url      = $published_at"

  cmd=(
    hammer repository create
    --organization "$ORG_TARGET"
    --product "$product_name"
    --name "$name"
    --label "$label"
    --content-type "$content_type"
    --url "$published_at"
  )

  if [[ -n "$download_policy" ]]; then
    cmd+=(--download-policy "$download_policy")
  fi

  if [[ -n "$mirroring_policy" ]]; then
    cmd+=(--mirroring-policy "$mirroring_policy")
  fi

  if [[ -n "$http_proxy_policy" ]]; then
    cmd+=(--http-proxy-policy "$http_proxy_policy")
  fi

  if [[ "$http_proxy_policy" == "use_selected_http_proxy" && -n "$http_proxy_name" ]]; then
    if http_proxy_exists "$http_proxy_name"; then
      cmd+=(--http-proxy "$http_proxy_name")
    else
      log "ATTENTION: proxy [$http_proxy_name] introuvable sur le Satellite cible, création sans --http-proxy"
    fi
  fi

  run_cmd "${cmd[@]}"
}

sync_repo_if_needed() {
  local product_name="$1"
  local repo_name="$2"

  if [[ "$SYNC_AFTER_CREATE" != "yes" ]]; then
    return 0
  fi

  log "Synchronisation repository : [$product_name] / [$repo_name]"
  run_cmd hammer repository synchronize \
    --organization "$ORG_TARGET" \
    --product "$product_name" \
    --name "$repo_name"
}

if [[ ! -f "$CSV" ]]; then
  echo "Fichier CSV introuvable : $CSV" >&2
  exit 1
fi

# Parse CSV robuste sans python
tail -n +2 "$CSV" | awk -v FPAT='([^,]*)|(\"([^\"]|\"\")*\")' '
{
  for (i=1; i<=NF; i++) {
    gsub(/^"/, "", $i)
    gsub(/"$/, "", $i)
    gsub(/""/, "\"", $i)
  }
  print $1 "\t" $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6 "\t" $7 "\t" $8 "\t" $9 "\t" $10 "\t" $11
}' | while IFS=$'\t' read -r \
  NAME LABEL CONTENT_TYPE CONTENT_LABEL MIRRORING_POLICY URL PUBLISHED_AT DOWNLOAD_POLICY HTTP_PROXY_NAME HTTP_PROXY_POLICY PRODUCT_NAME
do
  NAME=$(trim_quotes "$NAME")
  LABEL=$(trim_quotes "$LABEL")
  CONTENT_TYPE=$(trim_quotes "$CONTENT_TYPE")
  CONTENT_LABEL=$(trim_quotes "$CONTENT_LABEL")
  MIRRORING_POLICY=$(trim_quotes "$MIRRORING_POLICY")
  URL=$(trim_quotes "$URL")
  PUBLISHED_AT=$(trim_quotes "$PUBLISHED_AT")
  DOWNLOAD_POLICY=$(trim_quotes "$DOWNLOAD_POLICY")
  HTTP_PROXY_NAME=$(trim_quotes "$HTTP_PROXY_NAME")
  HTTP_PROXY_POLICY=$(trim_quotes "$HTTP_PROXY_POLICY")
  PRODUCT_NAME=$(trim_quotes "$PRODUCT_NAME")

  if [[ -z "$NAME" || -z "$PRODUCT_NAME" || -z "$CONTENT_TYPE" || -z "$PUBLISHED_AT" ]]; then
    log "Entrée ignorée car incomplète : PRODUCT=[$PRODUCT_NAME] NAME=[$NAME] CONTENT_TYPE=[$CONTENT_TYPE] PUBLISHED_AT=[$PUBLISHED_AT]"
    continue
  fi

  create_product_if_needed "$PRODUCT_NAME"

  create_repo_if_needed \
    "$NAME" \
    "$LABEL" \
    "$CONTENT_TYPE" \
    "$MIRRORING_POLICY" \
    "$PUBLISHED_AT" \
    "$DOWNLOAD_POLICY" \
    "$HTTP_PROXY_NAME" \
    "$HTTP_PROXY_POLICY" \
    "$PRODUCT_NAME"

  sync_repo_if_needed "$PRODUCT_NAME" "$NAME"
done

log "Import terminé."