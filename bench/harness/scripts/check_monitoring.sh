#!/bin/sh
# B2 monitoring check. Run from the repo root on the machine under test:
#
#   PYTHON=.venv/bin/python sh bench/harness/scripts/check_monitoring.sh
#
# Prints what the sandbox and monitor depend on (strace, user/network
# namespaces, ptrace restrictions, Docker), then runs the B test suite with
# every isolation mode the machine supports. The report is written to
# runs/checks/monitoring-<host>-<timestamp>.txt and also printed.
# Offline: the tests contact only a local test proxy and the unroutable
# address 192.0.2.1 (expected to fail).
set -u

PYTHON=${PYTHON:-python3}
HOST=$(hostname -s 2>/dev/null || hostname)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p runs/checks
REPORT="runs/checks/monitoring-$HOST-$STAMP.txt"

{
echo "== ConsentDriftBench B2 monitoring check"
echo "host: $HOST   date: $STAMP   slurm job: ${SLURM_JOB_ID:-none} partition: ${SLURM_JOB_PARTITION:-none}"
echo "git: $(git rev-parse --short HEAD 2>/dev/null) $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
uname -a
[ -r /etc/os-release ] && . /etc/os-release && echo "os: $PRETTY_NAME"
echo "python: $($PYTHON --version 2>&1) ($PYTHON)"
$PYTHON -c "import yaml, pytest, openpyxl; print('python deps: ok')" 2>&1

echo
echo "== strace"
if command -v strace >/dev/null 2>&1; then
    strace -V 2>&1 | head -1
    strace -f -qq -o /dev/null true && echo "strace -f true: ok" || echo "strace -f true: FAILED"
else
    echo "strace: NOT INSTALLED"
fi
for f in /proc/sys/kernel/yama/ptrace_scope /proc/sys/kernel/unprivileged_userns_clone \
         /proc/sys/user/max_user_namespaces /proc/sys/kernel/apparmor_restrict_unprivileged_userns; do
    [ -r "$f" ] && echo "$f = $(cat "$f")"
done

echo
echo "== unshare -rn (netns mode)"
if command -v unshare >/dev/null 2>&1; then
    unshare -rn true && echo "unshare -rn true: ok" || echo "unshare -rn true: FAILED"
    unshare -rn "$PYTHON" -I bench/harness/_sandbox_exec.py --lo-up -- true \
        && echo "unshare -rn + loopback up: ok" || echo "unshare -rn + loopback up: FAILED"
    if command -v strace >/dev/null 2>&1; then
        unshare -rn strace -f -qq -o /dev/null true && echo "strace inside netns: ok" \
            || echo "strace inside netns: FAILED"
    fi
else
    echo "unshare: NOT INSTALLED"
fi

echo
echo "== docker"
if command -v docker >/dev/null 2>&1; then
    docker info --format 'server {{.ServerVersion}}' 2>&1 | head -1
    docker image inspect consentdrift-sandbox:latest >/dev/null 2>&1 \
        && echo "image consentdrift-sandbox:latest: present" \
        || echo "image consentdrift-sandbox:latest: missing (docker build -t consentdrift-sandbox:latest bench/harness/docker)"
else
    echo "docker: not installed"
fi

echo
echo "== isolation chosen by auto"
$PYTHON -c "from bench.harness.sandbox import detect_isolation; print(detect_isolation())" 2>&1

echo
echo "== pytest bench/tests/b"
$PYTHON -m pytest bench/tests/b -v -rs 2>&1
echo "pytest exit: $?"
} 2>&1 | tee "$REPORT"

echo
echo "report: $REPORT"
