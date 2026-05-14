# Suggested Commands

## Development
```bash
pip install -e ".[dev]"
conducere --repo-path /path/to/data --web-port 24298
```

## Testing
```bash
python3 -m pytest tests/
python3 -m pytest tests/ -v          # verbose
python3 -m pytest tests/conducere/test_session_store.py -v  # single file
python3 -m pytest tests/conducere/test_web.py::TestJoinAPI -v  # single class
```

## Formatting & Linting
```bash
ruff format .
ruff check .
```

## System utils (Darwin)
```bash
git, ls, find, grep
```
