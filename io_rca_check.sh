#!/bin/bash
# io_rca_collect_safe.sh
# Collecte RCA stockage avec protections anti-blocage

TS=$(date +%Y%m%d_%H%M%S)
OUT="/tmp/io_rca_${HOSTNAME}_${TS}.log"
TIMEOUT_CMD="${TIMEOUT_CMD:-8}"

run_cmd() {
  local title="$1"
  shift
  echo
  echo "===== ${title} ====="
  timeout "${TIMEOUT_CMD}" "$@" || echo "[WARN] Command timed out after ${TIMEOUT_CMD}s: $*"
}

{
  echo "===== IO RCA SAFE COLLECT START ====="
  echo "Host      : $(hostname -f 2>/dev/null || hostname)"
  echo "Date      : $(date)"
  echo "Uptime    : $(uptime)"
  echo "Timeout   : ${TIMEOUT_CMD}s"
  echo

  run_cmd "OS / KERNEL" uname -a

  echo
  echo "===== LOAD / CPU ====="
  timeout "${TIMEOUT_CMD}" top -b -n 1 | head -20 || echo "[WARN] top timed out"

  run_cmd "VMSTAT" vmstat 1 5
  run_cmd "IOSTAT" iostat -xz 1 5

  echo
  echo "===== BLOCKED TASKS (D STATE) ====="
  timeout "${TIMEOUT_CMD}" ps -eo pid,ppid,user,state,wchan:32,cmd | awk '$4=="D" {print}' \
    || echo "[WARN] ps/awk timed out"

  echo
  echo "===== TOP CPU ====="
  timeout "${TIMEOUT_CMD}" ps -eo pid,ppid,user,%cpu,%mem,state,cmd --sort=-%cpu | head -20 \
    || echo "[WARN] top cpu query timed out"

  echo
  echo "===== TOP MEM ====="
  timeout "${TIMEOUT_CMD}" ps -eo pid,ppid,user,%cpu,%mem,state,cmd --sort=-%mem | head -20 \
    || echo "[WARN] top mem query timed out"

  echo
  echo "===== RPM / DNF / YUM / PACKAGE LOCK ====="
  timeout "${TIMEOUT_CMD}" sh -c "ps -ef | egrep 'dnf|yum|rpm' | grep -v grep" \
    || echo "[WARN] rpm/dnf process query timed out"

  timeout 5 sh -c "lsof 2>/dev/null | egrep 'rpm|Packages|__db|yum|dnf'" \
    || echo "[WARN] lsof timed out (possible kernel I/O blocking)"

  echo
  echo "===== MOUNT / DISK USAGE ====="
  run_cmd "FINDMNT" findmnt
  run_cmd "DF -HT" df -hT
  run_cmd "DF -I" df -i

  echo
  echo "===== MULTIPATH ====="
  if command -v multipath >/dev/null 2>&1; then
    timeout "${TIMEOUT_CMD}" multipath -ll || echo "[WARN] multipath -ll timed out"
  else
    echo "multipath not installed"
  fi

  echo
  echo "===== DMESG STORAGE ====="
  timeout "${TIMEOUT_CMD}" sh -c "dmesg -T | egrep -i 'scsi|blk|I/O|tim(e|ed) out|reset|reject|abort|error|pvscsi|buffer io|reservation' | tail -200" \
    || echo "[WARN] dmesg storage query timed out"

  echo
  echo "===== JOURNAL STORAGE ====="
  timeout "${TIMEOUT_CMD}" sh -c "journalctl -k -n 200 --no-pager | egrep -i 'scsi|blk|I/O|tim(e|ed) out|reset|reject|abort|error|pvscsi|buffer io|reservation'" \
    || echo "[WARN] journalctl storage query timed out"

  echo
  echo "===== PSI IO ====="
  if [ -f /proc/pressure/io ]; then
    cat /proc/pressure/io
  else
    echo "/proc/pressure/io not available"
  fi

  echo
  echo "===== OPTIONAL: BLOCKED STACKS (use carefully) ====="
  echo "To dump blocked tasks manually:"
  echo "  echo w > /proc/sysrq-trigger"
  echo "Then check:"
  echo "  dmesg | tail -100"

  echo
  echo "===== QUICK SUMMARY ====="
  echo "- High load + high CPU idle => system waiting, likely I/O bound"
  echo "- Processes in D state => blocked on disk / storage path"
  echo "- High %util on dm-X/sdX => disk saturation / queue saturation"
  echo "- lsof timeout => even diagnostics blocked by kernel I/O waits"
  echo
  echo "Report saved to: $OUT"
  echo "===== IO RCA SAFE COLLECT END ====="
} | tee "$OUT"