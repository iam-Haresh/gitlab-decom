"""
Revert the changes made by `decommission.py apply`.

It reads state.json (produced by the apply step) and undoes everything, in the
safest order:
    1. Unarchive any project we archived  (so it can be edited again).
    2. Restore each project's original topic list.
    3. Restore each LDAP link's original access level.

Run:
    python revert.py
"""

import common

log = common.log


def revert_projects(gl, project_changes):
    """Unarchive (if we archived it) and put topics back to the original list."""
    log.info("Reverting %d project change(s)", len(project_changes))
    rows = []
    for c in project_changes:
        log.info("Reverting project %s", c["path"])
        project = gl.projects.get(c["project_id"])

        # Unarchive first - an archived project is read-only and can't be edited.
        if c["archived_by_us"]:
            common.unarchive_project(project)
            project = gl.projects.get(c["project_id"])  # refresh after change

        common.set_project_topics(project, c["old_topics"])
        rows.append([c["project_id"], c["path"], "topics restored",
                     "unarchived" if c["archived_by_us"] else "-"])
    return rows


def revert_ldap(gl, ldap_changes):
    """Set each LDAP link back to the access level it had before apply."""
    log.info("Reverting %d LDAP change(s)", len(ldap_changes))
    rows = []
    for c in ldap_changes:
        name = c["cn"] or f"filter:{c['filter']}"
        log.info(
            "Restoring LDAP link %s on %s to access %s",
            name, c.get("group_path", c["group_id"]), c["old_access"],
        )
        group = gl.groups.get(c["group_id"])
        common.set_ldap_link_access(
            group, c["cn"], c["filter"], c["provider"], c["old_access"]
        )
        rows.append([c.get("group_path", str(c["group_id"])), name, c["old_access"]])
    return rows


def main():
    log.info("Starting revert")
    state = common.load_state()
    gl = common.get_client()

    print("Reverting project changes...")
    project_rows = revert_projects(gl, state.get("project_changes", []))
    common.print_table(["ID", "Project", "Topics", "Archive"], project_rows)

    print("\nReverting LDAP changes...")
    ldap_rows = revert_ldap(gl, state.get("ldap_changes", []))
    common.print_table(["Group", "LDAP CN", "Restored access"], ldap_rows)

    log.info("Revert complete.")


if __name__ == "__main__":
    main()
