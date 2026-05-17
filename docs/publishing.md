# Publishing to GitHub

This repo is safe to publish only after generated runtime state is excluded. The `.gitignore` already excludes:

- logs,
- slot state,
- generated datasets,
- embedding caches,
- local `.env` files,
- Python caches.

## Recommended: Private Repo

Use a private repo if your local memory table, docs, screenshots, or examples include device names, file paths, troubleshooting output, or personal workflow details.

## With GitHub CLI

```powershell
winget install --id GitHub.cli
gh auth login
gh repo create networkintegrationcoach-memory-rag --private --source . --remote origin --push
```

For public:

```powershell
gh repo create networkintegrationcoach-memory-rag --public --source . --remote origin --push
```

## With Git Only

Create an empty repo on GitHub, then:

```powershell
git remote add origin https://github.com/<your-user>/networkintegrationcoach-memory-rag.git
git branch -M main
git push -u origin main
```

## Pre-Publish Check

```powershell
git status --short
rg -n "GITHUB_TOKEN|GH_TOKEN|api_key|password|secret|C:\\Users\\[^\\]+"
```
