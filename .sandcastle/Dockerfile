FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  && rm -rf /var/lib/apt/lists/*

# TODO: install your issue tracker's CLI here. See .sandcastle/SETUP_ISSUE_TRACKER.md

# Install project Python dependencies (Django, pytest, mypy, ...) so the agent
# can run manage.py, the test suite, and typechecks inside the sandbox.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

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
