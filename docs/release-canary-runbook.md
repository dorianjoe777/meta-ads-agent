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

## Required sequence

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

   It verifies the MCP bridge, discovers tools, asks Hermes to call an empty
   campaign preflight exactly once, and asks it to call empty image validation
   exactly once. Those checks must not create/edit/delete Meta objects, send a
   Telegram message, generate media, or restart the Gateway.
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
- A check attempts a buyer-facing action or relies on an unpinned dependency.

Never hot-patch a buyer installation and call that a release fix. A temporary
support patch can restore one installation, but the same correction must be
made in source, regression-tested, canaried on the maintained Droplet, and
published normally before it reaches other buyers.
