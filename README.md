# GitLab Decommission Tool

Decommissions a GitLab group/projects after they have been migrated from
GitLab 1.0 to GitLab 2.0 SaaS. It runs as a 3-job GitLab CI pipeline:

| Job | Stage | When | What it does |
|-----|-------|------|--------------|
| `summarize` | summarize | automatic | Prints a table of everything that **would** change. No changes made. |
| `apply` | apply | **manual** | Applies the changes and writes `state.json` (artifact). |
| `revert` | revert | **manual** | Undoes everything using `state.json` from `apply`. |

## Strategies

Pick one per pipeline run with the `STRATEGY` variable.

### `Full_Group`
For one top-level group (and all its subgroups):
1. Downgrade every **LDAP group link** role to **Reporter** (access level 20), except
   the link whose `cn` is `App-AppSec-GitLab-Developer` (case-insensitive). Links already
   at Reporter or lower are left unchanged. Groups with no LDAP links mapped are skipped
   with a warning (no 404 failure).
2. Add the `DSO-Migrated` topic to every **active** project (existing topics kept).
3. Archive those projects (only if `ARCHIVE_PROJECTS` is `true`; off by default).

### `APMID_BASED`
Across several groups (and their subgroups):
1. Find **active** projects that carry the APM-ID topic (`APM_ID`).
2. Add the `DSO-Migrated` topic to them (existing topics kept).
3. Archive those projects (only if `ARCHIVE_PROJECTS` is `true`; off by default).

> Archived projects and shared projects are always ignored.
> `APMID_BASED` never changes LDAP roles.

## CI/CD variables

| Variable | Used by | Description |
|----------|---------|-------------|
| `CI_SERVER_URL` | both | GitLab instance URL. **Predefined by GitLab CI** - no need to set it. (For local runs, export it yourself, e.g. `https://gitlab.com`.) |
| `GITLAB_PRIVATE_TOKEN` | both | Personal/group access token. **Mask it.** Needs `api` scope and owner/admin rights (LDAP link changes are an owner/admin operation). |
| `STRATEGY` | both | `Full_Group` or `APMID_BASED`. |
| `GROUP_ID` | `Full_Group` | The single top-level group id. |
| `APM_ID` | `APMID_BASED` | The APM-ID topic to match on. |
| `GROUP_IDS` | `APMID_BASED` | Comma-separated group ids to search, e.g. `12,34,56`. |
| `ARCHIVE_PROJECTS` | both | `true` to archive projects after tagging. Defaults to `false` (no archiving). |

## Files

- `decommission.py` — summary (Job 1) and apply (Job 2).
- `revert.py` — revert logic (Job 3), kept separate.
- `common.py` — shared helpers (connection, config, GitLab actions, table, state).
- `.gitlab-ci.yml` — the 3-job pipeline.
- `requirements.txt` — `python-gitlab`.

## Run locally

```bash
pip install -r requirements.txt

export CI_SERVER_URL="https://gitlab.example.com"
export GITLAB_PRIVATE_TOKEN="xxxxx"
export STRATEGY="Full_Group"
export GROUP_ID="123"

python decommission.py summary    # review - no changes
python decommission.py apply      # apply  - writes state.json
python revert.py                  # undo   - reads state.json
```

For `APMID_BASED`:

```bash
export STRATEGY="APMID_BASED"
export APM_ID="APM12345"
export GROUP_IDS="12,34,56"
```

## How revert works

`apply` records the original state of every change into `state.json`:
- each LDAP link's original `group_access`,
- each project's original topic list,
- whether **this run** archived the project.

`revert.py` reads that file and restores all three, in a safe order (unarchive →
restore topics → restore LDAP roles). The file is produced as a pipeline artifact,
so the revert job picks it up automatically via `needs: [apply]`.
