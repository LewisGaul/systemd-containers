#!/bin/bash

set -e

LOG_FILE=/var/log/init_script.log

function log() {
    local msg=$1
    echo "$(date +"%Y-%m-%d %H:%M:%S,%03N"): $msg" >> "$LOG_FILE"
}

function log_stderr() {
    local msg=$1
    echo "$msg" >&2
    log "$msg"
}

# Output logs if this script fails.
trap 'echo "$0 logs:" >&2; cat $LOG_FILE >&2' ERR EXIT


cgroup_mount_type=$(stat -f /sys/fs/cgroup/ -c %T)

if [[ $cgroup_mount_type == tmpfs ]]; then
    log "Detected cgroups v1"
    log "Unmounting all /sys/fs/cgroup mounts (allow systemd to recreate)"
    umount -R /sys/fs/cgroup
elif [[ $cgroup_mount_type == cgroup2fs ]]; then
    log "Detected cgroups v2"
    log "Unmounting /sys/fs/cgroup mount (allow systemd to recreate)"
    umount /sys/fs/cgroup
    export SYSTEMD_PROC_CMDLINE="systemd.unified_cgroup_hierarchy=1"
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Start systemd.
exec /sbin/init
