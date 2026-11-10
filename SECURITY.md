# Security policy

## Reporting a problem

If you have access to this private repository, report the issue through its
[GitHub issue tracker](https://github.com/DavidDiazMerino/hermes-pathfinder/issues/new).
If the repository becomes public, use **Report a vulnerability** on its Security tab when available.
Otherwise, open an issue asking for a private contact and share the details once you have one.
[GitHub private reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)

## Evidence gate

The gate stops hallucinated or untested skills from being saved. It is not a sandbox: an agent
with unrestricted shell access running as your user could still work around it.

## Data stored locally

Pathfinder stores the following under `<HERMES_HOME>/plugin-data/enterprise-pathfinder/`.

- Full parsed contracts as JSON, their hashes, lab results and skill evidence links.
- Source records with URL, title when available, trust tier, content hash and content length.
- Documents fetched by `pathfinder_read` and their cache metadata.

There is no automatic cleanup. Deleting the directory also removes the evidence history.
