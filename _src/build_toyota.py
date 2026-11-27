"""Build the Toyota kiosk data + images from the cache made by fetch_toyota.py.

For each of the vehicle ranges on toyota.co.za/vehicles:
  - banner photo, model tagline, body-type categories, price range, monthly-from price
  - feature stories (title, text, photo), highlight tiles (photo + labels), safety items
  - photo gallery (exterior / interior)
  - every grade: price, monthly, engine, transmission, fuel, consumption, drive, seats,
    top speed, EV figures, key stats, spec-sheet PDF, and every colour with its own car photo
Images are downloaded once, converted to WebP sized for a 1080x1920 portrait screen (HD),
and named by a hash of their source URL. Writes ../data.js  (window.CATALOG = {...})
"""
import re, json, gzip, hashlib, html, io, pathlib, urllib.request, concurrent.futures as cf
from PIL import Image
import qrcode

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
CACHE = HERE / "cache"
IMG = ROOT / "img"; IMG.mkdir(exist_ok=True)
QR = ROOT / "qr"; QR.mkdir(exist_ok=True)
SITE = "https://www.toyota.co.za"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"

MAX_GALLERY = 14
MAX_FEATURES = 8
MAX_TIPS = 8
# body-type groups shown on the kiosk, in order: (key on toyota.co.za, label)
CATEGORIES = [("SUV", "SUV"), ("Bakkie", "Bakkie"), ("Hatch", "Hatch"), ("Sedan", "Sedan"),
              ("Hybrid & Electric", "Hybrid & Electric"), ("Performance", "GR Performance"),
              ("offRoad", "Off-Road"), ("People Carriers", "People Carriers"), ("Commercial", "Commercial")]

jobs = {}   # local file name -> (url, max width, max height, kind)


def load(name):
    return json.loads(gzip.decompress((CACHE / f"{name}.json.gz").read_bytes()))


def clean(s):
    s = html.unescape(str(s or "")).replace(" ", " ").replace("�", "'")
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip(" \n'")


def img(url, w, h=None, kind="photo"):
    """Register an image for download; returns its local path (or '' if none)."""
    if not url or not isinstance(url, str) or url.endswith(".svg"):
        return ""
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + f"_{w}.webp"
    jobs[name] = (url, w, h or w, kind)
    return "img/" + name


def first_url(area):
    """Desktop URL of the first image in an Apostrophe 'area' ({items:[{url:{desktop}}]})."""
    for it in (area or {}).get("items", []) if isinstance(area, dict) else []:
        u = (it.get("url") or {}).get("desktop")
        if u:
            return u
    return ""


def all_urls(obj):
    return re.findall(r'"desktop":\s*"(https://[^"]+\.(?:jpg|jpeg|png|webp))"', json.dumps(obj))


def rich(area):
    return clean(" ".join(it.get("content", "") for it in (area or {}).get("items", []) if isinstance(it, dict)))


