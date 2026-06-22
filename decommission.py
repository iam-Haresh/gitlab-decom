"""
GitLab decommission tool.

Run modes:
    python decommission.py summary   # Job 1 - show what WOULD change (no changes)
    python decommission.py apply     # Job 2 - apply the changes + write state.json

The revert step lives in a separate file: revert.py.

Two strategies (chosen with the STRATEGY variable):
    Full_Group   - one top-level group (+ subgroups): downgrade LDAP roles to
                   Reporter (only links currently above Reporter, and never
                   App-Appsec-Dev), tag active projects with DSO-Migrated,
                   then optionally archive them.
    APMID_BASED  - several groups (+ subgroups): tag active projects that carry
                   the APM-ID topic with DSO-Migrated, then optionally archive.
"""

import sys

import gitlab

import common

log = common.log


# --- Validation --------------------------------------------------------------

def validate_config(config):
    """Stop early with a clear message if required variables are missing."""
    strategy = config["strategy"]
    if strategy == common.STRATEGY_FULL_GROUP:
        if not config["group_id"]:
            sys.exit("GROUP_ID is required for the Full_Group strategy")
    elif strategy == common.STRATEGY_APMID_BASED:
        if not config["apm_id"]:
            sys.exit("APM_ID is required for the APMID_BASED strategy")
        if not config["group_ids"]:
            sys.exit("GROUP_IDS is required for the APMID_BASED strategy")
    else:
        sys.exit(
            f"STRATEGY must be '{common.STRATEGY_FULL_GROUP}' or "
            f"'{common.STRATEGY_APMID_BASED}'"
        )


# --- Collecting the targets --------------------------------------------------

def collect_groups_for_ldap(gl, config):
    """Full_Group only: the top group plus every subgroup at any depth."""
    log.info("Collecting groups for LDAP starting at group %s", config["group_id"])
    top = gl.groups.get(config["group_id"])
    groups = [top]
    for sub in top.descendant_groups.list(all=True):
        groups.append(gl.groups.get(sub.id))
    log.info("Found %d group(s) (top group + subgroups)", len(groups))
    return groups


def collect_projects(gl, config):
    """Return the full Project objects we should tag (and maybe archive).

    Active only (archived projects are skipped) and never shared projects.
    For APMID_BASED we keep only projects that carry the APM-ID topic.
    """
    if config["strategy"] == common.STRATEGY_FULL_GROUP:
        group_ids = [config["group_id"]]
    else:
        group_ids = config["group_ids"]

    log.info("Collecting projects from group(s): %s", ", ".join(map(str, group_ids)))
    projects = []
    seen = set()  # avoid handling the same project twice (groups can overlap)
    for gid in group_ids:
        group = gl.groups.get(gid)
        group_projects = group.projects.list(
            include_subgroups=True,  # also look inside subgroups
            archived=False,          # ignore archived repos
            with_shared=False,       # ignore shared projects
            all=True,
        )
        log.info("Group %s: %d active project(s) found", group.full_path, len(group_projects))
        for gp in group_projects:
            if gp.id in seen:
                continue
            seen.add(gp.id)

            # group.projects gives a lightweight object; fetch the real one
            # so we can read/change topics and archive it.
            project = gl.projects.get(gp.id)

            if config["strategy"] == common.STRATEGY_APMID_BASED:
                if config["apm_id"] not in project.topics:
                    log.info(
                        "Skipping %s (missing APM-ID topic %r)",
                        project.path_with_namespace, config["apm_id"],
                    )
                    continue

            projects.append(project)
    log.info("Collected %d project(s) to process", len(projects))
    return projects


# --- Building the plan -------------------------------------------------------

def plan_ldap_changes(groups):
    """Find LDAP links to downgrade to Reporter (Full_Group only)."""
    changes = []
    for group in groups:
        # A group may have no LDAP mapping at all. Listing then returns a 404
        # on some GitLab setups - treat that as "nothing to do" with a warning
        # rather than crashing the whole run.
        try:
            links = group.ldap_group_links.list()
        except gitlab.exceptions.GitlabError as e:
            if common.is_not_found(e):
                log.warning(
                    "Group %s has no LDAP links mapped (404) - skipping",
                    group.full_path,
                )
                continue
            raise

        if not links:
            log.warning("Group %s has no LDAP links mapped - skipping", group.full_path)
            continue

        log.info("Group %s: inspecting %d LDAP link(s)", group.full_path, len(links))
        for link in links:
            cn = getattr(link, "cn", None)
            ldap_filter = getattr(link, "filter", None)
            old_access = link.group_access
            name = cn or f"filter:{ldap_filter}"

            # Never touch the AppSec link (compare without caring about case).
            if cn and cn.lower() == common.EXCLUDED_LDAP_CN:
                log.info("Keeping protected LDAP link %s on %s", name, group.full_path)
                continue
            # Only downgrade. Skip links already at Reporter or lower.
            if old_access <= common.REPORTER:
                log.info(
                    "Skipping LDAP link %s on %s (already at %s <= Reporter)",
                    name, group.full_path, old_access,
                )
                continue

            log.info(
                "Planning downgrade of LDAP link %s on %s (%s -> %s)",
                name, group.full_path, old_access, common.REPORTER,
            )
            changes.append({
                "group_id": group.id,
                "group_path": group.full_path,
                "cn": cn,
                "filter": ldap_filter,
                "provider": link.provider,
                "old_access": old_access,
                "new_access": common.REPORTER,
            })
    return changes


