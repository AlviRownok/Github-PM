import os
import json
import base64
import datetime as dt
from urllib.parse import urlparse

import requests
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from jinja2 import Template

# ============================================================
# Configurazione e costanti
# ============================================================

load_dotenv()

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
RPMLOGO_PATH = os.path.join(ASSETS_DIR, "rpmlogo.png")
RPMSOFT_PATH = os.path.join(ASSETS_DIR, "rpmsoft.png")

STATE_FILE = os.path.join(BASE_DIR, ".pm_state.json")

ACTIVITY_TAG_OPTIONS = [
    "Frontend",
    "Backend",
    "Database",
    "Model",
    "Payment System",
    "Scale UP",
]

# ============================================================
# Helper generali
# ============================================================

def get_inline_logo(path: str) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return ""


def parse_iso_date(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_github_url(url: str):
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
    if params is None:
        params = {}

    url = f"{GITHUB_API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-pm-dashboard",
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


# ============================================================
# Persistenza locale
# ============================================================

def _safe_read_state_file() -> dict:
    try:
        if not os.path.exists(STATE_FILE):
            return {}
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _safe_write_state_file(data: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def make_repo_key(owner: str, repo: str, branch: str) -> str:
    return f"{owner}/{repo}@{branch}"


def load_pm_state(repo_key: str) -> dict:
    all_state = _safe_read_state_file()
    return all_state.get(repo_key, {}) if isinstance(all_state, dict) else {}


def save_pm_state(repo_key: str, pm_state: dict) -> None:
    all_state = _safe_read_state_file()
    if not isinstance(all_state, dict):
        all_state = {}
    all_state[repo_key] = pm_state
    _safe_write_state_file(all_state)


def delete_pm_state(repo_key: str) -> None:
    all_state = _safe_read_state_file()
    if not isinstance(all_state, dict):
        return
    if repo_key in all_state:
        del all_state[repo_key]
        _safe_write_state_file(all_state)


# ============================================================
# Raccolta dati per cruscotto repository
# ============================================================

def collect_repo_dashboard_data(owner: str, repo: str, branch: str):
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

    issues_raw = github_get(f"/repos/{owner}/{repo}/issues", params={"state": "all", "per_page": 50})
    pulls_raw = github_get(f"/repos/{owner}/{repo}/pulls", params={"state": "all", "per_page": 50})
    contributors_raw = github_get(f"/repos/{owner}/{repo}/contributors", params={"per_page": 10})
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
                    "updated_display": updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else "",
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
                    "updated_display": updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else "",
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

    return {
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


# ============================================================
# Attività autore 360
# ============================================================

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

    activity_by_day = [{"label": k, "total": v} for k, v in sorted(activity_by_day_map.items(), key=lambda kv: kv[0])]

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
        "first_date_display": first_date.strftime("%Y-%m-%d %H:%M") if first_date else "",
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


# ============================================================
# Template HTML report autore
# ============================================================

AUTHOR_REPORT_TEMPLATE = Template(r"""
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Attività autore · {{ summary.author_display }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #050509; color: #e5e7eb; }
        header { padding: 10px 24px; background: linear-gradient(90deg, #020617, #7f1d1d); color: #f9fafb; border-bottom: 1px solid #111827; }
        .header-bar { display: flex; align-items: center; }
        .logo-main { height: 32px; border-radius: 4px; margin-right: 12px; }
        .container { padding: 24px; max-width: 1080px; margin: 0 auto; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .card { background: radial-gradient(circle at top left, #111827, #020617); border-radius: 10px; padding: 12px 14px; border: 1px solid #1f2937; box-shadow: 0 8px 20px rgba(0,0,0,0.35); }
        .card-title { font-size: 0.8rem; text-transform: uppercase; color: #9ca3af; margin-bottom: 4px; letter-spacing: 0.04em; }
        .card-value { font-size: 1.1rem; font-weight: 600; color: #f9fafb; }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th, td { padding: 6px 8px; border-bottom: 1px solid #111827; text-align: left; }
        th { background: #020617; font-weight: 500; color: #f97373; }
        .section { margin-bottom: 32px; }
        .muted { color: #9ca3af; }
    </style>
</head>
<body>
<header>
    <div class="header-bar">
        {% if inline_logo_data %}
            <img src="data:image/png;base64,{{ inline_logo_data }}" alt="RPM Logo" class="logo-main">
        {% endif %}
        <div>
            <div style="font-size:1.2rem; font-weight:600;">Attività autore · {{ summary.author_display }}</div>
            <div style="font-size:0.85rem; color:#e5e7eb;">{{ summary.owner }}/{{ summary.repo }} sul branch "{{ summary.branch }}"</div>
        </div>
    </div>
</header>

<div class="container">
    <div class="section">
        <h2>Panoramica 360</h2>
        <div class="grid">
            <div class="card"><div class="card-title">Commit totali</div><div class="card-value">{{ summary.total_commits }}</div></div>
            <div class="card"><div class="card-title">Primo commit</div><div class="card-value">{{ summary.first_date_display }}</div></div>
            <div class="card"><div class="card-title">Ultimo commit</div><div class="card-value">{{ summary.last_date_display }}</div></div>
            <div class="card"><div class="card-title">Giorni attivi</div><div class="card-value">{{ summary.days_active }}</div></div>
            <div class="card"><div class="card-title">Righe aggiunte</div><div class="card-value">{{ summary.total_additions }}</div></div>
            <div class="card"><div class="card-title">Righe rimosse</div><div class="card-value">{{ summary.total_deletions }}</div></div>
            <div class="card"><div class="card-title">Righe nette</div><div class="card-value">{{ summary.net_lines }}</div></div>
            <div class="card"><div class="card-title">Media per commit</div><div class="card-value">+{{ summary.avg_additions }} / -{{ summary.avg_deletions }}<br><span class="muted">file modificati: {{ summary.avg_files }}</span></div></div>
        </div>
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
            <p class="muted">Nota: i dettagli diff sono raccolti per un massimo di {{ commits|length }} commit piu recenti per questo autore su questo branch.</p>
        {% else %}
            <p class="muted">Nessun commit trovato.</p>
        {% endif %}
    </div>
</div>
</body>
</html>
""")


def generate_author_report_html(summary, commits) -> str:
    inline_logo = get_inline_logo(RPMSOFT_PATH)
    return AUTHOR_REPORT_TEMPLATE.render(summary=summary, commits=commits, inline_logo_data=inline_logo)


# ============================================================
# Blocco Project Manager
# ============================================================

def build_pm_table_from_commits(commits: list) -> pd.DataFrame:
    rows = []
    for c in commits:
        rows.append(
            {
                "SHA": c.get("sha", ""),
                "Messaggio": c.get("message", ""),
                "Autore": c.get("author", ""),
                "Data e ora commit": c.get("date_display", ""),
                "Activity Tag": "",
                "Activity Description": "",
                "sha_full": c.get("sha_full", ""),
            }
        )
    return pd.DataFrame(rows)


def merge_saved_inputs(df: pd.DataFrame, saved_map: dict) -> pd.DataFrame:
    if df.empty or not isinstance(saved_map, dict):
        return df
    df = df.copy()
    tags = []
    descs = []
    for _, r in df.iterrows():
        key = r.get("sha_full") or ""
        item = saved_map.get(key, {}) if key else {}
        tags.append(item.get("tag", ""))
        descs.append(item.get("desc", ""))
    df["Activity Tag"] = tags
    df["Activity Description"] = descs
    return df


def extract_inputs_map(df: pd.DataFrame) -> dict:
    out = {}
    if df.empty:
        return out
    for _, r in df.iterrows():
        sha_full = r.get("sha_full", "")
        if not sha_full:
            continue
        out[sha_full] = {
            "tag": (r.get("Activity Tag") or "").strip(),
            "desc": (r.get("Activity Description") or "").strip(),
        }
    return out


def make_gantt_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    tasks = []
    for _, r in df.iterrows():
        tag = (r.get("Activity Tag") or "").strip()
        if not tag:
            continue
        dt_str = (r.get("Data e ora commit") or "").strip()
        try:
            start = dt.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        except Exception:
            continue
        end = start + dt.timedelta(hours=2)

        autore = (r.get("Autore") or "").strip()
        desc = (r.get("Activity Description") or "").strip()
        sha = (r.get("SHA") or "").strip()

        label_parts = []
        if tag:
            label_parts.append(tag)
        if autore:
            label_parts.append(autore)
        if sha:
            label_parts.append(sha)
        label = " | ".join(label_parts)

        tasks.append(
            {
                "Task": label,
                "Start": start,
                "End": end,
                "Tag": tag,
                "Autore": autore,
                "Descrizione": desc,
                "SHA": sha,
            }
        )
    return pd.DataFrame(tasks)


def render_gantt_chart(tasks_df: pd.DataFrame, project_end: dt.date, extension_dates: list):
    try:
        import plotly.express as px
    except Exception:
        st.warning("Plotly non disponibile. Aggiungi plotly a requirements.txt per il Gantt.")
        return

    if tasks_df.empty:
        st.info("Compila almeno qualche riga con Activity Tag e Activity Description, poi genera il Gantt.")
        return

    tasks_df = tasks_df.sort_values("Start", ascending=True)

    fig = px.timeline(
        tasks_df,
        x_start="Start",
        x_end="End",
        y="Task",
        color="Tag",
        hover_data=["Autore", "Descrizione", "SHA"],
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        height=min(900, 140 + 28 * len(tasks_df)),
        paper_bgcolor="#050509",
        plot_bgcolor="#050509",
        font=dict(color="#e5e7eb"),
        legend_title_text="Activity Tag",
        margin=dict(l=10, r=10, t=40, b=10),
    )

    end_dt = dt.datetime.combine(project_end, dt.time(23, 59))
    fig.add_vline(x=end_dt, line_width=2, line_dash="dot", line_color="#ef4444")

    max_task_end = tasks_df["End"].max()
    max_ext = None
    if extension_dates:
        try:
            max_ext = max(extension_dates)
        except Exception:
            max_ext = None

    if max_ext:
        ext_dt = dt.datetime.combine(max_ext, dt.time(23, 59))
        shade_end = max(ext_dt, max_task_end)
    else:
        shade_end = max_task_end

    fig.add_vrect(
        x0=end_dt,
        x1=shade_end,
        fillcolor="rgba(239,68,68,0.12)",
        line_width=0,
        layer="below",
    )

    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Streamlit UI
# ============================================================

def main():
    st.set_page_config(
        page_title="GitHub PM Dashboard",
        page_icon="https://raw.githubusercontent.com/AlviRownok/Github-PM/main/assets/rpmsoft.png",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        .stApp { background-color: #050509; }
        .block-container {
            padding-top: 4rem !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            max-width: 100% !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }
        div[data-testid="stMetric"] {
            background: #020617;
            border-radius: 10px;
            padding: 8px 12px;
            border: 1px solid #1f2937;
        }
        div[data-testid="stMetricLabel"] { color: #9ca3af; font-size: 0.8rem; }
        div[data-testid="stMetricValue"] { color: #f9fafb; font-size: 1.2rem; }
        h4 { margin-bottom: 0.5rem !important; }
        table { color: #e5e7eb !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    inline_logo = get_inline_logo(RPMSOFT_PATH)
    header_html = f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
        {'<img src="data:image/png;base64,' + inline_logo + '" style="height:32px;border-radius:4px;" alt="RPM Logo">' if inline_logo else ''}
        <div>
            <div style="font-size:1.3rem;font-weight:600;color:#f9fafb;">Cruscotto Progetto GitHub</div>
            <div style="font-size:0.85rem;color:#9ca3af;margin-top:2px;">
                Vista di gestione rapida per qualsiasi repository a cui hai accesso
            </div>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    if "dashboard_data" not in st.session_state:
        st.session_state.dashboard_data = None
    if "last_error" not in st.session_state:
        st.session_state.last_error = None

    default_url = "https://github.com/gamdevelop2024/GAM-Anonymization/tree/dev"
    repo_url = st.text_input(
        "URL del repository GitHub",
        value=default_url,
        help="Accetta sia https://github.com/owner/repo sia https://github.com/owner/repo/tree/dev",
    )
    load_btn = st.button("Carica cruscotto")

    if load_btn:
        try:
            owner, repo, branch = parse_github_url(repo_url)
            data = collect_repo_dashboard_data(owner, repo, branch)
            st.session_state.dashboard_data = data
            st.session_state.last_error = None
        except Exception as exc:
            st.session_state.dashboard_data = None
            st.session_state.last_error = str(exc)

    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    dashboard_data = st.session_state.dashboard_data
    if not dashboard_data:
        st.info("Inserisci una URL valida e premi Carica cruscotto per vedere il cruscotto.")
        return

    overview = dashboard_data["overview"]

    tab_pan, tab_issues, tab_contrib, tab_author, tab_pm = st.tabs(
        ["Panoramica", "Issue e Pull request", "Contributor", "Autori 360", "Responsabile del progetto"]
    )

    # Panoramica
    with tab_pan:
        st.markdown("#### Panoramica repository")

        top1, top2, top3, top4 = st.columns(4)
        top1.metric("Repository", overview["full_name"])
        top2.metric("Branch attivo", dashboard_data["branch"])
        top3.metric("Branch predefinito", overview["default_branch"])
        top4.metric("Linguaggio", overview["language"] or "Non definito")

        mid1, mid2, mid3, mid4, mid5 = st.columns(5)
        mid1.metric("Stelle", overview["stars"])
        mid2.metric("Fork", overview["forks"])
        mid3.metric("Osservatori", overview["watchers"])
        mid4.metric("Issue aperte totali", overview["open_issues"])
        mid5.metric("Issue aperte e chiuse", f"{dashboard_data['open_issues_count']} / {dashboard_data['closed_issues_count']}")

        st.caption(
            f"Creato il {overview['created_at']} · Ultimo push {overview['pushed_at']} · "
            f"[Apri su GitHub]({dashboard_data['repo_url']})"
        )

        st.markdown("##### Attività commit (ultime 12 settimane, livello repository)")
        if dashboard_data["commit_weeks"]:
            df_weeks = pd.DataFrame(dashboard_data["commit_weeks"]).rename(columns={"label": "Settimana", "total": "Commit"}).set_index("Settimana")
            st.line_chart(df_weeks, use_container_width=True)
        else:
            st.caption("Nessun dato di attività commit disponibile (GitHub potrebbe essere ancora in elaborazione).")

        st.markdown("##### Commit recenti sul branch (solo commit specifici)")
        if dashboard_data["commits"]:
            df_commits = pd.DataFrame(dashboard_data["commits"]).rename(columns={"sha": "SHA", "message": "Messaggio", "author": "Autore", "date_display": "Data"})[["SHA", "Messaggio", "Autore", "Data"]]
            st.dataframe(df_commits, use_container_width=True, hide_index=True)
        else:
            st.caption("Nessun commit specifico trovato per questo branch.")

        st.markdown("##### Riepilogo autori sul branch")
        if dashboard_data["author_overview"]:
            df_auth = pd.DataFrame(dashboard_data["author_overview"]).rename(
                columns={"display": "Autore", "commits": "Commit", "first_date_display": "Primo commit", "last_date_display": "Ultimo commit", "days_active": "Giorni attivi"}
            )[["Autore", "Commit", "Primo commit", "Ultimo commit", "Giorni attivi"]]
            st.dataframe(df_auth, use_container_width=True, hide_index=True)
        else:
            st.caption("Nessuna attività autori trovata per questo branch.")

    # Issue e PR
    with tab_issues:
        left, right = st.columns(2)
        with left:
            st.markdown("#### Issue (ultime 50)")
            if dashboard_data["issues"]:
                df_issues = pd.DataFrame(dashboard_data["issues"]).rename(
                    columns={"number": "Numero", "title": "Titolo", "state": "Stato", "assignee": "Assegnato a", "updated_display": "Aggiornato", "url": "URL"}
                )[["Numero", "Titolo", "Stato", "Assegnato a", "Aggiornato", "URL"]]
                st.dataframe(df_issues, use_container_width=True, hide_index=True)
            else:
                st.caption("Nessuna issue trovata.")

        with right:
            st.markdown("#### Pull request (ultime 50)")
            if dashboard_data["pulls"]:
                df_pr = pd.DataFrame(dashboard_data["pulls"]).rename(
                    columns={"number": "Numero", "title": "Titolo", "state": "Stato", "author": "Autore", "updated_display": "Aggiornato", "url": "URL"}
                )[["Numero", "Titolo", "Stato", "Autore", "Aggiornato", "URL"]]
                st.dataframe(df_pr, use_container_width=True, hide_index=True)
            else:
                st.caption("Nessuna pull request trovata.")

    # Contributor
    with tab_contrib:
        st.markdown("#### Principali contributor (repo intera)")
        if dashboard_data["contributors"]:
            df_contrib = pd.DataFrame(dashboard_data["contributors"]).rename(columns={"login": "Login", "commits": "Commit", "avatar": "Avatar", "url": "URL"})[["Login", "Commit", "Avatar", "URL"]]
            st.dataframe(df_contrib, use_container_width=True, hide_index=True)
        else:
            st.caption("Nessun contributor trovato.")

    # Autori 360
    with tab_author:
        st.markdown("#### Vista 360 autore sul branch selezionato")

        authors = dashboard_data["author_overview"]
        if not authors:
            st.info("Nessun autore disponibile per il branch selezionato.")
        else:
            options = {a["display"]: a["id"] for a in authors}
            selected_display = st.selectbox("Seleziona autore", list(options.keys()))
            author_id = options[selected_display]

            if st.button("Calcola vista 360 autore"):
                try:
                    summary, commits = compute_author_activity(dashboard_data["owner"], dashboard_data["repo"], dashboard_data["branch"], author_id)
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
                    df_ad = pd.DataFrame(summary["activity_by_day"]).rename(columns={"label": "Data", "total": "Commit"}).set_index("Data")
                    st.line_chart(df_ad, use_container_width=True)
                else:
                    st.caption("Nessun commit datato da mostrare.")

                st.markdown("##### Variazioni per commit (ultimi 50)")
                if commits:
                    df_changes = pd.DataFrame(commits)[["date_display", "additions", "deletions"]].rename(columns={"date_display": "Data", "additions": "Righe aggiunte", "deletions": "Righe rimosse"}).set_index("Data")
                    st.bar_chart(df_changes, use_container_width=True)
                else:
                    st.caption("Nessun dato di diff disponibile.")

                st.markdown("##### Dettaglio commit")
                if commits:
                    df_c = pd.DataFrame(commits).rename(
                        columns={"date_display": "Data", "sha": "SHA", "message": "Messaggio", "additions": "Righe +", "deletions": "Righe -", "files_changed": "File modificati", "file_names": "Nomi file"}
                    )[["Data", "SHA", "Messaggio", "Righe +", "Righe -", "File modificati", "Nomi file"]]
                    st.dataframe(df_c, use_container_width=True, hide_index=True)

                    html_report = generate_author_report_html(summary, commits)
                    st.download_button(
                        label="Scarica report HTML autore",
                        data=html_report,
                        file_name=f"{summary['repo']}_{summary['branch']}_{summary['author_id']}_attivita.html",
                        mime="text/html",
                    )
                else:
                    st.caption("Nessun commit trovato per questo autore.")

    # Responsabile del progetto
    with tab_pm:
        st.markdown("#### Responsabile del progetto")

        owner = dashboard_data["owner"]
        repo = dashboard_data["repo"]
        branch = dashboard_data["branch"]
        repo_key = make_repo_key(owner, repo, branch)

        saved = load_pm_state(repo_key)

        colA, colB = st.columns(2)

        with colA:
            start_default = saved.get("project_start")
            try:
                start_default = dt.date.fromisoformat(start_default) if start_default else dt.date.today()
            except Exception:
                start_default = dt.date.today()
            project_start = st.date_input("Data inizio progetto", value=start_default, key=f"pm_start_{repo_key}")

        with colB:
            end_default = saved.get("project_end")
            try:
                end_default = dt.date.fromisoformat(end_default) if end_default else dt.date.today()
            except Exception:
                end_default = dt.date.today()
            project_end = st.date_input("Data fine progetto", value=end_default, key=f"pm_end_{repo_key}")

        st.markdown("##### Date di estensione")

        if "pm_extensions" not in st.session_state:
            st.session_state.pm_extensions = {}
        if repo_key not in st.session_state.pm_extensions:
            ext_saved = saved.get("extensions", [])
            parsed_ext = []
            for x in ext_saved:
                try:
                    parsed_ext.append(dt.date.fromisoformat(x))
                except Exception:
                    pass
            st.session_state.pm_extensions[repo_key] = parsed_ext

        ext_cols = st.columns([1, 1, 2])
        with ext_cols[0]:
            new_ext = st.date_input("Nuova estensione", value=dt.date.today(), key=f"pm_newext_{repo_key}")
        with ext_cols[1]:
            if st.button("Aggiungi estensione", key=f"pm_addext_{repo_key}"):
                st.session_state.pm_extensions[repo_key].append(new_ext)
        with ext_cols[2]:
            if st.session_state.pm_extensions[repo_key]:
                st.write("Estensioni attive:", ", ".join([d.isoformat() for d in st.session_state.pm_extensions[repo_key]]))
            else:
                st.caption("Nessuna estensione inserita.")

        if st.session_state.pm_extensions[repo_key]:
            if st.button("Svuota estensioni", key=f"pm_clear_ext_{repo_key}"):
                st.session_state.pm_extensions[repo_key] = []

        st.markdown("##### Registro attività sui commit del branch")

        base_df = build_pm_table_from_commits(dashboard_data["commits"])
        base_df = merge_saved_inputs(base_df, saved.get("commit_inputs", {}))

        edited = st.data_editor(
            base_df,
            use_container_width=True,
            height=420,
            hide_index=True,
            column_config={
                "Activity Tag": st.column_config.SelectboxColumn("Activity Tag", options=[""] + ACTIVITY_TAG_OPTIONS, required=False),
                "Activity Description": st.column_config.TextColumn("Activity Description", required=False),
                "sha_full": st.column_config.TextColumn("sha_full", disabled=True),
            },
            disabled=["SHA", "Messaggio", "Autore", "Data e ora commit", "sha_full"],
        )

        save_cols = st.columns([1, 1, 2])
        with save_cols[0]:
            if st.button("Salva modifiche", key=f"pm_save_{repo_key}"):
                pm_state = {
                    "project_start": project_start.isoformat(),
                    "project_end": project_end.isoformat(),
                    "extensions": [d.isoformat() for d in st.session_state.pm_extensions[repo_key]],
                    "commit_inputs": extract_inputs_map(edited),
                    "updated_at": dt.datetime.utcnow().isoformat(),
                }
                save_pm_state(repo_key, pm_state)
                st.success("Dati progetto salvati.")

        with save_cols[1]:
            if st.button("Elimina dati progetto", key=f"pm_delete_{repo_key}"):
                delete_pm_state(repo_key)
                st.session_state.pm_extensions[repo_key] = []
                st.success("Dati progetto eliminati. Ricarica la pagina per vedere lo stato pulito.")

        st.markdown("##### Gantt chart")
        if st.button("Genera Gantt chart", key=f"pm_gantt_{repo_key}"):
            tasks_df = make_gantt_dataframe(edited)
            render_gantt_chart(tasks_df=tasks_df, project_end=project_end, extension_dates=st.session_state.pm_extensions[repo_key])

            pm_state = {
                "project_start": project_start.isoformat(),
                "project_end": project_end.isoformat(),
                "extensions": [d.isoformat() for d in st.session_state.pm_extensions[repo_key]],
                "commit_inputs": extract_inputs_map(edited),
                "updated_at": dt.datetime.utcnow().isoformat(),
            }
            save_pm_state(repo_key, pm_state)

            st.caption("L’area evidenziata dopo la data fine progetto rappresenta la fase di estensione.")

if __name__ == "__main__":
    main()
