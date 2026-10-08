# Run Contract Setup

How to make `/ship` step 2c able to start Sophia and sign in to it, on a box
where nobody has done it before.

The three gates in `.claude/gates.sh` are portable — they run offline against a
checkout. The **run contract** is not: it needs a TU Wien session, and a session
needs one interactive login per box. This file is the per-box part, so bringing
up prometheus is a checklist rather than a rediscovery.

Nothing here runs on Stop. The run contract is read only by `/ship` step 2c.

## Why this is box-local at all

`create_app` (`src/sophia/infra/di.py:64`) loads a stored TUWEL session and
raises `AuthError` before it builds anything, so the API will not start until
somebody has logged in on that machine. After the first login, `ensure_session`
(`src/sophia/services/job_runner.py`) re-authenticates from the keyring via
`login_both` with **no MFA code** and re-saves both the TUWEL and the TISS
session — so only the first login is interactive, and the same credential pair
serves both services.

That is why `SESSION_CMD` points at a project mint script that calls
`ensure_session` rather than at a faked identity. A fake session lands in an
empty workspace: `course_materials`, `lecture_modules` and `topic_mappings` stay
empty until a TUWEL sync has run, so it cannot exercise the study surface at all.
The cost is that the proof walk is box-bound — it works where somebody has logged
in once, and cannot work in CI or on a fresh clone. That trade is recorded in
`.claude/gates.sh` beside `SESSION_CMD`.

## Per-box checklist

### 1. Make the config directory writable

    ls -ld ~/.config/sophia

It shipped root-owned on hephaestus, which silently breaks `save_session()` —
a refreshed session cannot be persisted, so every run re-authenticates until the
credentials themselves expire.

    sudo chown -R "$USER:$USER" ~/.config/sophia

### 2. Install a keyring backend, and pin it

A headless box has no secret service, so `keyring` resolves to
`keyring.backends.fail.Keyring` and every `get_password` raises `NoKeyringError`.
Check first:

    uv run python -c "import keyring; print(keyring.get_keyring())"

`keyrings.alt` and `pycryptodome` are in the `dev` dependency group for this.
**Installing `keyrings.alt` alone is not enough and is actively worse:**
`keyrings.alt.file.PlaintextKeyring` wins on priority and writes the TU Wien
password to disk in cleartext. Pin the encrypted backend explicitly:

    PYTHON_KEYRING_BACKEND=keyrings.alt.file.EncryptedKeyring

`EncryptedKeyring` needs `pycryptodome` — without it, it raises
`RuntimeError: pycryptodome/x required` from its `priority` property, which
reads as the backend simply not existing.

For the deployed container this is unsolved — see #111. The image installs no
backend at all, so its scheduled re-auth cannot work.

### 3. Persist the environment variables

    export PYTHON_KEYRING_BACKEND=keyrings.alt.file.EncryptedKeyring
    export SOPHIA_KEYRING_PASSWORD='<master password for the encrypted store>'
    export SOPHIA_TUWEL_USERNAME='<matriculation number>'

These are needed on **every** unattended run, not just the login. Put them in
`~/.config/sophia/env` at mode 600, the same way the glab token lives at mode 600
in `~/.config/glab-cli/config.yml` on hephaestus.

`scripts/mint_session.py` **reads that file itself** (`SOPHIA_ENV_FILE`
overrides), so nothing has to source it and `SOPHIA_KEYRING_PASSWORD` never
enters any other process's environment. `/ship` runs `SESSION_CMD` in an
environment that has sourced no profile at all, which is why this is read rather
than inherited. Anything already set in the environment wins, so `gates.sh` and
an explicit override still do. For `sophia auth login` and other CLI work you do
still source it by hand.

**`export`, and single quotes, both matter.** Without `export`, sourcing sets a
shell variable that never reaches `uv run python scripts/mint_session.py`, which
runs in a fresh shell — `SESSION_CMD` would then mint for the wrong user or fail
to find one. Without quotes, a password containing `&`, `$`, a space or a
backtick is parsed as shell: a `&` backgrounds the assignment at that point, so
the variable silently takes only the fragment before it and the remainder is
executed as a command — printing part of the password to the terminal. That
happened here. If it happens, treat the password as disclosed and rotate it:
delete `~/.local/share/python_keyring/crypted_pass.cfg` and log in again.

Not in a repo `.env`: `.env` is on `verify-run-contract.sh`'s ambiguous-pattern
list and is a refusal on a `SESSION_CMD` line.

`SOPHIA_KEYRING_PASSWORD` is read by `_keyring_env_password()`
(`src/sophia/adapters/auth.py:141`), which swaps out `getpass.getpass` so the
encrypted store can be unlocked without a prompt. Anything that can read the
variable can decrypt the store; that is the accepted posture on a single-user
box, and it is strictly better than plaintext.

### 4. Log in once, interactively

    cd ~/projects/sophia && \
    PYTHON_KEYRING_BACKEND=keyrings.alt.file.EncryptedKeyring \
    SOPHIA_KEYRING_PASSWORD='…' \
    uv run sophia auth login --save-credentials

**This needs a real TTY.** `SOPHIA_TUWEL_USERNAME` and `SOPHIA_TUWEL_MFA_CODE`
are read from the environment, but the password always goes through
`getpass.getpass`, so running it from a non-interactive shell fails with
`EOF when reading a line` after burning an MFA code.

`--save-credentials` is what makes every later run unattended. Without it the
session is saved but there is nothing to refresh from.

The master password is fixed on the encrypted store's **first** use. If it was
initialised with the wrong one, delete `~/.local/share/python_keyring/crypted_pass.cfg`
and log in again.

### 5. Verify

    ls ~/.config/sophia/            # a TUWEL and a TISS session
    uv run sophia auth status       # "Session is active."
    ~/.claude/skills/project-setup/verify-run-contract.sh .

## Traps that cost time

- **A `READY_URL` that already answers is refused, not adopted.** `gate-lib.sh`
  cannot tell whose server it is, so a stray dev server would otherwise be
  reviewed as the product. Pick a port nothing else holds.
- **On hephaestus, do not `docker compose up` from this repo.** Ports 80 and 443
  belong to the homelab Caddy that fronts `gitlab.hephaestus`, and 5432 to the
  long-running `sophia-postgres-1`. `docker compose down` here stops that
  Postgres. Use loopback high ports.
- **Never `SOPHIA_E2E_AUTH=1` plus the `sophia-e2e-auth` cookie** to demonstrate
  a flow. It skips the server's own session record, and `tests/e2e/shell-auth.ts`
  pairs it with a hardcoded numeric `sophia-learning-path-id` — the seeded value
  that hid #106, because a real login got the non-numeric sentinel
  `"default-learning-path"` and every consumer coerces it with `Number()`.
- **Comments in `gates.sh` are blanked before the credential scan**, not dropped,
  so documenting the refusal by naming `keyring` or `~/.netrc` is safe. The scan
  is text-only and, by its own admission, a `SESSION_CMD` that shells out to a
  repo script reading credentials passes it — a human reading the script is the
  real check.
