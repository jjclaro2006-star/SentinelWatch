import requests, urllib3
urllib3.disable_warnings()
r = requests.get("https://data.humdata.org/api/3/action/package_search?q=chile+mining+concessions&rows=5", timeout=10)
data = r.json()
results = data.get("result", {}).get("results", [])
for pkg in results[:5]:
    print(pkg.get("title"))
    for res in pkg.get("resources", [])[:2]:
        print("  " + res.get("name", "") + "  " + res.get("url", "")[:100])
