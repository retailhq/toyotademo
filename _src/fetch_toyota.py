"""Download the Toyota South Africa vehicle range data (toyota.co.za/vehicles + every model page).

Saves page data (Next.js __NEXT_DATA__ pageProps) gzipped in cache/:
  cache/_vehicles.json.gz        the range list, grouped by body type
  cache/<range-slug>.json.gz     each model page: grades, colours, stats, features, gallery
Delete cache/ to pick up site changes, then run build_toyota.py.
"""
import re, json, gzip, time, urllib.request, urllib.error, pathlib, concurrent.futures as cf

HERE = pathlib.Path(__file__).parent
CACHE = HERE / "cache"; CACHE.mkdir(exist_ok=True)
SITE = "https://www.toyota.co.za"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"


def get(url):
    for attempt in range(6):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503) or attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))


def page_props(url):
    html = get(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1))["props"]["pageProps"]


def save(name, obj):
    (CACHE / f"{name}.json.gz").write_bytes(gzip.compress(json.dumps(obj, ensure_ascii=False).encode("utf-8")))


def main():
    listing = page_props(SITE + "/vehicles")
    save("_vehicles", listing)
    ranges = listing["rangesByCategory"]["All"]
    print(len(ranges), "ranges")

    def one(r):
        slug = r["rangeSlug"].lower()
        f = CACHE / f"{slug}.json.gz"
        if f.exists():
            return slug, "cached"
        try:
            save(slug, page_props(f"{SITE}/vehicles/{slug}"))
            return slug, "ok"
        except Exception as e:        # keep going; the build skips ranges without a page
            return slug, f"FAILED {e}"

    with cf.ThreadPoolExecutor(3) as ex:
        for slug, status in ex.map(one, ranges):
            print(f"  {slug:32s} {status}")


if __name__ == "__main__":
    main()
