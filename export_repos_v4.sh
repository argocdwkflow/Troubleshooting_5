#!/bin/bash
set -euo pipefail

ORG=""
OUT="/root/repos_export_with_published.csv"

echo '"ORGANIZATION_NAME","PRODUCT_NAME","HTTP_PROXY_NAME","HTTP_PROXY_POLICY","DOWNLOAD_POLICY","MIRRORING_POLICY","NAME","LABEL","CONTENT_TYPE","CONTENT_LABEL","URL","PUBLISHED_AT"' > "$OUT"

hammer --no-headers --csv repository list \
  --organization "$ORG" \
  --fields "Id" | tr -d '"' | while read -r ID
do
  hammer repository info --id "$ID" | awk -F': ' '
    BEGIN {
      org=""
      product_name=""
      http_proxy_name=""
      http_proxy_policy=""
      download_policy=""
      mirroring_policy=""
      name=""
      label=""
      content_type=""
      content_label=""
      url=""
      published_at=""
      section=""
    }

    /^[[:space:]]*$/ { next }

    /^Organization:/            { org=$2; next }
    /^Download Policy:/         { download_policy=$2; next }
    /^Mirroring Policy:/        { mirroring_policy=$2; next }
    /^HTTP Proxy Policy:/       { http_proxy_policy=$2; next }
    /^Label:/                   { label=$2; next }
    /^Content Type:/            { content_type=$2; next }
    /^Content Label:/           { content_label=$2; next }
    /^Url:/                     { url=$2; next }
    /^Published At:/            { published_at=$2; next }

    /^Name:/ && name=="" && section=="" { name=$2; next }

    /^Product:/                 { section="product"; next }
    /^HTTP Proxy:/              { section="http_proxy"; next }
    /^GPG Key:/                 { section=""; next }
    /^Sync:/                    { section=""; next }
    /^Publish Settings:/        { section=""; next }

    /^  Name:/ && section=="product" && product_name=="" {
      product_name=$2
      next
    }

    /^  Name:/ && section=="http_proxy" && http_proxy_name=="" {
      http_proxy_name=$2
      next
    }

    /^  HTTP Proxy Policy:/ && section=="http_proxy" && http_proxy_policy=="" {
      http_proxy_policy=$2
      next
    }

    END {
      gsub(/"/, "\"\"", org)
      gsub(/"/, "\"\"", product_name)
      gsub(/"/, "\"\"", http_proxy_name)
      gsub(/"/, "\"\"", http_proxy_policy)
      gsub(/"/, "\"\"", download_policy)
      gsub(/"/, "\"\"", mirroring_policy)
      gsub(/"/, "\"\"", name)
      gsub(/"/, "\"\"", label)
      gsub(/"/, "\"\"", content_type)
      gsub(/"/, "\"\"", content_label)
      gsub(/"/, "\"\"", url)
      gsub(/"/, "\"\"", published_at)

      printf "\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\"\n",
             org, product_name, http_proxy_name, http_proxy_policy,
             download_policy, mirroring_policy, name, label,
             content_type, content_label, url, published_at
    }
  ' >> "$OUT"
done

echo "Export terminé : $OUT"