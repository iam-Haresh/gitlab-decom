# Action Items / TODO

Things to take care of before running this for real. Tick them off as you go.

## Before production
- [x] **Remove the `LDAP_ENABLED` flag** from `common.py`, `decommission.py`,
      `.gitlab-ci.yml`, and `README.md`. Done — Full_Group now always runs LDAP
      downgrades; APMID_BASED never touches LDAP.
- [ ] **Delete `.env.local`** (local validation only; never commit it).
- [ ] **Validate the LDAP path on a staging EE instance.** It was never exercised
      on the personal/SaaS account (no LDAP group links there), so the LDAP
      downgrade + revert branch has zero live coverage.

## Token & permissions
- [ ] Use a `GITLAB_PRIVATE_TOKEN` (masked project CI/CD variable) whose user has:
  - [ ] **Admin rights** for LDAP group-link changes (owner/admin operation on EE).
  - [ ] **Owner/Maintainer** on the target group for topic + archive changes.
- [ ] Confirm the token has the **`api`** scope.

## Pipeline / artifacts
- [ ] Decide on **artifact retention** for `state.json`. The `apply` job has no
      `expire_in`, so it uses the instance default (often 30 days). If the revert
      window may be longer, set an explicit `expire_in` (e.g. `90 days` / `never`)
      on the `apply` job's artifacts.
- [ ] Remember **revert is same-pipeline only** (`needs: [apply]`). To revert later,
      archive `state.json` somewhere durable.

## Operational gotchas
- [ ] **Run `apply` once per group.** When `ARCHIVE_PROJECTS=true`, projects are
      archived and already-archived projects are skipped on collection, so a clean
      re-run is safe. Avoid re-running after a partial/manual change: `old_topics` is
      re-recorded from the current state, so if `DSO-Migrated` is already present
      a later revert won't remove it. (With archiving off, re-runs re-tag the same
      active projects, which is harmless but redundant.)
- [ ] **Announce to affected teams** — role downgrades and archiving are user-visible.
- [x] **Self-managed SSL** — the client sets `ssl_verify=False` in `get_client`
      so private/self-signed CAs work. Note: this disables TLS verification (no
      MITM protection) and emits an urllib3 `InsecureRequestWarning`.
- [ ] **Always review the `summarize` job log before running `apply`.**

## Optional improvements
- [ ] `APMID_BASED` fetches each project fully to check its topic. For very large
      groups, consider a server-side `topic=` filter on the project list call
      (verify the group projects endpoint supports it on your instance first).
- [ ] Runtime-validate the `APMID_BASED` strategy end-to-end (only `Full_Group`
      was tested live).
