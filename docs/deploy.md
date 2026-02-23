# Secure Self-Deploy Plan: GitHub Actions + Remote Server (Docker + Nginx)

## Summary

  You will run two secure CI/CD pipelines:

1. This repo: build and deploy frontend web artifact.
2. Separate backend repo: build and deploy API container.

Both deploy to hardened Linux servers (staging, production) using:

- GitHub Actions + environment protection rules
  - SSH deploy key with forced command (no interactive shell)
  - Blue/green-style container switch with health checks
  - Nginx reverse proxy with strict TLS/security headers
  - Minimal privileges and strong secret handling

## Public Interfaces / Contract Changes

  No app API contract changes in this repo are required now.
  New operational interfaces to introduce:

  1. GitHub Actions workflow triggers:

  - push to main => deploy staging
  - manual workflow_dispatch + approval => deploy production

  2. Server deploy entrypoint:

  - forced command executes /usr/local/bin/deploy-frontend.sh (frontend repo)
  - forced command executes /usr/local/bin/deploy-backend.sh (backend repo)

  3. Health endpoints required:

  - frontend: GET /healthz (Nginx static OK endpoint)
  - backend: GET /api/healthz (application health)

## Implementation Plan

### 1. Server Hardening (Do first on both servers)

  1. Base OS:

  - Ubuntu 24.04 LTS minimal install
  - separate hosts for staging/prod (or separate VMs)

  2. Users and auth:

  - create non-root deployer user
  - disable root SSH login
  - disable password auth (PasswordAuthentication no)
  - require SSH key auth only

  3. Network:

  - cloud firewall: allow inbound 22 only from your admin IPs; 80/443 public
  - deny all other inbound ports

  4. OS security:

  - enable unattended security updates
  - configure ufw default deny incoming, allow 22/80/443
  - install and enable fail2ban

  5. Docker security:

  - install Docker + Compose plugin
  - rootless Docker for deployer if feasible; otherwise restrict Docker group membership
  - enable log rotation in Docker daemon

  6. Filesystem/secrets:

  - create /opt/messenger/{frontend,backend}/{releases,current,shared}
  - store runtime env files in /opt/messenger/*/shared/.env with 600 permissions
  - never store secrets in repo

### 2. SSH Forced-Command Deployment Model

  1. Generate one deploy keypair per environment per repo.
  2. In server ~deployer/.ssh/authorized_keys, pin each public key to forced command and restrictions:

  - command="/usr/local/bin/deploy-frontend.sh",no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-
  forwarding <pubkey>

  3. deploy-frontend.sh and deploy-backend.sh:

  - strict shell mode (set -euo pipefail)
  - accept only signed artifact/version input from CI
  - verify checksum
  - deploy to new release directory
  - run health checks
  - switch symlink/active container only on success
  - rollback automatically if health checks fail
  - append audit logs to /var/log/messenger-deploy.log

### 3. Frontend Deployment from This Repo

  1. GitHub Actions workflow (.github/workflows/deploy-frontend.yml):

  - permissions: minimum required (contents:read)
  - use pinned action SHAs (not floating tags)
  - build static web output
  - package tarball + checksum
  - upload artifact
  - deploy job uses environment-scoped secrets and SSH key
  - copy artifact to server and trigger forced command

  2. Nginx frontend config:

  - serve current frontend release from symlinked docroot
  - enable TLS 1.2/1.3 only
  - Strict-Transport-Security, X-Content-Type-Options, X-Frame-Options, tight CSP
  - disable directory listing
  - location = /healthz { return 200; }

  3. Blue/green-like static swap:

  - extract new build into timestamped release
  - validate files
  - atomically switch current symlink
  - reload Nginx
  - quick rollback = switch symlink back

### 4. Backend Deployment (Separate Repo)

  1. Mirror same GitHub Actions security posture:

  - pinned actions, environment protection, minimal permissions

  2. Build immutable Docker image:

  - multi-stage build
  - non-root runtime user
  - pinned base image digests
  - vulnerability scan gate (fail on critical)

  3. Server deployment:

  - pull verified image digest
  - run new container on alternate port/network
  - health check /api/healthz
  - switch Nginx upstream to healthy container
  - keep previous container for immediate rollback window

### 5. GitHub Security Controls

  1. Enable branch protection on main:

  - required PR reviews
  - required status checks
  - signed commits recommended

  2. Environments:

  - staging and production environments with separate secrets
  - required reviewers for production deploy

  3. Secrets:

  - store private SSH key as environment secret
  - add server host key fingerprint pinning in workflow (known_hosts)
  - rotate deploy keys every 90 days

  4. OIDC future improvement:

  - later replace long-lived deploy keys with short-lived cloud credentials where possible

### 6. Observability and Audit

  1. Centralize logs:

  - Nginx access/error logs
  - deploy script audit log
  - app/container logs

  2. Monitoring:

  - uptime checks for staging and production
  - alert on failed deploy, failed health check, high 5xx

  3. Security monitoring:

  - monitor SSH auth failures and fail2ban actions
  - monthly patch and image refresh cadence

## Test Cases and Scenarios

  1. Staging auto-deploy:

  - push to main, confirm build, transfer, deploy, health check success

  2. Production gated deploy:

  - manual dispatch with approval required, then successful cutover

  3. Rollback path:

  - intentionally deploy unhealthy build, verify automatic rollback and service continuity

  4. Secret leak prevention:

  - confirm no secrets in logs/artifacts/repo

  5. SSH restriction test:

  - try interactive SSH with deploy key; must fail

  6. Host key pinning:

  - simulate host key mismatch; workflow must fail safely

  7. Disaster recovery drill:

  - restore previous release from retained artifacts and switch within target RTO

## Assumptions and Defaults

  1. Server OS is Ubuntu 24.04 LTS.
  2. Domain and TLS certificates are managed on-server with Nginx (Let’s Encrypt or existing certs).
  3. This repo deploys only frontend web artifact.
  4. Backend is deployed from a separate repo but follows the same security/deploy pattern.
  5. Chosen defaults from you:

  - Docker + Nginx
  - SSH deploy key + forced command
  - Blue/green-ish release strategy
  - Staging + Production environments
