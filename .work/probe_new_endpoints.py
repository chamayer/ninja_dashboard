import httpx
from urllib.parse import quote

with httpx.Client(
    timeout=15.0,
    headers={"User-Agent": "ninja-dashboard/intel-winget (+ops)", "Accept": "application/json"},
    follow_redirects=True,
) as c:
    r = c.get("https://api.winget.run/v2/packages", params={"query": "chrome", "take": 3})
    print("winget", r.status_code, "ct=", r.headers.get("content-type"))
    print("  body head:", r.text[:250])
    if r.status_code == 200:
        b = r.json()
        pk = b.get("Packages") or b.get("packages") or []
        print("  Packages len:", len(pk))
        if pk:
            print("  sample keys:", sorted((pk[0] or {}).keys())[:8])

with httpx.Client(
    timeout=15.0,
    headers={"User-Agent": "ninja-dashboard/intel-chocolatey (+ops)"},
    follow_redirects=True,
) as c:
    q = quote("chrome", safe="")
    url = f"https://community.chocolatey.org/api/v2/Search()?searchTerm=%27{q}%27&$filter=IsLatestVersion&$top=5"
    r = c.get(url)
    print("choco", r.status_code, "ct=", r.headers.get("content-type"))
    print("  body head:", r.text[:250])
    print("  tags count in body:", r.text.count("<d:Tags>"))
    print("  title count in body:", r.text.count("<title"))
