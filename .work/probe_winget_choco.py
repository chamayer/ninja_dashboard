import httpx, json

with httpx.Client(timeout=15.0) as c:
    r = c.post(
        "https://cdn.winget.microsoft.com/cache/api/manifestSearch",
        json={"Query": {"KeyWord": "chrome", "MatchType": "Substring"}, "MaximumResults": 5},
    )
    print("winget", r.status_code, "content-type", r.headers.get("content-type"))
    try:
        payload = r.json()
    except Exception as e:
        print("  json err:", e, "body head:", r.text[:200])
    else:
        print("  Data len:", len(payload.get("Data") or []))
        print("  sample:", (payload.get("Data") or [{}])[0])

    r = c.get(
        "https://community.chocolatey.org/api/v2/Search()",
        params={"searchTerm": "'chrome'", "$top": "5", "$filter": "IsLatestVersion"},
    )
    print("chocolatey", r.status_code, "content-type", r.headers.get("content-type"))
    body = r.text
    print("  body chars:", len(body))
    print("  first 300:", body[:300])
