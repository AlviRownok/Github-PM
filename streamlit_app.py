import os
import time
import base64
import datetime as dt
from urllib.parse import urlparse

import requests
import jwt
import pandas as pd
import streamlit as st
from jinja2 import Template

# ------------------------------------------------------------
# Config letta da environment (o secrets su Streamlit Cloud)
# ------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_APP_INSTALLATION_ID = os.getenv("GITHUB_APP_INSTALLATION_ID")
GITHUB_APP_PRIVATE_KEY_PATH = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY")

# Percorsi relativi logo (in repo)
RPMLOGO_PATH = os.path.join("assets", "rpmlogo.png")
RPMSOFT_PATH = os.path.join("assets", "rpmsoft.png")

# Cache token installazione
_APP_PRIVATE_KEY = None
_INSTALLATION_TOKEN = None
_INSTALLATION_TOKEN_EXPIRES_AT = 0  # epoch seconds


# ------------------------------------------------------------
# Helper loghi
# ------------------------------------------------------------

def get_inline_logo_data():
    """Ritorna il logo rpmsoft come base64, oppure stringa vuota in caso di errore."""
    try:
        with open(RPMSOFT_PATH, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return ""


# ------------------------------------------------------------
# Autenticazione GitHub App
# ------------------------------------------------------------

def _load_app_private_key():
    global _APP_PRIVATE_KEY

    if _APP_PRIVATE_KEY is not None:
        return _APP_PRIVATE_KEY

    # Preferiamo la chiave direttamente dall env
    if GITHUB_APP_PRIVATE_KEY:
        _APP_PRIVATE_KEY = GITHUB_APP_PRIVATE_KEY
        return _APP_PRIVATE_KEY

    # Fallback: percorso file
    if GITHUB_APP_PRIVATE_KEY_PATH:
        try:
            with open(GITHUB_APP_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
                _APP_PRIVATE_KEY = f.read()
            return _APP_PRIVATE_KEY
        except Exception:
            return None

    return None


def _create_app_jwt():
    """Crea un JWT per autenticarsi come GitHub App."""
    private_key = _load_app_private_key()
    if not private_key or not GITHUB_APP_ID:
        return None

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": GITHUB_APP_ID,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def _refresh_installation_token():
    """Usa JWT per ottenere installation access token."""
    global _INSTALLATION_TOKEN, _INSTALLATION_TOKEN_EXPIRES_AT

    if not GITHUB_APP_INSTALLATION_ID:
        return None

    app_jwt = _create_app_jwt()
    if not app_jwt:
        return None

    url = f"{GITHUB_API_BASE}/app/installations/{GITHUB_APP_INSTALLATION_ID}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gam-github-dashboard",
    }
    resp = requests.post(url, headers=headers, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Errore creazione installation token: {resp.status_code} {resp.text}"
        )
    data = resp.json()
    token = data.get("token")
    expires_at = data.get("expires_at")

    if not token:
        raise RuntimeError("Installation token mancante nella risposta")

    _INSTALLATION_TOKEN = token
    if expires_at:
        dt_exp = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        _INSTALLATION_TOKEN_EXPIRES_AT = int(dt_exp.timestamp())
    else:
        _INSTALLATION_TOKEN_EXPIRES_AT = int(time.time()) + 50 * 60

    return _INSTALLATION_TOKEN


def get_github_auth_token():
    """
    Token da usare per GitHub API.
    1) GitHub App se configurata
    2) GITHUB_TOKEN se presente
    3) Nessuno
    """
    global _INSTALLATION_TOKEN, _INSTALLATION_TOKEN_EXPIRES_AT

    if GITHUB_APP_ID and GITHUB_APP_INSTALLATION_ID and (GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH):
        now = int(time.time())
        if not _INSTALLATION_TOKEN or now > (_INSTALLATION_TOKEN_EXPIRES_AT - 60):
            _refresh_installation_token()
        return _INSTALLATION_TOKEN

    if GITHUB_TOKEN:
        return GITHUB_TOKEN

    return None


# ------------------------------------------------------------
# Helper GitHub
# ------------------------------------------------------------

def parse_github_url(url: str):
    """Estrae owner, repo e branch da URL GitHub (accetta /tree/dev)."""
    if not url:
        raise ValueError("URL vuota")

    parsed = urlparse(url.strip())
    if "github.com" not in parsed.netloc:
        raise ValueError("La URL non è GitHub")

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
    """Chiama GitHub API con il token corretto."""
    if params is None:
        params = {}

    url = f"{GITHUB_API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "gam-github-dashboard",
    }

    token = get_github_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

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


# ------------------------------------------------------------
# Raccolta dati cruscotto repository
# ------------------------------------------------------------

