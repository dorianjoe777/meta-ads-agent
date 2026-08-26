# Release canary runbook

Every Admira IA code, dependency, prompt-runtime, MCP, Hermes, installer, or
update-flow change must pass this process before it is described as successful
or promoted to the stable buyer update channel.

## Principle

Hermes is a product runtime, not the product maintainer. It must never update
itself, change its dependencies, patch compatibility code, or silently work
around an upstream change. It may report a structured incompatibility. Admira
maintainers own the reproduction, patch, canary validation, release, and stable
promotion.

No secrets, DigitalOcean tokens, host passwords, private keys, buyer tokens, or
passphrases are stored in the repository. The maintained DigitalOcean Admira
installation is the real canary target. Its access credentials are supplied
out-of-band by the release operator.

## Maintainer canary access profile

The release operator has authorized this maintained DigitalOcean installation
as the default real canary for every future product update. Keep its access
material in the local operating-system keychain, never in this repository,
shell history, test fixture, release ZIP, or command output.

- DigitalOcean API-token keychain service: `Admira IA DigitalOcean canary API token`
- SSH public-key label: `admiro-ai`
- Expected public-key fingerprint: `SHA256:FZChXLFsPiuKNr+eELAB9s3R4OiWE2YZhw/Sk800Vbw`
- Canary Droplet ID: `582080576`
- Expected container: `meta-ads-agent-meta-ads-agent-1`

Before every remote canary, retrieve the API credential only into the current
process environment, for example on macOS:

```bash
export DIGITALOCEAN_TOKEN="$(security find-generic-password -a "$USER" -s 'Admira IA DigitalOcean canary API token' -w)"
```

Use the API to resolve the current public IP at runtime; do not hard-code an IP
in a release script because Droplets can be rebuilt or reassigned.

The matching **private** SSH identity must be available locally and must match
the fingerprint above. A public key and its passphrase alone cannot establish
SSH access. If the private identity is unavailable, stop before promotion and
restore access through the DigitalOcean web console by re-authorizing the
approved public key; do not bypass the remote canary or substitute a buyer
installation.

## Required sequence

Before the sequence below, run
`./scripts/verify-canary-integrity.sh CONTAINER` as the final provenance gate.
It confirms that the clean worktree, commit, version tag, image labels, and
running container all describe one source manifest. The full operator
checklist is in `docs/canary-integrity-release-checklist.md`.

1. Implement the change and add a regression test for the observed failure.
2. Pin every dependency whose compatibility matters. Do not introduce an
   unbounded `latest`, branch, or `>=` dependency for Hermes or MCP.
3. Run the local suite and `python3 scripts/release_canary.py`.
4. Build the source package from a clean worktree with
   `scripts/package-release.sh`. A package is an artifact, **not** a stable
   release yet.
5. Install that exact candidate build on the maintained DigitalOcean canary.
   Confirm its `/app/VERSION` matches the candidate version.
6. Run the real safe canary, supplying credentials only through the operator
   environment/session:

   ```bash
   ./scripts/run-remote-canary-release.sh \
     root@CANARY_HOST ~/.ssh/CANARY_IDENTITY CANARY_CONTAINER
   ```

   It verifies the MCP bridge and runs one real Hermes response in a fresh,
   temporary Hermes home. The response is bounded by a hard timeout and cannot
   load the buyer's conversation/session cache. Those checks must not
   create/edit/delete Meta objects, send a Telegram message, generate media,
   or restart the Gateway. A timeout is a failed gate; never rerun it in a
   loop on the canary.

   For a direct check from the canary host, `run-canary-release.sh` defaults
   to the Docker runtime home `/app/runtime/hermes`. The legacy
   `/app/dashboard/data/hermes-home` path is migration input only and must not
   be used as the active smoke-test configuration.
7. Inspect the result and container logs. If any check fails, keep the release
   off the stable registry, write the regression test, and repeat from step 1.
8. Only after the remote canary passes may the operator publish the package to
   the stable release registry. Then—and only then—may the dashboard/Telegram
   updater notify buyers.

## What counts as a failure

- MCP tool discovery differs from the product contract.
- Hermes cannot call either safe product tool.
- A Python/MCP field, transport, SDK, auth, or packaging incompatibility
  appears.
- Candidate version differs from the artifact version.
- The bounded agent smoke times out, returns a different response, or leaves
  a test process alive.
- A check attempts a buyer-facing action or relies on an unpinned dependency.

Never hot-patch a buyer installation and call that a release fix. A temporary
support patch can restore one installation, but the same correction must be
made in source, regression-tested, canaried on the maintained Droplet, and
published normally before it reaches other buyers.
