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


function fixup_cgroup_v1_mount() {
    local mnt_path=$1
    local mnt_type=$2
    local opts
    local exit_code=0

    # Ensure that cgroup mounts are read-write, and have mount root same as the
    # cgroup filesystem root to avoid broken /proc/$PID/cgroup mappings.
    # We could check these conditions, but it's simpler just to recreate the
    # mounts unconditionally.

    # Unmount in case read-only or bind mount, so we can mount as read-write.
    opts=$(findmnt "$mnt_path" -o OPTIONS | tail -n 1 | sed 's/^ro/rw/')
    log "Remounting $mnt_path with opts $opts"
    umount -R "$mnt_path" || exit_code=$?
    # It's possible for there to be two mounts at the same mount point, and
    # this requires two 'umount' calls to remove... This has been seen on
    # CentOS 8 with podman v3.3.1 when running in systemd mode.
    if findmnt "$mnt_path" > /dev/null; then
        log "Still a mount at $mnt_path after 'umount -R', running 'umount' again..."
        umount "$mnt_path" || exit_code=$?
    fi
    if [[ $exit_code != 0 ]]; then
        log_stderr "Unable to unmount $mnt_path: exit code $exit_code"
        exit 1
    fi
    mount -t "$mnt_type" cgroup "$mnt_path" -o "$opts" || exit_code=$?
    if [[ $exit_code != 0 ]]; then
        log_stderr "Unable to mount $mnt_path with opts '$opts': exit code $exit_code"
        exit 1
    fi
}


cgroup_mount_type=$(stat -f /sys/fs/cgroup/ -c %T)

if [[ $cgroup_mount_type == tmpfs ]]; then
    log "Detected cgroups v1"
    log "Remounting all /sys/fs/cgroup mounts as read-write"
    for subsys_path in /sys/fs/cgroup/*; do
        if findmnt -t cgroup "$subsys_path" > /dev/null; then
            fixup_cgroup_v1_mount "$subsys_path" cgroup
        elif findmnt -t cgroup2 "$subsys_path" > /dev/null; then
            fixup_cgroup_v1_mount "$subsys_path" cgroup2
        fi
    done
elif [[ $cgroup_mount_type == cgroup2fs ]]; then
    log "Detected cgroups v2"
    log "Remounting /sys/fs/cgroup mount as read-write"
    mount /sys/fs/cgroup -o remount,rw
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Start systemd.
exec /sbin/init
