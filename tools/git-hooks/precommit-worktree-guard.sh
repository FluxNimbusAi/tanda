#!/bin/sh
# pre-commit guard: reject staging anything under .worktrees/ (6955f050 class).
# Install: cp tools/git-hooks/precommit-worktree-guard.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
if git diff --cached --name-only | grep -q '^\.worktrees/\|/[.]worktrees/'; then
  echo "BLOCKED (pre-commit guard): staged paths under .worktrees/ — commit from the main checkout only." >&2
  echo "If intentional (auditable): git commit --no-verify, disclose in the commit body." >&2
  exit 1
fi
exit 0
