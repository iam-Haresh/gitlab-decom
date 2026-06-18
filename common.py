"""
Shared helpers for the GitLab decommission scripts.

Everything that talks to GitLab or that both decommission.py and revert.py
need lives here, so the two scripts stay short and easy to read.
"""

import json
import os

import gitlab


# --- Constants ---------------------------------------------------------------

NEW_TOPIC = "DSO-Migrated"          # topic we add to every migrated project
REPORTER = 30                       # GitLab access level number for "Reporter"
EXCLUDED_LDAP_CN = "app-appsec-dev" # LDAP cn we must NEVER change (lower-case)
STATE_FILE = "state.json"           # where apply writes the revert information

# Allowed values for the STRATEGY variable.
STRATEGY_FULL_GROUP = "Full_Group"
STRATEGY_APMID_BASED = "APMID_BASED"


# --- Connection & configuration ---------------------------------------------

def get_client():
    """Create and log in to a GitLab API client using environment variables."""
    url = os.environ["CI_SERVER_URL"]  # predefined by GitLab CI (e.g. https://gitlab.com)
    token = os.environ["GITLAB_PRIVATE_TOKEN"]
    gl = gitlab.Gitlab(url, private_token=token)
    gl.auth()  # fail fast and clearly if the token/url is wrong
    return gl


def load_config():
    """Read all inputs from CI/CD variables into a simple dictionary."""
    group_ids_raw = os.environ.get("GROUP_IDS", "")
    group_ids = [g.strip() for g in group_ids_raw.split(",") if g.strip()]

    archive_flag = os.environ.get("ARCHIVE_ENABLED", "false").strip().lower()

    return {
        "strategy": os.environ.get("STRATEGY", "").strip(),
        "group_id": os.environ.get("GROUP_ID", "").strip(),
        "apm_id": os.environ.get("APM_ID", "").strip(),
        "group_ids": group_ids,
        "archive_enabled": archive_flag == "true",
    }


# --- GitLab actions (reused by both apply and revert) ------------------------

def set_ldap_link_access(group, cn, ldap_filter, provider, access_level):
    """Change an LDAP group link's access level.

    GitLab has no "update" endpoint for LDAP links, so we delete the existing
    link and add it back with the access level we want.
    """
    # Find the matching live link and delete it. We call .delete() on the link
    # object itself because python-gitlab sends the provider + cn/filter that
    # the GitLab delete endpoint needs.
    for link in group.ldap_group_links.list():
        if link.provider != provider:
            continue
        same_cn = cn and getattr(link, "cn", None) == cn
        same_filter = not cn and getattr(link, "filter", None) == ldap_filter
        if same_cn or same_filter:
            link.delete()
            break

    # Re-create the link with the access level we want.
    data = {"group_access": access_level, "provider": provider}
    if cn:
        data["cn"] = cn
    else:
        data["filter"] = ldap_filter
    group.ldap_group_links.create(data)


def set_project_topics(project, topics):
    """Replace a project's topics with the given list and save."""
    project.topics = topics
    project.save()


def archive_project(project):
    project.archive()


def unarchive_project(project):
    project.unarchive()


# --- Output & state ----------------------------------------------------------

def print_table(headers, rows):
    """Print a simple fixed-width text table (no external libraries)."""
    if not rows:
        print("(nothing to show)")
        return

    # Figure out how wide each column needs to be.
    all_lines = [headers] + [[str(cell) for cell in row] for row in rows]
    widths = [max(len(line[i]) for line in all_lines) for i in range(len(headers))]

    def format_row(cells):
        return " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(cells))

    print(format_row(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(format_row(row))


def save_state(state):
    """Write the revert information to disk as JSON."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"\nSaved revert state to {STATE_FILE}")


def load_state():
    """Read the revert information back from disk."""
    with open(STATE_FILE) as f:
        return json.load(f)
