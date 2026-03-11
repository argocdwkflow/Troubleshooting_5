#!/bin/bash
set -euo pipefail

ORG="BP2I Linux"
OUT="/root/repos_export_with_published.csv"

echo '"ORGANIZATION_NAME","PRODUCT","HTTP_PROXY","DOWNLOAD_POLICY","MIRRORING_POLICY","NAME","LABEL","CONTENT_TYPE","CONTENT_LABEL","URL","PUBLISHED_AT"' > "$OUT"

hammer --no-headers --csv repository list \
  --organization "$ORG" \
  --fields "Id" | tr -d '"' | while read -r ID
do
  hammer repository info --id "$ID" | awk -F': ' '
    BEGIN {
      org=""; product=""; http_proxy=""; dpolicy="";
      mpolicy=""; name=""; label=""; ctype="";
      clabel=""; url=""; published="";
      in_product=0; in_http_proxy=0
    }

    /^Organization:/      {org=$2}
    /^Download Policy:/   {dpolicy=$2}
    /^Mirroring Policy:/  {mpolicy=$2}
    /^Name:/ && name==""  {name=$2}
    /^Label:/             {label=$2}
    /^Content Type:/      {ctype=$2}
    /^Content Label:/     {clabel=$2}
    /^Url:/               {url=$2}
    /^Published At:/      {published=$2}

    /^Product:/           {in_product=1; next}
    in_product && /^  Name:/ && product=="" {
      product=$2
      in_product=0
    }

    /^HTTP Proxy:/        {in_http_proxy=1; next}
    in_http_proxy && /^  Name:/ && http_proxy=="" {
      http_proxy=$2
      in_http_proxy=0
    }

    END {
      gsub(/"/, "\"\"", org)
      gsub(/"/, "\"\"", product)
      gsub(/"/, "\"\"", http_proxy)
      gsub(/"/, "\"\"", dpolicy)
      gsub(/"/, "\"\"", mpolicy)
      gsub(/"/, "\"\"", name)
      gsub(/"/, "\"\"", label)
      gsub(/"/, "\"\"", ctype)
      gsub(/"/, "\"\"", clabel)
      gsub(/"/, "\"\"", url)
      gsub(/"/, "\"\"", published)

      printf "\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\",\"%s\"\n",
             org, product, http_proxy, dpolicy, mpolicy, name, label, ctype, clabel, url, published
    }
  ' >> "$OUT"
done

echo "Fichier généré : $OUT"