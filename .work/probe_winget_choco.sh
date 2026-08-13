#!/bin/sh
set -x
curl -s -o /tmp/winget_resp.json -w 'winget: http=%{http_code} time=%{time_total}\n' \
  -X POST 'https://cdn.winget.microsoft.com/cache/api/manifestSearch' \
  -H 'Content-Type: application/json' \
  -d '{"Query":{"KeyWord":"chrome","MatchType":"Substring"},"MaximumResults":5}'
echo '--- winget response (first 300 chars) ---'
head -c 300 /tmp/winget_resp.json; echo

curl -s -o /tmp/choco_resp.xml -w 'chocolatey: http=%{http_code} time=%{time_total}\n' \
  "https://community.chocolatey.org/api/v2/Search()?searchTerm=%27chrome%27&\$top=5&\$filter=IsLatestVersion"
echo '--- chocolatey response (first 300 chars) ---'
head -c 300 /tmp/choco_resp.xml; echo
