"""User accounts, password hashing, and JWT/refresh-token session management.

`db.py` is the only module that touches the `app_user` / `refresh_tokens` Postgres tables
directly (see `db/schema.sql` for the DDL); `service.py` is pure password/JWT/token logic with no
SQL and no FastAPI imports. `api.py` wires both together behind the `/auth/*` endpoints.
"""