def plan_project_changes(projects):
    """Work out the new topic list for each project (all are archived)."""
    changes = []
    for project in projects:
        old_topics = list(project.topics)
        new_topics = list(old_topics)
        if common.NEW_TOPIC not in new_topics:
            new_topics.append(common.NEW_TOPIC)

        changes.append({
            "project_id": project.id,
            "path": project.path_with_namespace,
            "old_topics": old_topics,
            "new_topics": new_topics,
        })
    return changes


def build_plan(gl, config):
    """Build the full list of changes, without making any of them."""
    plan = {
        "strategy": config["strategy"],
        "ldap_changes": [],
        "project_changes": [],
    }

    log.info("Building plan (strategy=%s)", config["strategy"])

    # LDAP role changes only happen for Full_Group. (APMID_BASED never touches
    # LDAP.) Groups without LDAP links mapped are skipped with a warning.
    if config["strategy"] == common.STRATEGY_FULL_GROUP:
        log.info("Step 1/2: planning LDAP role changes")
        groups = collect_groups_for_ldap(gl, config)
        plan["ldap_changes"] = plan_ldap_changes(groups)
    else:
        log.info("Step 1/2: LDAP role changes not applicable (strategy=%s)", config["strategy"])

    log.info("Step 2/2: planning project changes")
    projects = collect_projects(gl, config)
    plan["project_changes"] = plan_project_changes(projects)
    log.info(
        "Plan ready: %d LDAP change(s), %d project change(s)",
        len(plan["ldap_changes"]), len(plan["project_changes"]),
    )
    return plan


# --- Job 1: summary ----------------------------------------------------------

def print_summary(plan):
    """Print everything that will change, as tables, for review."""
    print("=" * 70)
    print(f"DECOMMISSION SUMMARY   strategy={plan['strategy']}")
    print("Archive projects: yes (always)")
    print("=" * 70)

    if plan["strategy"] != common.STRATEGY_FULL_GROUP:
        print("\nLDAP role changes: N/A for this strategy")
    else:
        print("\nLDAP role changes (downgrade to Reporter):")
        rows = []
        for c in plan["ldap_changes"]:
            name = c["cn"] or f"filter:{c['filter']}"
            rows.append([c["group_path"], name, c["old_access"], c["new_access"]])
        common.print_table(
            ["Group", "LDAP CN", "Old", f"New({common.REPORTER})"], rows
        )

    print("\nProject changes (add topic, then archive):")
    rows = []
    for c in plan["project_changes"]:
        already = common.NEW_TOPIC in c["old_topics"]
        topic_note = "(already present)" if already else f"+ {common.NEW_TOPIC}"
        existing = ", ".join(c["old_topics"]) if c["old_topics"] else "(none)"
        rows.append([
            c["project_id"],
            c["path"],
            existing,
            topic_note,
            "yes",
        ])
    common.print_table(
        ["ID", "Project", "Existing topics", "Topic", "Archive"], rows
    )


# --- Job 2: apply ------------------------------------------------------------

def apply(gl, plan):
    """Make the changes and record how to undo them in state.json.

    We record each change BEFORE making it and save the state in a `finally`
    block, so even a crash half-way through still leaves a usable state file
    for revert.py.
    """
    state = {
        "strategy": plan["strategy"],
        "ldap_changes": [],
        "project_changes": [],
    }

    try:
        # 1) LDAP role downgrades.
        log.info("Applying %d LDAP role change(s)", len(plan["ldap_changes"]))
        for c in plan["ldap_changes"]:
            state["ldap_changes"].append(c)  # keeps old_access for revert
            name = c["cn"] or f"filter:{c['filter']}"
            log.info("LDAP: downgrading %s / %s -> Reporter", c["group_path"], name)
            group = gl.groups.get(c["group_id"])
            common.set_ldap_link_access(
                group, c["cn"], c["filter"], c["provider"], c["new_access"]
            )

        # 2) Project topic add + archive.
        log.info("Applying %d project change(s)", len(plan["project_changes"]))
        for c in plan["project_changes"]:
            record = {
                "project_id": c["project_id"],
                "path": c["path"],
                "old_topics": c["old_topics"],
                "archived_by_us": False,
            }
            state["project_changes"].append(record)

            log.info("TOPIC: %s += %s", c["path"], common.NEW_TOPIC)
            project = gl.projects.get(c["project_id"])
            common.set_project_topics(project, c["new_topics"])

            log.info("ARCHIVE: %s", c["path"])
            common.archive_project(project)
            record["archived_by_us"] = True
    finally:
        common.save_state(state)


# --- Entry point -------------------------------------------------------------

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("summary", "apply"):
        print("Usage: python decommission.py [summary|apply]")
        sys.exit(1)

    mode = sys.argv[1]
    log.info("Starting decommission in '%s' mode", mode)
    config = common.load_config()
    validate_config(config)

    gl = common.get_client()
    plan = build_plan(gl, config)

    # Always show the summary first, in both modes.
    print_summary(plan)

    if mode == "apply":
        log.info("Applying changes...")
        apply(gl, plan)
        log.info("Done.")
    else:
        log.info("Summary mode - no changes were made.")


if __name__ == "__main__":
    main()
