# Style & Conventions

- Python code follows **ruff** defaults for formatting and linting
- **No comments** unless the WHY is non-obvious
- Frontend: no framework, no build step. XSS-safe DOM construction (textContent for user data, marked.js with safe renderer for markdown)
- Git commit messages: imperative mood, concise
- Tokens never serialized to git or API responses (except tokens.json for persistence)
- Type hints used throughout (Python 3.12+ style: `dict[str, str]`, `list[str] | None`)
- Pydantic models for data validation
- Tests use pytest with pytest-asyncio for async tests