def parse_range(r, page):
    items = (page.get("payloadData") or [{}])[0].get("content", {}).get("items", [])
    banner, features, tips, gallery, safety = "", [], [], [], []
    pending = None   # a text block waiting for its photo

    for it in items:
        t = it.get("type")
        if t in ("cms-adaptive-content-banner", "cms-banner", "cms-extended-tabbed-banner") and not banner:
            # Only the slide's main photo or the background photo: titleImage fields hold logos,
            # modal buttons hold icons and feature close-ups.
            for s in it.get("slides") or []:
                banner = banner or first_url(s.get("image"))
            banner = banner or first_url(it.get("backgroundImage")) or first_url(it.get("image"))
        elif t == "cms-text":
            d = it.get("htmlTextData") or {}
            title, text = clean(d.get("title")), clean(d.get("subtitle"))
            body = rich(d.get("content"))
            if title:
                pending = {"title": title, "text": text or body, "img": ""}
                features.append(pending)
            elif pending and (text or body) and not pending["img"]:
                pending["text"] = (pending["text"] + "\n\n" + (text or body)).strip()
        elif t == "cms-single-image":
            u = first_url(it.get("image"))
            if u and pending and not pending["img"]:
                pending["img"] = u
        elif t == "cms-two-column":
            d = it.get("textWithImageData") or {}
            u = first_url(d.get("image"))
            title = clean(d.get("title"))
            if title or u:
                features.append({"title": title, "text": rich(d.get("description")), "img": u})
            pending = None
        elif t in ("cms-gallery-grid-with-tooltips", "cms-tabbed-gallery-grid-with-tooltips", "cms-tabbed-gallery-grid-with-tooltips-cards"):
            for tile in re.findall(r'\{"id": "[^"]+", "image": .*?"toolTips": \[.*?\]\}', json.dumps(it, ensure_ascii=False)):
                try:
                    tile = json.loads(tile)
                except ValueError:
                    continue
                u = first_url(tile.get("image"))
                labels = [clean(x.get("heading")) for x in tile.get("toolTips", []) if clean(x.get("heading"))]
                if u and labels:
                    tips.append({"img": u, "labels": labels,
                                 "text": " ".join(clean(x.get("content")) for x in tile.get("toolTips", []) if clean(x.get("content")))})
        elif t == "cms-gallery":
            for g in it.get("galleryData", []):
                for gi in g.get("imageGalleryItems", []):
                    u = first_url(gi.get("slideImage"))
                    if u:
                        gallery.append({"img": u, "title": clean(gi.get("slideTitle")), "tab": clean(g.get("tabLabel"))})
        elif t == "cms-deck":
            for c in it.get("iconWithTextData") or []:
                title = clean(c.get("title"))
                if title:
                    safety.append({"title": title, "text": rich(c.get("cardContent"))})

    if not banner:   # no banner photo on the page: use the first exterior gallery shot
        ext = [g for g in gallery if "ext" in g["tab"].lower()] or gallery
        banner = ext[0]["img"] if ext else ""

    # keep features that say something; dedupe
    seen, feats = set(), []
    for f in features:
        key = f["title"].lower()
        if key in seen or (not f["text"] and not f["img"]):
            continue
        seen.add(key)
        feats.append(f)
    return banner, feats[:MAX_FEATURES], tips[:MAX_TIPS], gallery[:MAX_GALLERY], safety


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def dash(v):
    v = clean(v)
    return "" if v in ("-", "", "None", "null") else v


def parse_grade(m, range_slug):
    colours = []
    for c in m.get("colourSelectors") or []:
        u = (c.get("colourImage") or {}).get("desktop")
        if not u:
            continue
        colours.append({"name": clean(c.get("colourTitle")), "hex": c.get("colourCode") or "#999",
                        "hex2": c.get("colourCode2") or "", "img": img(u, 1400, 700, "car")})
    side = (m.get("sideHighImageUrl") or {}).get("desktop")
    front = (m.get("frontHighImageUrl") or {}).get("desktop")
    stats = [[clean(s.get("statName")), clean(s.get("statValue"))] for s in m.get("vehicleStats") or [] if clean(s.get("statValue"))]
    specs = [["Engine", dash(m.get("engine")) and dash(m.get("engine")) + " litre"],
             ["Transmission", dash(m.get("transmission"))], ["Fuel", dash(m.get("fuelType"))],
             ["Fuel consumption", dash(m.get("fuelcon")) and dash(m.get("fuelcon")) + " l/100 km"],
             ["Drive", dash(m.get("driveSystem")).strip("/")], ["Seats", dash(m.get("seats"))],
             ["Top speed", dash(m.get("topSpeed")) and dash(m.get("topSpeed")) + " km/h"],
             ["Body", {"suv": "SUV", "mpv": "MPV", "mini-van-taxi": "Minibus"}.get(dash(m.get("bodyType")).lower(), dash(m.get("bodyType")).title())],
             ["EV range", dash(m.get("evRange"))], ["Battery", dash(m.get("batteryCapacity"))],
             ["Electric motor", dash(m.get("electricMotorPower"))],
             ["Emissions", dash(m.get("euroEmissionStatus"))], ["Payload class", dash(m.get("tonnageHino"))]]
    specs = [[k, v] for k, v in specs if v]
    pdf = m.get("specDownload") or ""
    qr_pdf = ""
    if pdf.startswith("http"):
        qr_pdf = f"qr/spec_{hashlib.sha1(pdf.encode()).hexdigest()[:12]}.png"
        make_qr(pdf, ROOT / qr_pdf)
    return {
        "id": str(m.get("id") or m.get("code")), "code": m.get("code"), "name": clean(m.get("name")),
        "price": num(m.get("specialPrice")) or num(m.get("price")), "monthly": num(m.get("monthlyFromPrice")),
        "headline": clean(m.get("specHeader")), "blurb": clean(m.get("specSubHeader")),
        "stats": stats, "specs": specs, "pdfQr": qr_pdf,
        "side": img(side, 1400, 700, "car"), "front": img(front, 1400, 700, "car"),
        "colours": colours,
    }


