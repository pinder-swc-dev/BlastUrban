# ADR 0001: Require systemd linger and reuse SSH connections

- Status: Accepted
- Date: 2026-10-02
- Scope: trusted localhost SSH administration adapter only

## Context

`systemctl --user show-environment` can succeed while `loginctl show-user USER
-p Linger --value` is `no`. In that state a transient user unit may depend on a
remaining login session and a long job can stop after logout. Earlier smoke
tests had another session open and did not prove persistence.

The localhost adapter also created a fresh TCP/SSH authentication session for
every status, log, job-list and readiness call. A six-call `remote true`
benchmark on the configured server measured 1.927821 s total for independent
connections versus 0.139782 s total after establishing a ControlMaster.

## Decision

1. `check` reports `linger` as `yes`, `no`, or `unknown`.
2. Submission is refused unless `linger=yes` or the operator sends the literal
   boolean `accept_no_linger: true`. The generated runner checks the same rule
   again and records `linger` and `accept_no_linger` in job status.
3. The application never runs `sudo loginctl enable-linger`; it displays the
   command for an administrator.
4. SSH and rsync share `ControlMaster=auto`, `ControlPersist=60` and a hashed,
   short `ControlPath` under the workspace temp directory. The directory mode
   is 0700 and the application asks OpenSSH to close tracked masters on exit.
5. Set `BLASTURBAN_SSH_MULTIPLEX=0` to return to one connection per call.

## Alternatives considered

- Treat a live user manager as sufficient: rejected because it does not prove
  that the manager survives logout.
- Enable linger automatically: rejected because it changes host policy and
  requires administrator authority.
- Maintain one long custom SSH process: rejected as unnecessary state and
  protocol complexity when OpenSSH already supplies multiplexing.
- Use a global `/tmp` socket: rejected because of path ownership and collision
  concerns.

## Consequences

- A server with `Linger=no` now requires an explicit, visible risk acceptance;
  existing unattended submissions that omitted it are rejected.
- Repeated control-plane calls avoid repeated handshakes. This is an
  orchestration timing only and says nothing about CFD runtime.
- Stale OpenSSH masters may live for at most 60 seconds after an abnormal local
  process exit; they do not run Docker or CFD by themselves.
- The production HTTPS/queue architecture remains unchanged; this ADR does not
  turn the localhost adapter into a public API.

## Affected systems and verification

- `tools/blast_case_ui/blast_case_web.py`
- `tools/blast_case_ui/assets/server-docker-job.sh`
- `tools/blast_case_ui/web/index.html`
- Python unit tests with fake `loginctl`
- Read-only API check against the configured server (`Linger=no`)
- `tools/bench/benchmark_ssh.py`
