import os
import base64
import datetime as dt
from urllib.parse import urlparse

import requests
import streamlit as st
from dotenv import load_dotenv
from jinja2 import Template
from streamlit.components.v1 import html as st_html

# -------------------------------------------------------------------
# Configurazione
# -------------------------------------------------------------------

load_dotenv()

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
RPMLOGO_PATH = os.path.join(ASSETS_DIR, "rpmlogo.png")
RPMSOFT_PATH = os.path.join(ASSETS_DIR, "rpmsoft.png")


def get_inline_logo(path):
    """Ritorna il logo indicato come base64, oppure stringa vuota in caso di errore."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return ""


# -------------------------------------------------------------------
# Helper GitHub
# -------------------------------------------------------------------

def parse_github_url(url: str):
    """
    Estrae owner, repo e branch da una URL GitHub.
    """
    if not url:
        raise ValueError("URL vuota")

    parsed = urlparse(url.strip())
    if "github.com" not in parsed.netloc:
        raise ValueError("La URL non è una URL GitHub")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Impossibile estrarre owner e repo dalla URL")

    owner = parts[0]
    repo = parts[1]

    branch = "dev"
    if len(parts) >= 4 and parts[2] == "tree":
        branch = parts[3]

    return owner, repo, branch


def github_get(path: str, params=None):
    """
    Chiama la GitHub API e ritorna il JSON o solleva RuntimeError.
    """
    if params is None:
        params = {}

    url = f"{GITHUB_API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "gam-github-dashboard",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    resp = requests.get(url, headers=headers, params=params, timeout=20)

    if resp.status_code == 202:
        return None

    if resp.status_code == 403:
        try:
            data = resp.json()
            message = data.get("message", "Rate limit o accesso negato")
        except Exception:
            message = "GitHub API rate limit o accesso negato"
        raise RuntimeError(f"Errore GitHub API 403: {message}")

    if resp.status_code >= 400:
        try:
            data = resp.json()
            message = data.get("message", "Errore sconosciuto")
        except Exception:
            message = f"HTTP {resp.status_code}"
        raise RuntimeError(f"Errore GitHub API {resp.status_code}: {message}")

    try:
        return resp.json()
    except Exception as exc:
        raise RuntimeError(f"Impossibile decodificare risposta GitHub: {exc}") from exc


def parse_iso_date(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


# -------------------------------------------------------------------
# Raccolta dati per cruscotto repository
# -------------------------------------------------------------------

def collect_repo_dashboard_data(owner: str, repo: str, branch: str):
    """
    Recupera tutti i dati necessari per il cruscotto.
    Gli indicatori autore sono calcolati solo sui commit specifici del branch,
    cioè non presenti anche nel branch predefinito.
    """

    repo_info = github_get(f"/repos/{owner}/{repo}")
    default_branch = repo_info.get("default_branch") or "main"

    commits_branch_raw = github_get(
        f"/repos/{owner}/{repo}/commits",
        params={"per_page": 100, "sha": branch},
    )

    default_shas = set()
    if branch != default_branch:
        commits_default_raw = github_get(
            f"/repos/{owner}/{repo}/commits",
            params={"per_page": 100, "sha": default_branch},
        )
        if isinstance(commits_default_raw, list):
            default_shas = {c.get("sha") for c in commits_default_raw if c.get("sha")}

    commits_raw = []
    if isinstance(commits_branch_raw, list):
        for c in commits_branch_raw:
            sha_full = c.get("sha")
            if not sha_full:
                continue
            if branch != default_branch and sha_full in default_shas:
                continue
            commits_raw.append(c)

    issues_raw = github_get(
        f"/repos/{owner}/{repo}/issues",
        params={"state": "all", "per_page": 50},
    )

    pulls_raw = github_get(
        f"/repos/{owner}/{repo}/pulls",
        params={"state": "all", "per_page": 50},
    )

    contributors_raw = github_get(
        f"/repos/{owner}/{repo}/contributors",
        params={"per_page": 10},
    )

    commit_activity = github_get(f"/repos/{owner}/{repo}/stats/commit_activity")

    commits = []
    author_map = {}
    if isinstance(commits_raw, list):
        for c in commits_raw:
            sha_full = c.get("sha", "")
            sha = sha_full[:7]
            commit = c.get("commit", {})
            message = (commit.get("message") or "").splitlines()[0]
            author_info = commit.get("author", {}) or {}
            author_name = author_info.get("name")
            gh_author = c.get("author") or {}
            author_login = gh_author.get("login")
            author_id = author_login or author_name or "unknown"
            author_display = author_login or author_name or "Sconosciuto"
            date_str = author_info.get("date")
            date = parse_iso_date(date_str)

            commit_obj = {
                "sha": sha,
                "sha_full": sha_full,
                "message": message,
                "author": author_display,
                "author_id": author_id,
                "author_display": author_display,
                "date": date,
                "date_display": date.strftime("%Y-%m-%d %H:%M") if date else "",
            }
            commits.append(commit_obj)

            if date:
                if author_id not in author_map:
                    author_map[author_id] = {
                        "id": author_id,
                        "display": author_display,
                        "commits": 0,
                        "first_date": date,
                        "last_date": date,
                    }
                entry = author_map[author_id]
                entry["commits"] += 1
                if date < entry["first_date"]:
                    entry["first_date"] = date
                if date > entry["last_date"]:
                    entry["last_date"] = date

    author_overview = []
    for a in author_map.values():
        first_date = a["first_date"]
        last_date = a["last_date"]
        if first_date and last_date:
            days_active = (last_date.date() - first_date.date()).days + 1
        else:
            days_active = 0
        author_overview.append(
            {
                "id": a["id"],
                "display": a["display"],
                "commits": a["commits"],
                "first_date_display": first_date.strftime("%Y-%m-%d") if first_date else "",
                "last_date_display": last_date.strftime("%Y-%m-%d") if last_date else "",
                "days_active": days_active,
            }
        )

    issues = []
    open_issues_count = 0
    closed_issues_count = 0

    if isinstance(issues_raw, list):
        for i in issues_raw:
            if "pull_request" in i:
                continue
            state = i.get("state", "open")
            if state == "open":
                open_issues_count += 1
            else:
                closed_issues_count += 1

            updated_at = parse_iso_date(i.get("updated_at"))
            issues.append(
                {
                    "number": i.get("number"),
                    "title": i.get("title") or "",
                    "state": state,
                    "assignee": (i.get("assignee") or {}).get("login"),
                    "updated_display": updated_at.strftime("%Y-%m-%d %H:%M")
                    if updated_at
                    else "",
                    "url": i.get("html_url"),
                }
            )

    pulls = []
    open_pr_count = 0
    closed_pr_count = 0
    if isinstance(pulls_raw, list):
        for p in pulls_raw:
            state = p.get("state", "open")
            if state == "open":
                open_pr_count += 1
            else:
                closed_pr_count += 1

            updated_at = parse_iso_date(p.get("updated_at"))
            pulls.append(
                {
                    "number": p.get("number"),
                    "title": p.get("title") or "",
                    "state": state,
                    "author": (p.get("user") or {}).get("login"),
                    "updated_display": updated_at.strftime("%Y-%m-%d %H:%M")
                    if updated_at
                    else "",
                    "url": p.get("html_url"),
                }
            )

    contributors = []
    if isinstance(contributors_raw, list):
        for c in contributors_raw:
            contributors.append(
                {
                    "login": c.get("login"),
                    "commits": c.get("contributions"),
                    "avatar": c.get("avatar_url"),
                    "url": c.get("html_url"),
                }
            )

    commit_weeks = []
    if isinstance(commit_activity, list):
        for item in commit_activity[-12:]:
            ts = item.get("week")
            total = item.get("total", 0)
            if ts is None:
                continue
            week_start = dt.datetime.utcfromtimestamp(ts)
            label = week_start.strftime("%Y-%m-%d")
            commit_weeks.append({"label": label, "total": total})

    pushed_at = parse_iso_date(repo_info.get("pushed_at"))
    created_at = parse_iso_date(repo_info.get("created_at"))

    overview = {
        "full_name": repo_info.get("full_name"),
        "description": repo_info.get("description"),
        "default_branch": default_branch,
        "stars": repo_info.get("stargazers_count"),
        "forks": repo_info.get("forks_count"),
        "watchers": repo_info.get("subscribers_count"),
        "open_issues": repo_info.get("open_issues_count"),
        "language": repo_info.get("language"),
        "pushed_at": pushed_at.strftime("%Y-%m-%d %H:%M") if pushed_at else "",
        "created_at": created_at.strftime("%Y-%m-%d %H:%M") if created_at else "",
        "html_url": repo_info.get("html_url"),
    }

    repo_url = f"https://github.com/{owner}/{repo}/tree/{branch}"

    dashboard = {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "repo_url": repo_url,
        "overview": overview,
        "commits": commits,
        "issues": issues,
        "pulls": pulls,
        "contributors": contributors,
        "open_issues_count": open_issues_count,
        "closed_issues_count": closed_issues_count,
        "open_pr_count": open_pr_count,
        "closed_pr_count": closed_pr_count,
        "commit_weeks": commit_weeks,
        "author_overview": author_overview,
    }

    return dashboard


# -------------------------------------------------------------------
# Attività autore 360
# -------------------------------------------------------------------

def compute_author_activity(owner: str, repo: str, branch: str, author_id: str):
    dashboard = collect_repo_dashboard_data(owner, repo, branch)
    commits_all = dashboard["commits"]

    author_commits = [c for c in commits_all if c["author_id"] == author_id]

    if not author_commits:
        raise RuntimeError(f"Nessun commit trovato per autore {author_id} sul branch {branch}")

    author_commits_sorted = sorted(
        [c for c in author_commits if c["date"] is not None],
        key=lambda x: x["date"],
    )

    first_date = author_commits_sorted[0]["date"]
    last_date = author_commits_sorted[-1]["date"]
    days_active = (last_date.date() - first_date.date()).days + 1 if first_date and last_date else 0

    activity_by_day_map = {}
    for c in author_commits_sorted:
        if not c["date"]:
            continue
        label = c["date"].strftime("%Y-%m-%d")
        activity_by_day_map[label] = activity_by_day_map.get(label, 0) + 1

    activity_by_day = [
        {"label": k, "total": v}
        for k, v in sorted(activity_by_day_map.items(), key=lambda kv: kv[0])
    ]

    total_additions = 0
    total_deletions = 0
    total_files_changed = 0
    enriched_commits = []

    DETAIL_LIMIT = 50
    for c in author_commits_sorted[:DETAIL_LIMIT]:
        sha_full = c.get("sha_full")
        details = github_get(f"/repos/{owner}/{repo}/commits/{sha_full}")
        stats = details.get("stats") or {}
        additions = stats.get("additions", 0)
        deletions = stats.get("deletions", 0)
        files = details.get("files") or []
        files_changed = len(files)
        file_names_list = [f.get("filename", "") for f in files]
        file_names = ", ".join(file_names_list)

        total_additions += additions
        total_deletions += deletions
        total_files_changed += files_changed

        enriched = dict(c)
        enriched["additions"] = additions
        enriched["deletions"] = deletions
        enriched["files_changed"] = files_changed
        enriched["file_names"] = file_names
        enriched_commits.append(enriched)

    total_commits = len(author_commits_sorted)
    net_lines = total_additions - total_deletions
    avg_additions = total_additions / total_commits if total_commits else 0
    avg_deletions = total_deletions / total_commits if total_commits else 0
    avg_files = total_files_changed / total_commits if total_commits else 0

    author_display = author_commits_sorted[0]["author_display"]

    summary = {
        "author_id": author_id,
        "author_display": author_display,
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "repo_url": dashboard["repo_url"],
        "total_commits": total_commits,
        "first_date": first_date,
        "first_date_display": first_date.strftime("%Y-%m-%d %H:%M") if first_date else "",
        "last_date": last_date,
        "last_date_display": last_date.strftime("%Y-%m-%d %H:%M") if last_date else "",
        "days_active": days_active,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "total_files_changed": total_files_changed,
        "net_lines": net_lines,
        "avg_additions": round(avg_additions, 1),
        "avg_deletions": round(avg_deletions, 1),
        "avg_files": round(avg_files, 1),
        "activity_by_day": activity_by_day,
    }

    return summary, enriched_commits


# -------------------------------------------------------------------
# Template HTML - indice
# -------------------------------------------------------------------

MAIN_TEMPLATE = Template(r"""
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Cruscotto Progetto GitHub</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            background: #050509;
            color: #e5e7eb;
        }
        header {
            padding: 10px 24px;
            background: linear-gradient(90deg, #020617, #7f1d1d);
            color: #f9fafb;
            border-bottom: 1px solid #111827;
        }
        .header-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .logo-main {
            height: 36px;
            border-radius: 4px;
        }
        .header-title h1 {
            margin: 0;
            font-size: 1.2rem;
        }
        .header-title p {
            margin: 2px 0 0 0;
            font-size: 0.85rem;
            color: #e5e7eb;
        }
        .container {
            padding: 24px;
            max-width: 1280px;
            margin: 0 auto;
        }
        h1, h2, h3 {
            margin-top: 0;
        }
        h2 {
            font-size: 1.1rem;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }
        .card {
            background: radial-gradient(circle at top left, #111827, #020617);
            border-radius: 10px;
            padding: 12px 14px;
            border: 1px solid #1f2937;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
        }
        .card-title {
            font-size: 0.8rem;
            text-transform: uppercase;
            color: #9ca3af;
            margin-bottom: 4px;
            letter-spacing: 0.04em;
        }
        .card-value {
            font-size: 1.1rem;
            font-weight: 600;
            color: #f9fafb;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        th, td {
            padding: 6px 8px;
            border-bottom: 1px solid #111827;
            text-align: left;
        }
        th {
            background: #020617;
            position: sticky;
            top: 0;
            z-index: 1;
            font-weight: 500;
            color: #f97373;
        }
        .section {
            margin-bottom: 32px;
        }
        .pill {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.75rem;
        }
        .pill-open {
            background: rgba(34, 197, 94, 0.15);
            color: #22c55e;
        }
        .pill-closed {
            background: rgba(248, 113, 113, 0.15);
            color: #f87171;
        }
        a {
            color: #f97373;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        canvas {
            background: #020617;
            border-radius: 10px;
            padding: 8px;
            border: 1px solid #1f2937;
        }
        .error {
            background: rgba(248, 113, 113, 0.08);
            border: 1px solid #f97373;
            color: #fecaca;
            padding: 8px 10px;
            border-radius: 8px;
            margin-bottom: 16px;
            font-size: 0.9rem;
        }
        .muted {
            color: #9ca3af;
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
<header>
    <div class="header-bar">
        <div class="header-left">
            {% if inline_logo_data %}
                <img src="data:image/png;base64,{{ inline_logo_data }}" alt="RPM Logo" class="logo-main">
            {% endif %}
            <div class="header-title">
                <h1>Cruscotto Progetto GitHub</h1>
                <p>Vista di gestione rapida per qualsiasi repository a cui hai accesso</p>
            </div>
        </div>
    </div>
</header>
<div class="container">

    {% if error %}
        <div class="error">{{ error }}</div>
    {% endif %}

    {% if data %}
        <div class="section">
            <h2>Panoramica</h2>
            <p>
                <a href="{{ data.repo_url }}" target="_blank">
                    {{ data.overview.full_name }}
                </a>
                {% if data.overview.description %}
                    <br><span class="muted">{{ data.overview.description }}</span>
                {% endif %}
            </p>
            <div class="grid">
                <div class="card">
                    <div class="card-title">Branch attivo (cruscotto)</div>
                    <div class="card-value">{{ data.branch }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Branch predefinito (GitHub)</div>
                    <div class="card-value">{{ data.overview.default_branch }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Linguaggio</div>
                    <div class="card-value">{{ data.overview.language or "Non definito" }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Stelle</div>
                    <div class="card-value">{{ data.overview.stars }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Fork</div>
                    <div class="card-value">{{ data.overview.forks }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Osservatori</div>
                    <div class="card-value">{{ data.overview.watchers }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Issue aperte (totale)</div>
                    <div class="card-value">{{ data.overview.open_issues }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Issue (aperte/chiuse)</div>
                    <div class="card-value">{{ data.open_issues_count }} / {{ data.closed_issues_count }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Pull request (aperte/chiuse)</div>
                    <div class="card-value">{{ data.open_pr_count }} / {{ data.closed_pr_count }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Creato il</div>
                    <div class="card-value">{{ data.overview.created_at }}</div>
                </div>
                <div class="card">
                    <div class="card-title">Ultimo push</div>
                    <div class="card-value">{{ data.overview.pushed_at }}</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Riepilogo autori sul branch "{{ data.branch }}"</h2>
            {% if data.author_overview %}
                <div style="max-height: 260px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Autore</th>
                                <th>Commit</th>
                                <th>Primo commit</th>
                                <th>Ultimo commit</th>
                                <th>Giorni attivi</th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for a in data.author_overview %}
                            <tr>
                                <td>{{ a.display }}</td>
                                <td>{{ a.commits }}</td>
                                <td>{{ a.first_date_display }}</td>
                                <td>{{ a.last_date_display }}</td>
                                <td>{{ a.days_active }}</td>
                            </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% else %}
                <p class="muted">Nessuna attività autori trovata per questo branch.</p>
            {% endif %}
        </div>

        <div class="section">
            <h2>Attività commit (livello repository, ultime settimane)</h2>
            {% if data.commit_weeks %}
                <canvas id="commitChart" height="100"></canvas>
            {% else %}
                <p class="muted">Nessun dato di attività commit disponibile. GitHub potrebbe essere ancora in elaborazione.</p>
            {% endif %}
        </div>

        <div class="section">
            <h2>Commit recenti sul branch "{{ data.branch }}" (solo commit specifici del branch)</h2>
            {% if data.commits %}
                <div style="max-height: 260px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>SHA</th>
                                <th>Messaggio</th>
                                <th>Autore</th>
                                <th>Data</th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for c in data.commits %}
                            <tr>
                                <td><span class="muted">{{ c.sha }}</span></td>
                                <td>{{ c.message }}</td>
                                <td>{{ c.author }}</td>
                                <td>{{ c.date_display }}</td>
                            </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% else %}
                <p class="muted">Nessun commit specifico trovato per questo branch.</p>
            {% endif %}
        </div>

        <div class="section">
            <h2>Issue</h2>
            {% if data.issues %}
                <div style="max-height: 260px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Titolo</th>
                                <th>Stato</th>
                                <th>Assegnato a</th>
                                <th>Aggiornato</th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for i in data.issues %}
                            <tr>
                                <td><a href="{{ i.url }}" target="_blank">#{{ i.number }}</a></td>
                                <td>{{ i.title }}</td>
                                <td>
                                    {% if i.state == "open" %}
                                        <span class="pill pill-open">aperta</span>
                                    {% else %}
                                        <span class="pill pill-closed">{{ i.state }}</span>
                                    {% endif %}
                                </td>
                                <td>{{ i.assignee or "-" }}</td>
                                <td>{{ i.updated_display }}</td>
                            </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% else %}
                <p class="muted">Nessuna issue trovata.</p>
            {% endif %}
        </div>

        <div class="section">
            <h2>Pull request</h2>
            {% if data.pulls %}
                <div style="max-height: 260px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Titolo</th>
                                <th>Stato</th>
                                <th>Autore</th>
                                <th>Aggiornato</th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for p in data.pulls %}
                            <tr>
                                <td><a href="{{ p.url }}" target="_blank">#{{ p.number }}</a></td>
                                <td>{{ p.title }}</td>
                                <td>
                                    {% if p.state == "open" %}
                                        <span class="pill pill-open">aperta</span>
                                    {% else %}
                                        <span class="pill pill-closed">{{ p.state }}</span>
                                    {% endif %}
                                </td>
                                <td>{{ p.author or "-" }}</td>
                                <td>{{ p.updated_display }}</td>
                            </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% else %}
                <p class="muted">Nessuna pull request trovata.</p>
            {% endif %}
        </div>

        <div class="section">
            <h2>Principali contributor (livello repository)</h2>
            {% if data.contributors %}
                <div class="grid">
                    {% for c in data.contributors %}
                        <div class="card">
                            <div class="card-title">Contributor</div>
                            <div class="card-value">
                                <a href="{{ c.url }}" target="_blank">{{ c.login }}</a>
                            </div>
                            <div class="muted">{{ c.commits }} commit</div>
                        </div>
                    {% endfor %}
                </div>
            {% else %}
                <p class="muted">Nessun dato contributor disponibile.</p>
            {% endif %}
        </div>
    {% endif %}
</div>

{% if data and data.commit_weeks %}
<script>
    const labels = {{ data.commit_weeks | map(attribute="label") | list | tojson }};
    const values = {{ data.commit_weeks | map(attribute="total") | list | tojson }};

    const ctx = document.getElementById('commitChart').getContext('2d');

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Commit per settimana',
                data: values,
                tension: 0.3,
                borderColor: 'rgba(248,113,113,1)',
                backgroundColor: 'rgba(248,113,113,0.2)',
            }]
        },
        options: {
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true }
            }
        }
    });
