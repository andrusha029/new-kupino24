#!/usr/bin/env python3
"""Collect short, attributed RSS/Atom news summaries for the district site."""
import hashlib, html, json, re, sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
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
        else:
            title = clean(item.findtext("title"))
            link = (item.findtext("link") or "").strip()
            summary = clean(item.findtext("description") or item.findtext("summary"))
            date = item.findtext("pubDate") or item.findtext("published") or ""
            publisher = clean(item.findtext("source"))
        text = (title + " " + summary).lower()
        if not title or not link or any(x in text for x in EXCLUDE): continue
        if not source.get("allow_all", False) and not any(x in text for x in KEYWORDS): continue
        uid = hashlib.sha256(link.split("#")[0].encode()).hexdigest()[:20]
        out.append({"id":uid,"title":title[:240],"summary":summary[:360],"url":link,
                    "source":(publisher if not atom and publisher else source["name"]),"category":source.get("category","Район"),
                    "published_at":date_iso(date),"collected_at":datetime.now(timezone.utc).isoformat()})
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
            for entry in entries: by_id.setdefault(entry["id"], entry)
            print(source["name"], len(entries))
        except Exception as exc:
            errors.append(str(exc)); print("WARN", source["name"], exc, file=sys.stderr)
    items = sorted(by_id.values(), key=lambda x:x.get("published_at",""), reverse=True)[:250]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(items,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Saved",len(items),"items; errors:",len(errors))

if __name__ == "__main__": main()
