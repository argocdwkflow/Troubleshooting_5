#!/bin/bash
set -euo pipefail

ORG=""
OUT="/root/repos_export_with_published.csv"

FIELDS="Organization,Product/name,Http proxy/name,Http proxy/http proxy policy,Download policy,Mirroring policy,Name,Label,Content type,Content label,Url,Published at"

echo '"ORGANIZATION_NAME","PRODUCT_NAME","HTTP_PROXY_NAME","HTTP_PROXY_POLICY","DOWNLOAD_POLICY","MIRRORING_POLICY","NAME","LABEL","CONTENT_TYPE","CONTENT_LABEL","URL","PUBLISHED_AT"' > "$OUT"

hammer --no-headers --csv repository list \
  --organization "$ORG" \
  --fields "Id" | tr -d '"' | while read -r ID
do
  hammer --csv repository info --id "$ID" --fields "$FIELDS" | tail -n +2 >> "$OUT"
done

echo "Export terminé : $OUT"