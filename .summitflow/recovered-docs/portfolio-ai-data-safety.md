# Data Safety Rules

## Destructive Operations Protocol

**RULE**: NEVER run DELETE, DROP, or bulk modification commands without verification first.

1. **Verify field names** - Run `curl ... | jq '.items[0] | keys'`
2. **Test query first** - SELECT/COUNT before DELETE
3. **Limit scope** - Use LIMIT 1 or dry-run first

## Symbol Standardization

**RULE**: Use `symbol` everywhere. NEVER use `ticker`.

All database tables, Python models, and APIs are standardized on `symbol`.

For detailed PostgreSQL patterns, use the `postgresql-patterns` skill.