</script>
{% endif %}
</body>
</html>
""")


# -------------------------------------------------------------------
# Template HTML - vista autore + report HTML
# -------------------------------------------------------------------

AUTHOR_TEMPLATE = Template(r"""
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Attività autore · {{ summary.author_display }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            background: #050509;
            color: #e5e7eb;
        }
        header {
            padding: 10px 24px;
            background: linear-gradient(90deg, #020617, #7f1d1d);
            color: #f9fafb;
            border-bottom: 1px solid #111827;
        }
        .header-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .logo-main {
            height: 36px;
            border-radius: 4px;
        }
        .header-title h1 {
            margin: 0;
            font-size: 1.2rem;
        }
        .header-title p {
            margin: 2px 0 0 0;
            font-size: 0.85rem;
            color: #e5e7eb;
        }
        .container {
            padding: 24px;
            max-width: 1280px;
            margin: 0 auto;
        }
        h1, h2, h3 {
            margin-top: 0;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }
        .card {
            background: radial-gradient(circle at top left, #111827, #020617);
            border-radius: 10px;
            padding: 12px 14px;
            border: 1px solid #1f2937;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
        }
        .card-title {
            font-size: 0.8rem;
            text-transform: uppercase;
            color: #9ca3af;
            margin-bottom: 4px;
            letter-spacing: 0.04em;
        }
        .card-value {
            font-size: 1.1rem;
            font-weight: 600;
            color: #f9fafb;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        th, td {
            padding: 6px 8px;
            border-bottom: 1px solid #111827;
            text-align: left;
        }
        th {
            background: #020617;
            position: sticky;
            top: 0;
            z-index: 1;
            font-weight: 500;
            color: #f97373;
        }
        .section {
            margin-bottom: 32px;
        }
        .muted {
            color: #9ca3af;
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
<header>
    <div class="header-bar">
        <div class="header-left">
            {% if inline_logo_data %}
                <img src="data:image/png;base64,{{ inline_logo_data }}" alt="RPM Logo" class="logo-main">
            {% endif %}
            <div class="header-title">
                <h1>Attività autore · {{ summary.author_display }}</h1>
                <p>{{ summary.owner }}/{{ summary.repo }} sul branch "{{ summary.branch }}"</p>
            </div>
        </div>
    </div>
</header>
<div class="container">

    <div class="section">
        <h2>Panoramica 360</h2>
        <div class="grid">
            <div class="card">
                <div class="card-title">Commit totali</div>
                <div class="card-value">{{ summary.total_commits }}</div>
            </div>
            <div class="card">
                <div class="card-title">Primo commit</div>
                <div class="card-value">{{ summary.first_date_display }}</div>
            </div>
            <div class="card">
                <div class="card-title">Ultimo commit</div>
                <div class="card-value">{{ summary.last_date_display }}</div>
            </div>
            <div class="card">
                <div class="card-title">Giorni attivi</div>
                <div class="card-value">{{ summary.days_active }}</div>
            </div>
            <div class="card">
                <div class="card-title">Righe aggiunte</div>
                <div class="card-value">{{ summary.total_additions }}</div>
            </div>
            <div class="card">
                <div class="card-title">Righe rimosse</div>
                <div class="card-value">{{ summary.total_deletions }}</div>
            </div>
            <div class="card">
                <div class="card-title">Righe nette</div>
                <div class="card-value">{{ summary.net_lines }}</div>
            </div>
            <div class="card">
                <div class="card-title">Media per commit</div>
                <div class="card-value">
                    +{{ summary.avg_additions }} / -{{ summary.avg_deletions }}<br>
                    <span class="muted">file modificati: {{ summary.avg_files }}</span>
                </div>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Attività nel tempo</h2>
        {% if summary.activity_by_day %}
            <canvas id="activityByDayChart" height="80"></canvas>
        {% else %}
            <p class="muted">Nessun commit datato da mostrare.</p>
        {% endif %}
    </div>

    <div class="section">
        <h2>Variazioni per commit (ultimi {{ commits|length }} analizzati)</h2>
        {% if commits %}
            <canvas id="changesPerCommitChart" height="80"></canvas>
        {% else %}
            <p class="muted">Nessun dato di diff disponibile.</p>
        {% endif %}
    </div>

    <div class="section">
        <h2>Dettaglio commit</h2>
        {% if commits %}
            <div style="max-height: 320px; overflow-y: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Data</th>
                            <th>SHA</th>
                            <th>Messaggio</th>
                            <th>Righe +</th>
                            <th>Righe -</th>
                            <th>File modificati</th>
                            <th>Nomi file</th>
                        </tr>
                    </thead>
                    <tbody>
                    {% for c in commits %}
                        <tr>
                            <td>{{ c.date_display }}</td>
                            <td><span class="muted">{{ c.sha }}</span></td>
                            <td>{{ c.message }}</td>
                            <td>{{ c.additions }}</td>
                            <td>{{ c.deletions }}</td>
                            <td>{{ c.files_changed }}</td>
                            <td>{{ c.file_names }}</td>
                        </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
            <p class="muted">
                Nota: i dettagli di diff sono raccolti per un massimo di {{ commits|length }} commit piu recenti per questo autore su questo branch.
            </p>
        {% else %}
            <p class="muted">Nessun commit trovato.</p>
        {% endif %}
    </div>
</div>

<script>
{% if summary.activity_by_day %}
    const adLabels = {{ summary.activity_by_day | map(attribute="label") | list | tojson }};
    const adValues = {{ summary.activity_by_day | map(attribute="total") | list | tojson }};
    const ctxAD = document.getElementById('activityByDayChart').getContext('2d');
    new Chart(ctxAD, {
        type: 'line',
        data: {
            labels: adLabels,
            datasets: [{
                label: 'Commit al giorno',
                data: adValues,
                tension: 0.2,
                borderColor: 'rgba(248,113,113,1)',
                backgroundColor: 'rgba(248,113,113,0.2)',
            }]
        },
        options: {
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true }
            }
        }
    });
{% endif %}

{% if commits %}
    const cLabels = {{ commits | map(attribute="date_display") | list | tojson }};
    const cAdds = {{ commits | map(attribute="additions") | list | tojson }};
    const cDels = {{ commits | map(attribute="deletions") | list | tojson }};

    const ctxChanges = document.getElementById('changesPerCommitChart').getContext('2d');
    new Chart(ctxChanges, {
        type: 'bar',
        data: {
            labels: cLabels,
            datasets: [
                {
                    label: 'Righe aggiunte',
                    data: cAdds,
                    stack: 'stack1',
                    backgroundColor: 'rgba(34,197,94,0.7)',
                },
                {
                    label: 'Righe rimosse',
                    data: cDels,
                    stack: 'stack1',
                    backgroundColor: 'rgba(248,113,113,0.7)',
                }
            ]
        },
        options: {
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true }
            }
        }
    });
{% endif %}
</script>
</body>
</html>
""")


# -------------------------------------------------------------------
# Streamlit UI
# -------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="GitHub PM Dashboard",
        page_icon="📊",
        layout="wide",
    )

    inline_soft_logo = get_inline_logo(RPMSOFT_PATH)

    st.markdown(
        """
        <style>
        .stApp {
            background-color: #050509;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_logo, col_title = st.columns([1, 5])
    with col_logo:
        if os.path.exists(RPMSOFT_PATH):
            st.image(RPMSOFT_PATH, use_column_width=True)
    with col_title:
        st.markdown("### Cruscotto Progetto GitHub")
        st.caption("Vista di gestione rapida per qualsiasi repository a cui hai accesso")

    st.write("")

    default_url = "https://github.com/gamdevelop2024/GAM-Anonymization/tree/dev"
    repo_url = st.text_input(
        "URL del repository GitHub",
        value=default_url,
        help="Accetta sia https://github.com/owner/repo sia https://github.com/owner/repo/tree/dev",
    )

    load_button = st.button("Carica cruscotto")

    dashboard_data = None
    error = None

    if load_button and repo_url.strip():
        try:
            owner, repo, branch = parse_github_url(repo_url)
            dashboard_data = collect_repo_dashboard_data(owner, repo, branch)
        except Exception as exc:
            error = str(exc)

    if dashboard_data or error:
        html_main = MAIN_TEMPLATE.render(
            data=dashboard_data,
            error=error,
            inline_logo_data=inline_soft_logo,
        )
        st_html(html_main, height=900, scrolling=True)

    st.write("---")
    st.subheader("Vista 360 autore")

    if dashboard_data and dashboard_data.get("author_overview"):
        authors = dashboard_data["author_overview"]
        options = {a["display"]: a["id"] for a in authors}
        selected_display = st.selectbox("Seleziona autore", list(options.keys()))
        author_id = options[selected_display]

        if st.button("Carica vista 360 per autore"):
            try:
                summary, commits = compute_author_activity(
                    dashboard_data["owner"],
                    dashboard_data["repo"],
                    dashboard_data["branch"],
                    author_id,
                )
            except Exception as exc:
                st.error(f"Errore vista autore: {exc}")
                return

            inline_logo_author = inline_soft_logo

            html_author_view = AUTHOR_TEMPLATE.render(
                summary=summary,
                commits=commits,
                inline_logo_data=inline_logo_author,
            )
            st_html(html_author_view, height=900, scrolling=True)

            html_author_download = AUTHOR_TEMPLATE.render(
                summary=summary,
                commits=commits,
                inline_logo_data=inline_logo_author,
            )
            st.download_button(
                label="Scarica report HTML autore",
                data=html_author_download,
                file_name=f"{summary['repo']}_{summary['branch']}_{summary['author_id']}_attivita.html",
                mime="text/html",
            )
    elif dashboard_data:
        st.info("Nessun autore disponibile per il branch selezionato.")
    else:
        st.caption("Carica prima un repository per vedere la vista autore.")


if __name__ == "__main__":
    main()
