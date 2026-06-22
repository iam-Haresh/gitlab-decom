"""
Shared helpers for the GitLab decommission scripts.

Everything that talks to GitLab or that both decommission.py and revert.py
need lives here, so the two scripts stay short and easy to read.
"""

import json
import logging
import os
import sys

import gitlab


# --- Logging -----------------------------------------------------------------

def setup_logging():
    """Configure a console logger shared by every script.

    Logs go to stdout with a timestamp and level so each step is easy to
    follow in the CI job output. Calling this more than once is safe.
    """
    logger = logging.getLogger("decom")
    if logger.handlers:  # already configured (e.g. imported twice)
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


# Module-level logger used everywhere: common.log.info(...) / .warning(...).
log = setup_logging()


def is_not_found(error):
    """True if a GitLab error is an HTTP 404 (resource/mapping not found)."""
    return getattr(error, "response_code", None) == 404


# --- Constants ---------------------------------------------------------------

NEW_TOPIC = "DSO-Migrated"          # topic we add to every migrated project
REPORTER = 20                       # GitLab access level number for "Reporter"
                                    # (10=Guest, 20=Reporter, 30=Developer,
                                    #  40=Maintainer, 50=Owner)
EXCLUDED_LDAP_CN = "app-appsec-gitlab-developer" # LDAP cn we must NEVER change (lower-case)
STATE_FILE = "state.json"           # where apply writes the revert information

# Allowed values for the STRATEGY variable.
STRATEGY_FULL_GROUP = "Full_Group"
STRATEGY_APMID_BASED = "APMID_BASED"


# --- Connection & configuration ---------------------------------------------

def get_client():
    """Create and log in to a GitLab API client using environment variables."""
    url = os.environ["CI_SERVER_URL"]  # predefined by GitLab CI (e.g. https://gitlab.com)
    token = os.environ["GITLAB_PRIVATE_TOKEN"]
    log.info("Connecting to GitLab at %s", url)
    gl = gitlab.Gitlab(url, private_token=token, ssl_verify=False)
    gl.auth()  # fail fast and clearly if the token/url is wrong
    log.info("Authenticated to GitLab as %s", gl.user.username)
    return gl


def load_config():
    """Read all inputs from CI/CD variables into a simple dictionary."""
    group_ids_raw = os.environ.get("GROUP_IDS", "")
    group_ids = [g.strip() for g in group_ids_raw.split(",") if g.strip()]

    archive_flag = os.environ.get("ARCHIVE_ENABLED", "false").strip().lower()
    ldap_flag = os.environ.get("LDAP_ENABLED", "true").strip().lower()

    return {
        "strategy": os.environ.get("STRATEGY", "").strip(),
        "group_id": os.environ.get("GROUP_ID", "").strip(),
        "apm_id": os.environ.get("APM_ID", "").strip(),
        "group_ids": group_ids,
        "archive_enabled": archive_flag == "true",
        "ldap_enabled": ldap_flag == "true",
    }


# --- GitLab actions (reused by both apply and revert) ------------------------

def set_ldap_link_access(group, cn, ldap_filter, provider, access_level):
    """Change an LDAP group link's access level.

    GitLab has no "update" endpoint for LDAP links, so we delete the existing
    link and add it back with the access level we want.

    If the link is not mapped (the group has no matching LDAP link, e.g. on a
    personal account or after a manual change), we log a warning and skip it
    instead of failing with a 404.
    """
    name = cn or f"filter:{ldap_filter}"

    # Find the matching live link and delete it. We call .delete() on the link
    # object itself because python-gitlab sends the provider + cn/filter that
    # the GitLab delete endpoint needs.
    try:
        links = group.ldap_group_links.list()
    except gitlab.exceptions.GitlabError as e:
        if is_not_found(e):
            log.warning(
                "LDAP link %s on group %s is not mapped (404) - skipping",
                name, group.full_path,
            )
            return
        raise

    matched = False
    for link in links:
        if link.provider != provider:
            continue
        same_cn = cn and getattr(link, "cn", None) == cn
        same_filter = not cn and getattr(link, "filter", None) == ldap_filter
        if same_cn or same_filter:
            log.info("Deleting existing LDAP link %s on %s", name, group.full_path)
            link.delete()
            matched = True
            break

    if not matched:
        log.warning(
            "LDAP link %s on group %s is not mapped - skipping",
            name, group.full_path,
        )
        return

    # Re-create the link with the access level we want.
    data = {"group_access": access_level, "provider": provider}
    if cn:
        data["cn"] = cn
    else:
        data["filter"] = ldap_filter
    log.info(
        "Re-creating LDAP link %s on %s at access level %s",
        name, group.full_path, access_level,
    )
    group.ldap_group_links.create(data)


def set_project_topics(project, topics):
    """Replace a project's topics with the given list and save."""
    log.info("Setting topics on %s -> %s", project.path_with_namespace, topics)
    project.topics = topics
    project.save()


def archive_project(project):
    log.info("Archiving project %s", project.path_with_namespace)
    project.archive()


def unarchive_project(project):
    log.info("Unarchiving project %s", project.path_with_namespace)
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
    log.info(
        "Saved revert state to %s (%d LDAP, %d project changes)",
        STATE_FILE,
        len(state.get("ldap_changes", [])),
        len(state.get("project_changes", [])),
    )


def load_state():
    """Read the revert information back from disk."""
    log.info("Loading revert state from %s", STATE_FILE)
    with open(STATE_FILE) as f:
        return json.load(f)
