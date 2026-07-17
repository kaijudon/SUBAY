FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  && rm -rf /var/lib/apt/lists/*

# Issue tracker = GitHub (repo kaijudon/SUBAY). Install the GitHub CLI; the AFK
# Tester files issues with it and the Reviewer closes them. Auth is via the GH_TOKEN
# env var (see .sandcastle/.env.example); the bind-mounted git remote selects the repo.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update && apt-get install -y gh \
  && rm -rf /var/lib/apt/lists/*

# NOTE: project Python deps (Django, pytest, mypy, ...) are NOT installed here.
# sandcastle's build context is .sandcastle/, so the repo-root requirements.txt
# is not reachable at build time. They are installed at runtime instead by the
# onSandboxReady hook in main.mts, where the repo is bind-mounted at the workspace.

# Playwright's Chromium needs ~30 system shared libs (libglib, libnss, libatk, ...).
# Install them here, as root, at build time - `playwright install-deps` shells out to
# apt, which only works root+build-time. The onSandboxReady hook later downloads the
# browser BINARY itself (no root needed) into the agent's cache. Baking the deps in
# means every run launches Chromium immediately instead of re-resolving libs rootlessly.
RUN pip install --no-cache-dir playwright \
  && python -m playwright install-deps chromium \
  && rm -rf /var/lib/apt/lists/*

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# python:slim has no pre-existing non-root user, so create one named "agent"
# with the host-aligned UID/GID.
RUN groupadd -o -g $AGENT_GID agent \
  && useradd -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m agent
USER ${AGENT_UID}:${AGENT_GID}

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash

# Add Claude to PATH
ENV PATH="/home/agent/.local/bin:$PATH"

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
WORKDIR /home/agent/workspace

ENTRYPOINT ["sleep", "infinity"]
