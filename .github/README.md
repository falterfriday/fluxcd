# CI for this GitOps repository

Every check renders the manifests the way Flux will apply them — per-cluster
patches included — and inspects the result. Nothing invents a separate source of
truth.

## Workflows

| workflow | trigger | runner | blocking |
| --- | --- | --- | --- |
| `validate` | PR, push to main | GitHub | yes |
| `security` | PR, push, weekly | GitHub | partly (see below) |
| `image-scan` | weekly | GitHub | no |
| `flux-version-check` | monthly | GitHub | no — opens an issue |
| `promotion` | manual | GitHub | no |
| `pr-labeler` | PR opened/updated | GitHub | no |
| `repo-hygiene` | monthly | GitHub | no |
| `deploy` | push to main | **self-hosted** | yes |
| `drift-detection` | daily | **self-hosted** | yes |
| `backup-check` | daily | **self-hosted** | yes |

Blocking vs reporting is deliberate. Blocking checks describe something wrong
*right now*: a leaked secret, a manifest that will not build, a chart whose
content changed under a pinned version. Reporting checks track findings that
already exist — the repository carries a known backlog of them, and a
permanently red required check trains everyone to ignore red checks.

## The self-hosted runner

`deploy`, `drift-detection` and `backup-check` need cluster access. Every
endpoint in this homelab is RFC1918 — API servers on `10.120.x`, ingress via
MetalLB at `10.120.0.200` and `10.120.1.200` — so GitHub-hosted runners cannot
reach them.

Register a runner on the cluster network with the label `fluxcd` (declared in
`.github/actionlint.yaml`), and give it:

- `kubectl` and `flux` on PATH, with the Flux CLI matching the cluster
  (`FLUX_VERSION` in `validate.yaml`, currently 2.9.3)
- `jq` and `python3`
- a kubeconfig with contexts named exactly `staging` and `production`

The runner needs read access for drift and backup checks; `deploy` additionally
reconciles the Flux git source. Until the runner exists, those three workflows
queue and never run — the GitHub-hosted ones are unaffected.

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
