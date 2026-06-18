# GitLab 1.0 → 2.0 Migration / Decommission Tooling

## Context
After a top-level group is migrated from GitLab 1.0 to GitLab 2.0 SaaS, we decommission it on
the source side in a controlled, reviewable, reversible way. Runs as a 3-job GitLab CI
pipeline, built on `python-gitlab`, simple enough for a fresher to read, with revert logic in
its own file.

### Confirmed decisions
- Role change targets **LDAP Group Links** (group LDAP-sync config), not direct members.
- Inputs come from **CI/CD variables**; server URL is the predefined **`CI_SERVER_URL`**.
- Job 3 reverts using a **state JSON artifact produced by Job 2** (same pipeline).
- **One strategy per pipeline run**, selected by `STRATEGY` (`Full_Group` | `APMID_BASED`).

## Strategies
- **`Full_Group`** (one top-level group + subgroups): downgrade each LDAP group-link role to
  **Reporter (30)** — only when currently **above** Reporter, and **never** the `App-Appsec-Dev`
  link (cn match, case-insensitive); add the `DSO-Migrated` topic to every active project;
  optionally archive them.
- **`APMID_BASED`** (several groups + subgroups): find active projects carrying the `APM_ID`
  topic, add `DSO-Migrated`, optionally archive. **No LDAP changes.**
- Archived projects and shared projects are always ignored.

## Files (implemented)
```
.gitlab-ci.yml     # 3 jobs (summarize auto, apply manual, revert manual) + prefilled vars
requirements.txt   # python-gitlab>=4.0.0
common.py          # get_client (CI_SERVER_URL + token), load_config, GitLab actions,
                   #   print_table, save/load_state, constants
decommission.py    # Job 1 summary + Job 2 apply (both strategies)
revert.py          # Job 3 revert logic (separate file)
README.md          # variables + how to run
.gitignore         # .venv, __pycache__, state.json
```

## Key API facts (python-gitlab 6.x, verified)
- LDAP links: `group.ldap_group_links` supports list/create/delete. Create requires
  `provider` + `group_access` + exactly one of `cn`/`filter`. There is no update endpoint, so
  `set_ldap_link_access` finds the live link and calls **`link.delete()`** (which sends the
  provider + cn/filter the API needs), then re-creates it with the new access level.
- Projects: `group.projects.list(include_subgroups=True, archived=False, with_shared=False,
  all=True)` → lightweight; re-fetch full project via `gl.projects.get(id)` to edit.
- Subgroups (for LDAP): `group.descendant_groups.list(all=True)` + the group itself.
- Topics: `project.topics` (list) → append `DSO-Migrated`, `project.save()`.
- Archive/unarchive: `project.archive()` / `project.unarchive()`.

## Revert design
`apply` records, per change: LDAP `old_access`; project original topic list; whether **this
run** archived the project. Records are appended before each mutation and saved in a `finally`
block, so a mid-run crash still leaves a usable `state.json`. `revert.py` restores in safe
order: unarchive → restore topics → restore LDAP roles.

## CI/CD variables
- `CI_SERVER_URL` (predefined by GitLab), `GITLAB_PRIVATE_TOKEN` (masked project var; owner/admin)
- `STRATEGY` = `Full_Group` | `APMID_BASED` (dropdown)
- `ARCHIVE_ENABLED` = `false` | `true` (dropdown)
- `Full_Group`: `GROUP_ID`
- `APMID_BASED`: `APM_ID`, `GROUP_IDS` (comma-separated)

## Verification
1. **Local dry run:** export `CI_SERVER_URL`, `GITLAB_PRIVATE_TOKEN`, `STRATEGY=Full_Group`,
   `GROUP_ID=<test group>`, `ARCHIVE_ENABLED=false`; run `python decommission.py summary` —
   confirm the printed LDAP + project tables look right; no changes made.
2. **Apply on a throwaway group:** `python decommission.py apply`; verify LDAP links above
   Reporter are downgraded (Reporter-or-below and `App-Appsec-Dev` untouched), projects carry
   `DSO-Migrated`, and (if enabled) are archived. Confirm `state.json` is written.
3. **Revert:** `python revert.py`; verify roles, topics, archive status return to pre-apply.
4. Repeat with `STRATEGY=APMID_BASED`, `APM_ID`, `GROUP_IDS` for the topic-based path.
5. Pipeline: Job 1 auto, Jobs 2 & 3 manual, Job 3 consumes Job 2's `state.json` via `needs`.
