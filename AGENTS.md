## Python Environment

Always use `uv` to manage Python packages and execution. Never call `python` or `pip` directly.

- Install a package: `uv pip install <package>`
- Uninstall a package: `uv pip uninstall <package>`
- Run any Python script: `uv run python script.py`
- Run a module: `uv run python -m <module>`

Do NOT run `python script.py` or `pip install` — these may resolve to the wrong
interpreter or site-packages. Always use `uv run` for execution and `uv pip install`
for package management.
