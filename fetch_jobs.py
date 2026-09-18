"""
easyjob collector
Fetches remote jobs from free public job feeds and saves them to jobs.json.
Uses only Python's standard library, so nothing needs to be installed.
Each source is wrapped in try/except: if one fails, the others still work.
"""

import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

OUTPUT_FILE = "jobs.json"
MAX_AGE_DAYS = 45      # drop jobs older than this
MAX_JOBS = 2000        # keep the file a reasonable size
EXCERPT_LENGTH = 240   # we only keep a short preview and link to the original

HEADERS = {"User-Agent": "easyjob-aggregator/1.0 (links back to original postings)"}


# ---------- helpers ----------

def get_json(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_text(value, limit=None):
    """Remove HTML tags and extra spaces."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "..."
    return text


def to_iso(value):
    """Turn many date formats into one ISO date in UTC."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            moment = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OSError):
        return None


def pretty_type(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).replace("_", " ").replace("-", " ").strip().title() if value else ""


def first(value):
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def make_job(source, source_id, title, company, url, posted, category="",
             job_type="", location="", salary="", tags=None, excerpt=""):
    return {
        "id": f"{source}-{source_id}",
        "title": clean_text(title),
        "company": clean_text(company),
        "category": clean_text(category) or "Other",
        "type": pretty_type(job_type),
        "location": clean_text(location) or "Anywhere",
        "salary": clean_text(salary),
        "tags": [clean_text(t) for t in (tags or [])][:4],
        "posted": to_iso(posted),
        "url": url,
        "source": source,
        "excerpt": clean_text(excerpt, EXCERPT_LENGTH),
    }


# ---------- sources ----------

def from_remotive():
    data = get_json("https://remotive.com/api/remote-jobs")
    return [
        make_job("Remotive", j["id"], j["title"], j["company_name"], j["url"],
                 j.get("publication_date"), j.get("category"), j.get("job_type"),
                 j.get("candidate_required_location"), j.get("salary"),
                 j.get("tags"), j.get("description"))
        for j in data.get("jobs", [])
    ]


def from_remoteok():
    data = get_json("https://remoteok.com/api")
    jobs = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue  # the first item is a legal notice, not a job
        tags = j.get("tags") or []
        salary = ""
        if j.get("salary_min") and j.get("salary_max"):
            salary = f"${j['salary_min']:,} - ${j['salary_max']:,}"
        jobs.append(make_job(
            "Remote OK", j.get("id"), j["position"], j.get("company"),
            j.get("url") or j.get("apply_url"), j.get("date") or j.get("epoch"),
            (tags[0].title() if tags else ""), "", j.get("location"), salary,
            tags, j.get("description")))
    return jobs


def from_arbeitnow():
    data = get_json("https://www.arbeitnow.com/api/job-board-api")
    return [
        make_job("Arbeitnow", j["slug"], j["title"], j["company_name"], j["url"],
                 j.get("created_at"), first(j.get("tags")), j.get("job_types"),
                 j.get("location"), "", j.get("tags"), j.get("description"))
        for j in data.get("data", []) if j.get("remote")
    ]


def from_jobicy():
    data = get_json("https://jobicy.com/api/v2/remote-jobs?count=50")
    return [
        make_job("Jobicy", j["id"], j["jobTitle"], j["companyName"], j["url"],
                 j.get("pubDate"), first(j.get("jobIndustry")), j.get("jobType"),
                 j.get("jobGeo"), "", [], j.get("jobExcerpt"))
        for j in data.get("jobs", [])
    ]


SOURCES = [from_remotive, from_remoteok, from_arbeitnow, from_jobicy]


# ---------- main ----------

def main():
    all_jobs = []
    for source in SOURCES:
        try:
            found = source()
            print(f"{source.__name__}: {len(found)} jobs")
            all_jobs.extend(found)
        except Exception as error:  # keep going if one source is down
            print(f"{source.__name__} failed: {error}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    seen, jobs = set(), []
    for job in all_jobs:
        if not (job["title"] and job["company"] and str(job["url"]).startswith("http")):
            continue
        if not job["posted"] or datetime.fromisoformat(job["posted"]) < cutoff:
            continue
        key = (job["title"].lower(), job["company"].lower())
        if key in seen:
            continue
        seen.add(key)
        jobs.append(job)

    jobs.sort(key=lambda job: job["posted"], reverse=True)
    jobs = jobs[:MAX_JOBS]

    if not jobs:
        print("No jobs collected. Keeping the existing jobs.json.")
        sys.exit(0)

    output = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": jobs}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=1)
    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
