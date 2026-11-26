"""Client portal: private, per-tenant access to the analyses a party or candidate has bought.

Stdlib only. A tenant is a folder under `analysis/clients/<slug>/` (local, gitignored; override with STAVROI_CLIENTS)
whose `client.json` lists what the tenant may see (`publish`). Users log in with a password or a one-time link;
every request is checked against the user's own tenant, so one client can never reach another's files.
Run `python -X utf8 -m portal help`.
"""
