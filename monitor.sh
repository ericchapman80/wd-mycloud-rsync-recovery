#!/bin/bash
# Monitor script for restsdk copy operations
# Run alongside the main script to track system health and catch issues early

LOGFILE="${1:-monitor.log}"
INTERVAL="${2:-30}"  # seconds between checks
NFS_MOUNT="${3:-/mnt/nfs-media}"
TRACKING_DB="${4:-}"  # Optional: path to tracking database with copied_files table

echo "=== Monitor Started: $(date) ===" | tee -a "$LOGFILE"
echo "Logging to: $LOGFILE (interval: ${INTERVAL}s)" | tee -a "$LOGFILE"
echo "NFS Mount: $NFS_MOUNT" | tee -a "$LOGFILE"
[ -n "$TRACKING_DB" ] && echo "Tracking DB: $TRACKING_DB" | tee -a "$LOGFILE"
echo ""

check_count=0

while true; do
    check_count=$((check_count + 1))
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Memory usage (works on both Linux and macOS)
    if [ -f /proc/meminfo ]; then
        # Linux
        mem_info=$(free -m 2>/dev/null | awk 'NR==2{printf "%.1f%% (%dMB/%dMB)", $3*100/$2, $3, $2}')
    else
        # macOS fallback
        mem_info=$(vm_stat 2>/dev/null | awk '/Pages (free|active|inactive|speculative)/ {sum+=$NF} END {printf "%.0f pages used", sum}' || echo "N/A")
    fi
    
    # Load average (works on both Linux and macOS)
    if [ -f /proc/loadavg ]; then
        load=$(cat /proc/loadavg | awk '{print $1, $2, $3}')
    else
        load=$(sysctl -n vm.loadavg 2>/dev/null | tr -d '{}' || uptime | awk -F'load average:' '{print $2}' | xargs)
    fi
    
    # Open file descriptors for our specific script processes
    python_fd=0
    
    # Get PIDs for our scripts - use multiple methods to find them
    script_pids=""
    # Method 1: pgrep with full match
    script_pids=$(pgrep -f "restsdk_public.py|create_symlink_farm.py" 2>/dev/null)
    # Method 2: If empty, try ps + grep (works better with sudo)
    if [ -z "$script_pids" ]; then
        script_pids=$(ps aux 2>/dev/null | grep -E "python.*restsdk_public|python.*create_symlink_farm" | grep -v grep | awk '{print $2}')
    fi
    
    if [ -n "$script_pids" ]; then
        for pid in $script_pids; do
            if [ -d "/proc/$pid/fd" ]; then
                # Use ls -1 and timeout to avoid hanging on busy system
                count=$(timeout 2 ls -1 /proc/$pid/fd 2>/dev/null | wc -l)
                python_fd=$((python_fd + count))
            fi
        done
    fi
    
    # Show N/A if nothing found, otherwise show count
    [ "$python_fd" = "0" ] && python_fd="N/A"
    
    # NFS mount status
    nfs_status="OK"
    if [ -n "$NFS_MOUNT" ] && [ "$NFS_MOUNT" != "none" ]; then
        if ! mountpoint -q "$NFS_MOUNT" 2>/dev/null && ! mount | grep -q "$NFS_MOUNT"; then
            nfs_status="UNMOUNTED!"
        elif ! timeout 5 ls "$NFS_MOUNT" >/dev/null 2>&1; then
            nfs_status="STALLED!"
        fi
    else
        nfs_status="N/A"
    fi
    
    # Copied files count - try multiple sources
    copied_count="N/A"
    # Method 1: Check tracking database if provided
    if [ -n "$TRACKING_DB" ] && [ -f "$TRACKING_DB" ]; then
        copied_count=$(timeout 5 sqlite3 "$TRACKING_DB" "SELECT COUNT(*) FROM copied_files" 2>/dev/null || echo "DB_ERR")
    fi
    # Method 2: Parse from run.out if tracking DB not available
    if [ "$copied_count" = "N/A" ] || [ "$copied_count" = "DB_ERR" ]; then
        if [ -f "run.out" ]; then
            # Count [COPIED] lines in run.out
            copied_count=$(grep -c "\[COPIED\]" run.out 2>/dev/null || echo "0")
            copied_count="${copied_count} (from log)"
        fi
    fi
    
    # Disk I/O wait (Linux only, graceful fallback)
    iowait="N/A"
    if command -v iostat &>/dev/null; then
        # iostat output varies; try to get iowait %
        iowait=$(iostat -c 1 2 2>/dev/null | awk '/^ *(avg-cpu|[0-9])/ {iow=$4} END {if(iow!="") print iow; else print "N/A"}')
    elif [ -f /proc/stat ]; then
        # Fallback: calculate from /proc/stat (crude but works)
        read cpu user nice system idle iowait_raw irq softirq < /proc/stat
        total=$((user + nice + system + idle + iowait_raw + irq + softirq))
        if [ "$total" -gt 0 ]; then
            iowait=$(awk "BEGIN {printf \"%.1f\", $iowait_raw * 100 / $total}")
        fi
    fi
    
    # Process status - check for both scripts
    script_status="STOPPED"
    if pgrep -f "restsdk_public.py" >/dev/null 2>&1; then
        script_status="restsdk"
    elif pgrep -f "create_symlink_farm.py" >/dev/null 2>&1; then
        script_status="symlink"
    elif pgrep -f "rsync" >/dev/null 2>&1; then
        script_status="rsync"
    fi
    
    # Log entry
    log_entry="[$timestamp] #$check_count | Script: $script_status | NFS: $nfs_status | Mem: $mem_info | Load: $load | FDs: $python_fd | IOWait: ${iowait}% | Copied: $copied_count"
    
    echo "$log_entry" | tee -a "$LOGFILE"
    
    # Alerts
    if [ "$nfs_status" = "STALLED!" ]; then
        echo "  ⚠️  ALERT: NFS appears stalled! Check mount." | tee -a "$LOGFILE"
    fi
    
    if [ "$script_status" = "STOPPED" ]; then
        echo "  ⚠️  ALERT: No copy process running!" | tee -a "$LOGFILE"
    fi
    
    # Check for high memory usage (>90%)
    mem_pct=$(free | awk 'NR==2{printf "%.0f", $3*100/$2}')
    if [ "$mem_pct" -gt 90 ] 2>/dev/null; then
        echo "  ⚠️  ALERT: Memory usage critical: ${mem_pct}%!" | tee -a "$LOGFILE"
    fi
    
    sleep "$INTERVAL"
done
