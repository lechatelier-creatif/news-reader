#!/usr/bin/env python3
"""Robot : récupère les flux RSS, extrait l'article en mode lecteur (Readability), écrit news.json."""
import json, hashlib, re, time, os, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin
import feedparser, requests
from readability import Document
from lxml import html as LH

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
MAX_PER_FEED = 15
MAX_AGE_DAYS = 7
OUT = os.path.join(HERE, "news.json")

ALLOWED = {"p","h2","h3","h4","ul","ol","li","blockquote","strong","em","b","i","a","img","figure","figcaption","br","pre","code","table","thead","tbody","tr","td","th"}
JUNK = re.compile(r"(newsletter|abonnez|partager|share|related|a-lire|lire-aussi|advert|sponsor|comment|social|outbrain|taboola)", re.I)

def clean(content_html, base):
    try:
        root = LH.fromstring(content_html)
    except Exception:
        return ""
    for bad in root.xpath("//script|//style|//iframe|//form|//button|//noscript|//svg|//aside|//nav|//footer|//input"):
        bad.drop_tree()
    for el in root.xpath("//*[@class or @id]"):
        if el.getparent() is not None and el.tag not in ("p", "img") and JUNK.search((el.get("class") or "") + " " + (el.get("id") or "")):
            el.drop_tree()
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        if el.tag == "img":
            src = el.get("data-src") or el.get("data-lazy-src") or el.get("src") or ""
            if not src or src.startswith("data:"):
                el.drop_tree(); continue
            alt = el.get("alt", "")
            el.attrib.clear(); el.set("src", urljoin(base, src)); el.set("alt", alt); el.set("loading", "lazy")
        elif el.tag == "a":
            href = el.get("href", "")
            el.attrib.clear()
            if href: el.set("href", urljoin(base, href))
        else:
            el.attrib.clear()
            if el.tag not in ALLOWED and el.tag not in ("html", "body", "div", "section", "article", "span") and el.getparent() is not None:
                el.drop_tag()
    for p in root.xpath("//p"):
        t = p.text_content().lower()
        if "cookies" in t and ("accepte" in t or "traceurs" in t) or "contenu est bloqué" in t:
            p.drop_tree()
    out = LH.tostring(root, encoding="unicode")
    out = re.sub(r"</?(html|body|div|section|article|span)[^>]*>", "", out)
    out = re.sub(r"<p>\s*(&nbsp;)?\s*</p>", "", out)
    return out.strip()

def og_image(page, base):
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', page)
    return urljoin(base, m.group(1)) if m else ""

def extract(item):
    try:
        r = requests.get(item["url"], headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr"}, timeout=20)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        page = r.text
        doc = Document(page)
        body = clean(doc.summary(html_partial=True), r.url)
        if not item.get("image"):
            item["image"] = og_image(page, r.url)
        if len(re.sub("<[^>]+>", "", body)) > 300:
            item["content"] = body
    except Exception as e:
        print("  ! extraction", item["url"], e, file=sys.stderr)
    if not item.get("content"):
        item["content"] = item.get("_summary") or "<p>Contenu indisponible, ouvre l'article original.</p>"
    item.pop("_summary", None)
    text = re.sub("<[^>]+>", " ", item["content"])
    item["readingTime"] = max(1, round(len(text.split()) / 220))
    item["excerpt"] = re.sub(r"\s+", " ", text).strip()[:220]
    return item

def first_image(entry):
    for k in ("media_content", "media_thumbnail"):
        for m in entry.get(k, []) or []:
            if m.get("url"): return m["url"]
    for l in entry.get("links", []):
        if l.get("type", "").startswith("image"): return l.get("href")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', entry.get("summary", "") or "")
    return m.group(1) if m else ""

def main():
    cfg = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
    old = {}
    if os.path.exists(OUT):
        try:
            old = {a["id"]: a for a in json.load(open(OUT, encoding="utf-8"))["articles"]}
        except Exception:
            pass
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    items, todo = [], []
    for cat in cfg["categories"]:
        for src in cat["sources"]:
            print(f"[{cat['name']}] {src['name']}")
            try:
                raw = requests.get(src["feed"], headers={"User-Agent": UA}, timeout=20).content
                feed = feedparser.parse(raw)
            except Exception as e:
                print("  ! flux", e, file=sys.stderr); continue
            for e in feed.entries[:MAX_PER_FEED]:
                url = e.get("link")
                if not url: continue
                t = e.get("published_parsed") or e.get("updated_parsed")
                ts = time.mktime(t) if t else time.time()
                if ts < cutoff: continue
                aid = hashlib.md5(url.encode()).hexdigest()[:12]
                if aid in old and old[aid].get("content"):
                    a = old[aid]; a["category"] = cat["id"]; items.append(a); continue
                a = {"id": aid, "url": url, "title": e.get("title", "").strip(), "source": src["name"],
                     "category": cat["id"], "date": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                     "image": first_image(e), "_summary": e.get("summary", "")}
                items.append(a); todo.append(a)
    print(f"{len(todo)} nouveaux articles à extraire…")
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(extract, todo))
    seen, uniq = set(), []
    for a in sorted(items, key=lambda a: a["date"], reverse=True):
        if a["id"] in seen: continue
        seen.add(a["id"]); uniq.append(a)
    cats = [{"id": c["id"], "name": c["name"], "icon": c.get("icon", ""), "sources": [s["name"] for s in c["sources"]]} for c in cfg["categories"]]
    json.dump({"updated": datetime.now(timezone.utc).isoformat(), "categories": cats, "articles": uniq},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"OK : {len(uniq)} articles -> news.json")

if __name__ == "__main__":
    main()
