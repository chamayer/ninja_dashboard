import httpx

urls = [
    # v2 Search — canonical shape
    "https://community.chocolatey.org/api/v2/Search()?searchTerm='chrome'&$filter=IsLatestVersion",
    # v2 Packages with filter
    "https://community.chocolatey.org/api/v2/Packages()?$filter=IsLatestVersion&$top=5&searchTerm='chrome'",
    # v2 Search without filter
    "https://community.chocolatey.org/api/v2/Search()?searchTerm='chrome'&$top=5",
    # NuGet v3 - service index
    "https://community.chocolatey.org/api/v3/index.json",
    # community feed (nuget style)
    "https://community.chocolatey.org/api/v2/",
]

with httpx.Client(
    timeout=15.0,
    headers={"User-Agent": "ninja-dashboard/probe (+ops)"},
    follow_redirects=True,
) as c:
    for u in urls:
        r = c.get(u)
        print(r.status_code, u[:90])
        print(" head:", r.text[:180].replace("\n", " "))
