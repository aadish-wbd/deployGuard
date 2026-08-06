# deployGuard

Automated production incident investigation agent — Python REST service + Bedrock + JIRA + Slack.

See [REQUIREMENTS.md](REQUIREMENTS.md) and [TEAM.md](TEAM.md) for the spec and team split, and
[RUNBOOK.md](RUNBOOK.md) for setup, configuration, and demo instructions.

## Layout

- `app/` — the FastAPI service (Bedrock invocation, JIRA/Slack, S3 persistence, incidents API)
- `tests/` — unit/integration tests (fakes for Bedrock/JIRA/Slack/S3, no AWS required)
- `team/` — other tracks' design docs (e.g. the EC2 demo app), kept out of the service's way
