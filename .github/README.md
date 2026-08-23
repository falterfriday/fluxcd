# CI for this GitOps repository

Every check renders the manifests the way Flux will apply them — per-cluster
patches included — and inspects the result. Nothing invents a separate source of
truth.

## Workflows

| workflow | trigger | blocking |
| --- | --- | --- |
| `validate` | PR, push to main | yes |
| `security` | PR, push, weekly | partly (see below) |
| `image-scan` | weekly | no |
| `flux-version-check` | monthly | no — opens an issue |
| `promotion` | manual | no |
| `pr-labeler` | PR opened/updated | no |
| `repo-hygiene` | monthly | no |

Blocking vs reporting is deliberate. Blocking checks describe something wrong
*right now*: a leaked secret, a manifest that will not build, a chart whose
content changed under a pinned version. Reporting checks track findings that
already exist — the repository carries a known backlog of them, and a
permanently red required check trains everyone to ignore red checks.

## Cluster checks are manual

Three things a GitOps pipeline would normally do — verifying that a merge
actually converged, detecting drift, and checking backup coverage — have no CI
job here. Every cluster endpoint in this homelab is RFC1918 (API servers on
`10.120.x`, ingress via MetalLB at `10.120.0.200` and `10.120.1.200`), so
GitHub-hosted runners cannot reach them, and there is no self-hosted runner.

The logic exists as scripts you run yourself from a machine with cluster access.
They need `kubectl`, `flux`, `jq` and `python3` on PATH, and kubeconfig contexts
named `staging` and `production`.

```sh
# Did the clusters converge on what is in git?
.github/scripts/reconcile.sh production "$(git rev-parse --short HEAD)" --check-only

# Does live state still match the repository? (prune: false makes this matter)
.github/scripts/check-drift.sh staging
.github/scripts/check-drift.sh production

# Is every CNPG database backed up, and recently?
.github/scripts/check-backups.py staging
.github/scripts/check-backups.py production
```

`check-backups.py` reports two different failures: a database with **no**
ScheduledBackup at all, and one whose most recent attempt failed or has aged
out. The first is the one monitoring cannot see — nothing is failing, there is
simply no backup.

Worth knowing what is given up by not running these on a schedule: drift and
backup coverage regress silently between manual runs. If that becomes a problem,
the options are a self-hosted runner with cluster credentials, or in-cluster
CronJobs reporting through the existing Alertmanager → Slack path — which keeps
GitHub out of the cluster entirely.

## Required status checks

The gates only gate if branch protection requires them. `repo-hygiene` audits
this monthly and reports drift from the intended configuration:

- `sops guard`
- `lint`
- `build and schema-validate`
- `secret scan`
- `manifest policy and misconfiguration`

Also expected on `main`: required PR review, code-owner review, dismiss stale
reviews, branches up to date, force pushes and deletions blocked.

## Policies

`.github/policies/enforce/` is blocking — the repository satisfies it today, so
a failure is a regression. `.github/policies/audit/` reports gaps that exist
now. Move a policy from `audit/` to `enforce/` once the findings are cleared;
that is the intended ratchet.

## Regenerating the chart digest lockfile

After an intentional chart bump:

```sh
.github/scripts/render-all.sh /tmp/rendered
.github/scripts/chart-digests.py /tmp/rendered --update
```

A *new* version appearing is a warning. A *changed digest for a version already
in the lockfile* is an error: it means upstream republished content under a tag
this repository already trusts.