def collect_repo_dashboard_data(owner: str, repo: str, branch: str):
    """
    Dati per cruscotto repo.
    Commit autore solo specifici del branch (non presenti nel default branch).
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
        days_active = (last_date.date() - first_date.date()).days + 1 if first_date and last_date else 0
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


# ------------------------------------------------------------
# Attività autore 360
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# Template HTML per report autore (simile versione Flask)
# ------------------------------------------------------------

AUTHOR_HTML_TEMPLATE = Template(r"""
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
        }
        .logo-main {
            height: 36px;
            border-radius: 4px;
            margin-right: 12px;
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
            max-width: 1080px;
            margin: 0 auto;
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
</head>
<body>
<header>
    <div class="header-bar">
        {% if inline_logo_data %}
        <img src="data:image/png;base64,{{ inline_logo_data }}" alt="RPM Logo" class="logo-main">
        {% endif %}
        <div class="header-title">
            <h1>Attività autore · {{ summary.author_display }}</h1>
            <p>{{ summary.owner }}/{{ summary.repo }} sul branch "{{ summary.branch }}"</p>
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
        <h2>Dettaglio commit</h2>
        {% if commits %}
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
            <p class="muted">
                Nota: i dettagli di diff sono raccolti per un massimo di {{ commits|length }} commit piu recenti per questo autore su questo branch.
            </p>
        {% else %}
            <p class="muted">Nessun commit trovato.</p>
        {% endif %}
    </div>
</div>
</body>
</html>
""")


def generate_author_html(summary, commits):
    inline_logo = get_inline_logo_data()
    return AUTHOR_HTML_TEMPLATE.render(
        summary=summary,
        commits=commits,
        inline_logo_data=inline_logo,
    )


# ------------------------------------------------------------
# UI Streamlit
# ------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="GAM RPM GitHub Dashboard",
        page_icon="📊",
        layout="wide",
    )

    col_logo, col_title = st.columns([1, 5])
    with col_logo:
        if os.path.exists(RPMSOFT_PATH):
            st.image(RPMSOFT_PATH, use_column_width=True)
    with col_title:
        st.markdown("### Cruscotto Progetto GitHub")
        st.caption("Vista di gestione rapida per qualsiasi repository a cui hai accesso")

    st.write("---")

    with st.form("repo_form"):
        default_url = "https://github.com/gamdevelop2024/GAM-Anonymization/tree/dev"
        repo_url = st.text_input(
            "URL del repository GitHub",
            value=default_url,
            help="Accetta sia https://github.com/owner/repo sia https://github.com/owner/repo/tree/dev",
        )
        submitted = st.form_submit_button("Carica cruscotto")

    if not submitted:
        return

    try:
        owner, repo, branch = parse_github_url(repo_url)
        data = collect_repo_dashboard_data(owner, repo, branch)
    except Exception as exc:
        st.error(f"Errore: {exc}")
        return

    overview = data["overview"]

    st.subheader("Panoramica repository")
    top_cols = st.columns(4)
    top_cols[0].metric("Repository", overview["full_name"])
    top_cols[1].metric("Branch attivo (cruscotto)", data["branch"])
    top_cols[2].metric("Branch predefinito (GitHub)", overview["default_branch"])
    top_cols[3].metric("Linguaggio", overview["language"] or "Non definito")

    mid_cols = st.columns(5)
    mid_cols[0].metric("Stelle", overview["stars"])
    mid_cols[1].metric("Fork", overview["forks"])
    mid_cols[2].metric("Osservatori", overview["watchers"])
    mid_cols[3].metric("Issue aperte (totale)", overview["open_issues"])
    mid_cols[4].metric("Issue aperte / chiuse", f"{data['open_issues_count']} / {data['closed_issues_count']}")

    st.caption(f"Creato il {overview['created_at']} · Ultimo push {overview['pushed_at']}")
    st.markdown(f"[Apri su GitHub]({data['repo_url']})")

    st.write("---")

    left, right = st.columns([2, 1])

    with left:
        st.markdown(f"#### Riepilogo autori sul branch `{data['branch']}` (solo commit specifici)")

        if data["author_overview"]:
            df_auth = pd.DataFrame(data["author_overview"])
            df_auth_display = df_auth.rename(
                columns={
                    "display": "Autore",
                    "commits": "Commit",
                    "first_date_display": "Primo commit",
                    "last_date_display": "Ultimo commit",
                    "days_active": "Giorni attivi",
                }
            )[["Autore", "Commit", "Primo commit", "Ultimo commit", "Giorni attivi"]]
            st.dataframe(df_auth_display, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna attività autori trovata per questo branch.")

    with right:
        st.markdown("#### Attività commit (ultime settimane, livello repository)")
        if data["commit_weeks"]:
            df_weeks = pd.DataFrame(data["commit_weeks"])
            df_weeks = df_weeks.rename(columns={"label": "Settimana", "total": "Commit"})
            df_weeks = df_weeks.set_index("Settimana")
            st.line_chart(df_weeks)
        else:
            st.caption("Nessun dato di attività commit disponibile (GitHub potrebbe essere ancora in elaborazione).")

    st.write("---")

    st.markdown(f"#### Commit recenti sul branch `{data['branch']}` (solo specifici del branch)")

    if data["commits"]:
        df_commits = pd.DataFrame(data["commits"])
        df_commits_display = df_commits.rename(
            columns={
                "sha": "SHA",
                "message": "Messaggio",
                "author": "Autore",
                "date_display": "Data",
            }
        )[["SHA", "Messaggio", "Autore", "Data"]]
        st.dataframe(df_commits_display, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun commit specifico trovato per questo branch.")

    st.write("---")

    tabs = st.tabs(["Issue", "Pull request", "Contributor", "Autore 360"])

    with tabs[0]:
        st.markdown("#### Issue")
        if data["issues"]:
            df_issues = pd.DataFrame(data["issues"])
            df_issues_display = df_issues.rename(
                columns={
                    "number": "Numero",
                    "title": "Titolo",
                    "state": "Stato",
                    "assignee": "Assegnato a",
                    "updated_display": "Aggiornato",
                    "url": "URL",
                }
            )[["Numero", "Titolo", "Stato", "Assegnato a", "Aggiornato", "URL"]]
            st.dataframe(df_issues_display, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna issue trovata.")

    with tabs[1]:
        st.markdown("#### Pull request")
        if data["pulls"]:
            df_pr = pd.DataFrame(data["pulls"])
            df_pr_display = df_pr.rename(
                columns={
                    "number": "Numero",
                    "title": "Titolo",
                    "state": "Stato",
                    "author": "Autore",
                    "updated_display": "Aggiornato",
                    "url": "URL",
                }
            )[["Numero", "Titolo", "Stato", "Autore", "Aggiornato", "URL"]]
            st.dataframe(df_pr_display, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna pull request trovata.")

    with tabs[2]:
        st.markdown("#### Principali contributor (livello repository)")
        if data["contributors"]:
            df_contrib = pd.DataFrame(data["contributors"])
            df_contrib_display = df_contrib.rename(
                columns={
                    "login": "Login",
                    "commits": "Commit",
                    "avatar": "Avatar",
                    "url": "URL",
                }
            )[["Login", "Commit", "Avatar", "URL"]]
            st.dataframe(df_contrib_display, use_container_width=True, hide_index=True)
        else:
            st.info("Nessun contributor trovato.")

    with tabs[3]:
        st.markdown("#### Vista 360 autore sul branch specifico")

        authors = data["author_overview"]
        if not authors:
            st.info("Nessun autore disponibile per il branch selezionato.")
        else:
            options = {a["display"]: a["id"] for a in authors}
            selected_display = st.selectbox("Seleziona autore", list(options.keys()))
            author_id = options[selected_display]

            if st.button("Carica vista 360 per autore"):
                try:
                    summary, commits = compute_author_activity(owner, repo, branch, author_id)
                except Exception as exc:
                    st.error(f"Errore vista autore: {exc}")
                    return

                st.markdown(f"##### Panoramica 360 · {summary['author_display']}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Commit totali", summary["total_commits"])
                c2.metric("Righe aggiunte", summary["total_additions"])
                c3.metric("Righe rimosse", summary["total_deletions"])
                c4.metric("Righe nette", summary["net_lines"])

                c5, c6, c7 = st.columns(3)
                c5.metric("Primo commit", summary["first_date_display"])
                c6.metric("Ultimo commit", summary["last_date_display"])
                c7.metric("Giorni attivi", summary["days_active"])

                st.markdown("##### Attività nel tempo")
                if summary["activity_by_day"]:
                    df_ad = pd.DataFrame(summary["activity_by_day"]).rename(
                        columns={"label": "Data", "total": "Commit"}
                    )
                    df_ad = df_ad.set_index("Data")
                    st.line_chart(df_ad)
                else:
                    st.caption("Nessun commit datato da mostrare.")

                st.markdown("##### Dettaglio commit (massimo 50)")

                if commits:
                    df_c = pd.DataFrame(commits)
                    df_c_display = df_c.rename(
                        columns={
                            "date_display": "Data",
                            "sha": "SHA",
                            "message": "Messaggio",
                            "additions": "Righe +",
                            "deletions": "Righe -",
                            "files_changed": "File modificati",
                            "file_names": "Nomi file",
                        }
                    )[["Data", "SHA", "Messaggio", "Righe +", "Righe -", "File modificati", "Nomi file"]]
                    st.dataframe(df_c_display, use_container_width=True, hide_index=True)
                else:
                    st.info("Nessun commit trovato per questo autore.")

                # Download HTML report
                html_report = generate_author_html(summary, commits)
                st.download_button(
                    label="Scarica report HTML autore",
                    data=html_report,
                    file_name=f"{summary['repo']}_{summary['branch']}_{summary['author_id']}_attivita.html",
                    mime="text/html",
                )


if __name__ == "__main__":
    main()