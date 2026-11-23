#!/usr/bin/env python3
"""Collect short, attributed RSS/Atom news summaries and publisher preview photos."""
import hashlib, html, json, re, sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "news.json"
SOURCES = ROOT / "sources.json"
KEYWORDS = ["купин", "купино", "новосибирск", "новосибирской области", "чистоозер", "чистоозёр"]
EXCLUDE = ["реклама", "промокод"]

def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()

def date_iso(value):
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()

def resolve_article_url(url):
    """Turn Google News RSS redirect links into the publisher's article URL."""
    if "news.google.com" not in (url or "").lower():
        return url
    try:
        req = Request(url, headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept":"text/html,application/xhtml+xml"})
        with urlopen(req, timeout=15) as response:
            final_url = response.geturl()
            page = response.read(500000).decode("utf-8", "ignore")
        if "news.google.com" not in final_url.lower():
            return final_url
        # Some Google News responses expose the publisher URL as canonical metadata.
        patterns = (
            r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)""",
            r"""<meta[^>]+property=["']og:url["'][^>]+content=["']([^"']+)""",
            r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:url["']""",
            r"""<meta[^>]+http-equiv=["']refresh["'][^>]+content=["'][^;]+;\s*url=([^"']+)""",
        )
        for pattern in patterns:
            match = re.search(pattern, page, re.I)
            if match:
                candidate = urljoin(final_url, html.unescape(match.group(1).strip()))
                if candidate.startswith("https://") and "news.google.com" not in candidate.lower():
                    return candidate
    except Exception as exc:
        print("LINK WARN", url[:100], str(exc)[:160], file=sys.stderr)
    return url

def preview_image(url):
    """Resolve publisher pages and read their public preview image."""
    try:
        req = Request(url, headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept":"text/html,application/xhtml+xml"})
        with urlopen(req, timeout=15) as response:
            page = response.read(700000).decode("utf-8", "ignore")
            base = response.geturl()
        patterns = (
            r"""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)""",
            r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']""",
            r"""<meta[^>]+name=["']twitter:image["'][^>]+content=["']([^"']+)""",
            r"""<link[^>]+rel=["']image_src["'][^>]+href=["']([^"']+)""",
        )
        for pattern in patterns:
            match = re.search(pattern, page, re.I)
            if match:
                image = urljoin(base, html.unescape(match.group(1).strip()))
                if image.startswith(("https://", "http://")):
                    return image
        match = re.search(r"""<img[^>]+src=["']([^"']+)""", page, re.I)
        if match:
            image = urljoin(base, html.unescape(match.group(1).strip()))
            if image.startswith(("https://", "http://")):
                return image
    except Exception as exc:
        print("IMAGE WARN", url[:100], str(exc)[:160], file=sys.stderr)
    return ""

def parse(xml, source):
    root = ET.fromstring(xml)
    items = root.findall(".//item")
    atom = False
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        atom = True
    out = []
    for item in items[:30]:
        if atom:
            ns = "{http://www.w3.org/2005/Atom}"
            title = clean(item.findtext(ns+"title"))
            link_node = item.find(ns+"link")
            link = link_node.attrib.get("href", "") if link_node is not None else ""
            summary = clean(item.findtext(ns+"summary") or item.findtext(ns+"content"))
            date = item.findtext(ns+"published") or item.findtext(ns+"updated") or ""
            image = ""
            for tag in (ns+"link",):
                pass
        else:
            title = clean(item.findtext("title"))
            link = (item.findtext("link") or "").strip()
            raw_description = item.findtext("description") or item.findtext("summary") or ""
            summary = clean(raw_description)
            date = item.findtext("pubDate") or item.findtext("published") or ""
            publisher = clean(item.findtext("source"))
            image = ""
            img_match = re.search(r'<img[^>]+src="([^"]+)"', raw_description, re.I)
            if img_match:
                image = urljoin(link, html.unescape(img_match.group(1)))
            for tag in ("{http://search.yahoo.com/mrss/}thumbnail", "{http://search.yahoo.com/mrss/}content", "enclosure"):
                node = item.find(tag)
                if node is not None and node.attrib.get("url"):
                    image = node.attrib["url"]; break
        link = resolve_article_url(link)
        text = (title + " " + summary).lower()
        if not title or not link or any(x in text for x in EXCLUDE): continue
        if not source.get("allow_all", False) and not any(x in text for x in KEYWORDS): continue
        uid = hashlib.sha256(link.split("#")[0].encode()).hexdigest()[:20]
        out.append({"id":uid,"title":title[:240],"summary":summary[:360],"url":link,
                    "source":(publisher if not atom and publisher else source["name"]),"category":source.get("category","Район"),
                    "published_at":date_iso(date),"image":image,"collected_at":datetime.now(timezone.utc).isoformat()})
    return out

def main():
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    by_id = {x["id"]:x for x in old if isinstance(x,dict) and x.get("id")}
    errors = []
    for source in sources:
        if not source.get("enabled") or not source.get("feed"): continue
        try:
            req = Request(source["feed"], headers={"User-Agent":"KupinskiyDistrictNewsBot/1.0"})
            with urlopen(req, timeout=20) as response: entries = parse(response.read(), source)
            for entry in entries:
                previous = by_id.get(entry["id"], {})
                if not entry.get("image") and not previous.get("image"):
                    entry["image"] = preview_image(entry["url"])
                by_id[entry["id"]] = {**previous, **entry, "image":entry.get("image") or previous.get("image","")}
            print(source["name"], len(entries))
        except Exception as exc:
            errors.append(str(exc)); print("WARN", source["name"], exc, file=sys.stderr)
    # Backfill publisher preview photos for older items that predate image extraction.
    for item in sorted(by_id.values(), key=lambda x:x.get("published_at",""), reverse=True)[:60]:
        if not item.get("image"):
            item["image"] = preview_image(item.get("url",""))
    items = sorted(by_id.values(), key=lambda x:x.get("published_at",""), reverse=True)[:250]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(items,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Saved",len(items),"items; errors:",len(errors))

if __name__ == "__main__": main()
