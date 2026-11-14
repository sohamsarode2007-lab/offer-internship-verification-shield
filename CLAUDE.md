# CLAUDE.md

All project rules, environment notes and workflow are in AGENTS.md — follow them exactly.

@AGENTS.md

Additional notes for Claude Code:
- Windows Device Guard blocks .exe launchers in the venv; always run tools as `.\.venv\Scripts\python.exe -m <tool>`.
- Work on the `clean-main` branch. Push with a plain `git push`; never push other branches or use `--all`.
- After every task: run the full test suite and the eval (`eval/run_eval.py`), push, and confirm the GitHub
  Actions run passed (`gh run watch`).
