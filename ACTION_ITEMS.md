# Action Items / TODO

Things to take care of before running this for real. Tick them off as you go.

## Before production
- [ ] **Remove the `LDAP_ENABLED` flag** from `common.py`, `decommission.py`,
      `.gitlab-ci.yml`, and `README.md`. It exists only to validate on accounts
      without LDAP; production should always run with LDAP on.
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
- [ ] **Run `apply` once per group.** Re-running with `ARCHIVE_ENABLED=true` is safe
      (archived projects are skipped), but re-running with archive *off* re-records
      `old_topics` already containing `DSO-Migrated`, so a later revert won't remove it.
- [ ] **Announce to affected teams** — role downgrades and archiving are user-visible.
- [ ] **Self-managed SSL** — if the instance uses a private/self-signed CA,
      python-gitlab may need extra SSL configuration (gitlab.com is fine).
- [ ] **Always review the `summarize` job log before running `apply`.**

## Optional improvements
- [ ] `APMID_BASED` fetches each project fully to check its topic. For very large
      groups, consider a server-side `topic=` filter on the project list call
      (verify the group projects endpoint supports it on your instance first).
- [ ] Runtime-validate the `APMID_BASED` strategy end-to-end (only `Full_Group`
      was tested live).