def make_qr(url, path):
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    q.add_data(url); q.make(fit=True)
    q.make_image(fill_color="black", back_color="white").save(path)


def fetch(name):
    dst = IMG / name
    if dst.exists():
        return
    url, w, h, kind = jobs[name]
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90).read()
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGBA") if (im.mode in ("RGBA", "LA", "P") and kind == "car") else im.convert("RGB")
    im.thumbnail((w, h), Image.LANCZOS)
    im.save(dst, "WEBP", quality=80 if kind != "car" else 85, method=5)


def main():
    listing = load("_vehicles")
    by_cat = listing["rangesByCategory"]
    out = []
    for r in by_cat["All"]:
        slug = r["rangeSlug"].lower()
        try:
            page = load(slug)
        except FileNotFoundError:
            print("no page:", slug)
            continue
        banner, feats, tips, gallery, safety = parse_range(r, page)
        grades = [parse_grade(m, slug) for m in page.get("models") or []]
        grades = [g for g in grades if g["colours"] or g["side"] or g["front"]]
        if not grades:
            print("no grades:", slug)
            continue
        grades.sort(key=lambda g: g["price"] or 9e12)
        hero_side = (r.get("heroModelSideImage") or {}).get("desktop")
        hero_front = (r.get("heroModelFrontImage") or {}).get("desktop")
        cats = [k for k, _ in CATEGORIES if any(x.get("rangeCode") == r.get("rangeCode") for x in by_cat.get(k, []))]
        prices = [g["price"] for g in grades if g["price"]]
        make_qr(f"{SITE}/vehicles/{slug}", QR / f"{slug}.png")
        out.append({
            "id": slug, "name": clean(r["name"]), "tagline": clean(r.get("subtitle")), "cats": cats,
            "minPrice": min(prices) if prices else num(r.get("minPrice")),
            "maxPrice": max(prices) if prices else num(r.get("maxPrice")),
            "monthly": num(r.get("monthlyFromPrice")),
            "card": img(hero_front or hero_side, 900, 500, "car"),
            "side": img(hero_side, 1400, 700, "car"),
            "banner": img(banner, 2000, 1400) if banner else "",
            "features": [{"title": f["title"], "text": f["text"], "img": img(f["img"], 1600, 1100)} for f in feats],
            "tips": [{"img": img(t["img"], 1400, 1100), "labels": t["labels"], "text": t["text"]} for t in tips],
            "gallery": [{"img": img(g["img"], 1800, 1300), "thumb": img(g["img"], 360, 260), "title": g["title"], "tab": g["tab"]} for g in gallery],
            "safety": safety,
            "grades": grades,
            "qr": f"qr/{slug}.png",
        })

    print(len(out), "ranges,", sum(len(r["grades"]) for r in out), "grades,", len(jobs), "images")
    errors = []
    def safe_fetch(n):
        try:
            fetch(n)
        except Exception as e:
            errors.append((n, jobs[n][0], str(e)))
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(safe_fetch, jobs))
    for n, u, e in errors[:10]:
        print("image failed:", u, e)
    bad = {"img/" + n for n, _, _ in errors}
    # drop references to images that failed, so the kiosk never shows a broken picture
    def scrub(o):
        if isinstance(o, dict):
            return {k: ("" if isinstance(v, str) and v in bad else scrub(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [scrub(x) for x in o]
        return o
    out = scrub(out)
    for r in out:
        r["gallery"] = [g for g in r["gallery"] if g["img"]]
        r["features"] = [f for f in r["features"] if f["img"] or f["text"]]
        r["tips"] = [t for t in r["tips"] if t["img"]]
        for g in r["grades"]:
            g["colours"] = [c for c in g["colours"] if c["img"]]

    keep = set(jobs)
    for f in IMG.iterdir():
        if f.name not in keep:
            f.unlink()
    data = {"categories": [[k, label] for k, label in CATEGORIES if any(k in r["cats"] for r in out)], "ranges": out}
    (ROOT / "data.js").write_text("window.CATALOG = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("done,", len(errors), "image errors")


if __name__ == "__main__":
    main()
