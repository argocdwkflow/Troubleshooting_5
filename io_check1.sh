#!/bin/bash
# io_rca_collect.sh
# Collecte rapide des preuves de saturation stockage / I/O

TS=$(date +%Y%m%d_%H%M%S)
OUT="/tmp/io_rca_${HOSTNAME}_${TS}.log"

exec > >(tee -a "$OUT") 2>&1

echo "===== IO RCA COLLECT START ====="
echo "Host      : $(hostname -f 2>/dev/null || hostname)"
echo "Date      : $(date)"
echo "Uptime    : $(uptime)"
echo

echo "===== OS / KERNEL ====="
uname -a
echo

echo "===== LOAD / CPU ====="
top -b -n 1 | head -20
echo

echo "===== VMSTAT ====="
vmstat 1 5
echo

echo "===== IOSTAT ====="
iostat -xz 1 5
echo

echo "===== BLOCKED TASKS (D STATE) ====="
ps -eo pid,ppid,user,state,wchan:32,cmd | awk '$4=="D" {print}'
echo

echo "===== TOP CPU ====="
ps -eo pid,ppid,user,%cpu,%mem,state,cmd --sort=-%cpu | head -20
echo

echo "===== TOP MEM ====="
ps -eo pid,ppid,user,%cpu,%mem,state,cmd --sort=-%mem | head -20
echo

echo "===== RPM / DNF / YUM / PACKAGE LOCK ====="
ps -ef | egrep 'dnf|yum|rpm' | grep -v grep
echo
lsof 2>/dev/null | egrep 'rpm|Packages|__db|yum|dnf' || true
echo

echo "===== MOUNT / DISK USAGE ====="
findmnt
echo
df -hT
echo
df -i
echo

echo "===== MULTIPATH ====="
if command -v multipath >/dev/null 2>&1; then
  multipath -ll
else
  echo "multipath not installed"
fi
echo

echo "===== DMESG STORAGE ====="
dmesg -T | egrep -i 'scsi|blk|I/O|tim(e|ed) out|reset|reject|abort|error|pvscsi|buffer io|reservation' | tail -200
echo

echo "===== JOURNAL STORAGE ====="
journalctl -k -n 200 --no-pager | egrep -i 'scsi|blk|I/O|tim(e|ed) out|reset|reject|abort|error|pvscsi|buffer io|reservation' || true
echo

echo "===== PSI IO ====="
if [ -f /proc/pressure/io ]; then
  cat /proc/pressure/io
else
  echo "/proc/pressure/io not available"
fi
echo

echo "===== SANITY SUMMARY ====="
echo "- High load + high idle CPU => waiting, likely I/O bound"
echo "- Processes in D state => blocked on disk / I/O"
echo "- High %util / await in iostat => storage saturation or latency"
echo "- rpm/dnf locks help explain patch timeout"
echo

echo "Report saved to: $OUT"
echo "===== IO RCA COLLECT END ====="