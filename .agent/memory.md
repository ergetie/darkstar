## **Current Phase**

* REV // PUB01 — Public Beta Release (v2.4.1-beta) [DONE]

## **Architectural Decisions**

* Monorepo structure enforced.  
* Frontend talks to Backend via /api proxy (configured in Vite).  
* ML pipelines reside in root/ml.
* **HA Ingress SPA Support**: Backend injects `<base href>` dynamically from `X-Ingress-Path` header. Frontend uses `document.baseURI` for socket.io path calculation.

## **Recurring Issues**

* QEMU ARM builds on GitHub Actions are very slow (~2h). Consider native ARM runner (Oracle Cloud Free Tier) for future optimization.

## **GitHub CLI (gh) Commands**

Installed `github-cli` via `pacman -S github-cli`. Useful commands:

| Command | Purpose |
|---------|---------|
| `gh auth login` | Authenticate with GitHub |
| `gh run list` | List recent workflow runs |
| `gh run view <id>` | View workflow run details |
| `gh run watch <id>` | Live-tail a running workflow |
| `gh workflow run <name>.yml` | Manually trigger a workflow |
| `gh release create v1.0.0` | Create a GitHub release |
| `gh api /user/packages/...` | Query GHCR packages (needs `read:packages` scope) |