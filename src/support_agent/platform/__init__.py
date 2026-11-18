"""Local platform tooling behind `make up / down / status` (S2).

Run as `python -m support_agent.platform <command>`; see `__main__.py`.
Nothing here runs inside a service: it prepares the machine, renders the
config files that need secrets into `.run/` (git-ignored) and checks health.
"""
