# Sandbox image for DockerSandbox (bench/harness/sandbox.py).
#
#   docker build -t consentdrift-sandbox:latest bench/harness/docker
#
# Contains the tools the 55 tasks' delegations execute (git, npm/node, python3,
# pytest, ruff), what the repos' setup.sh scripts need (openpyxl, GNU tar,
# gzip), and strace for B2 monitoring. The container runs with
# --network none; the only way out is the proxy bridge.
# Versions: Debian bookworm packages; Python tools pinned below (B, unreviewed).
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm strace curl tar gzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pyyaml==6.0.2 openpyxl==3.1.5 pytest==8.3.4 ruff==0.8.4

CMD ["sleep", "infinity"]
