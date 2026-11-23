# Security and privacy

Ash stores material that should be treated as private: conversations, prompts,
memories, model credentials, MCP credentials and notification endpoints.

Before deploying:

- Set different random values for `GATEWAY_SECRET`, `MCP_SECRET` and
  `DASHBOARD_PASSWORD`.
- Keep `.env`, `system_prompt.txt`, database exports and logs out of version
  control.
- Use HTTPS and leave secure Dashboard cookies enabled outside local
  development.
- Do not expose PostgreSQL directly to the internet.
- Give MCP servers only the credentials and permissions they require.
- Review backup files before moving them between environments; backups can
  contain prompts, memories, conversations and tool configuration.

Before publishing a fork, create a repository with fresh Git history. Deleting a
secret or private prompt in a later commit does not remove it from earlier
commits.

If a credential has ever entered Git history, revoke or rotate it. Rewriting the
history alone is not sufficient.
