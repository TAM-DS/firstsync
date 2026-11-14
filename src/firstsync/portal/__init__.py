"""The admin portal: the human-facing surface of FirstSync.

The portal is where a person does the one thing the model cannot — authorize. It shows
Claude's proposed mappings, the dry-run preview of their own data, and the approve and
migrate controls. It never calls the model: every page reads state the engines wrote, and
every action (approve, migrate, sync) is a server-side call behind the same gate the CLI
uses. For a self-contained demo it loads the proposals Claude produced in the evaluation
runs, so the whole flow works with no API key.
"""
