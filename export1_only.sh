hammer --no-headers --csv repository list \
  --organization "BP2I Linux" \
  --fields "Id" | tr -d '"' | while read -r ID
do
  hammer repository info --id "$ID" | awk -F': ' '
    BEGIN {
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
    in_product && /^  Name:/ && product=="" {product=$2; in_product=0}
    /^HTTP Proxy:/        {in_http_proxy=1; next}
    in_http_proxy && /^  Name:/ && http_proxy=="" {http_proxy=$2; in_http_proxy=0}
    END {
      print "Organization Name : " org
      print "Product           : " product
      print "HTTP Proxy        : " http_proxy
      print "Download Policy   : " dpolicy
      print "Mirroring Policy  : " mpolicy
      print "Name              : " name
      print "Label             : " label
      print "Content Type      : " ctype
      print "Content Label     : " clabel
      print "Url               : " url
      print "Published At      : " published
      print "------------------------------------------------------------"
    }'
done