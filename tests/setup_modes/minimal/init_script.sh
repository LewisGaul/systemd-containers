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
    log "Ensuring /sys/fs/cgroup/systemd is mounted read-write"
    if findmnt -t cgroup /sys/fs/cgroup/systemd -O ro > /dev/null; then
        # Unmount if read-only or bind mount, so we can mount as read-write.
        opts=$(findmnt /sys/fs/cgroup/systemd -o OPTIONS | tail -n 1 | sed 's/^ro/rw/')
        log "Remounting /sys/fs/cgroup/systemd with opts $opts"
        umount -R /sys/fs/cgroup/systemd
        mount -t cgroup cgroup /sys/fs/cgroup/systemd -o "$opts"
    fi
elif [[ $cgroup_mount_type == cgroup2fs ]]; then
    log_stderr "NOT SUPPORTED: This would be the same as the 'remount' approach"
    exit 1
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Start systemd.
exec /sbin/init
