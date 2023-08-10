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
trap 'echo "$0 logs:" >&2; cat $LOG_FILE >&2' ERR


cgroup_mount_type=$(stat -f /sys/fs/cgroup/ -c %T)

if [[ $cgroup_mount_type == tmpfs ]]; then
    log "Detected cgroups v1"
    for subsys in systemd unified memory cpuset; do
        if [[ $subsys == unified && ! -d /sys/fs/cgroup/unified ]]; then
            continue
        fi
        log "Creating $subsys/custom/ and moving PID 1"
        mkdir "/sys/fs/cgroup/$subsys/custom/"
        if [[ $subsys == cpuset ]]; then
            cat "/sys/fs/cgroup/$subsys/cpuset.cpus" > "/sys/fs/cgroup/$subsys/custom/cpuset.cpus"
            cat "/sys/fs/cgroup/$subsys/cpuset.mems" > "/sys/fs/cgroup/$subsys/custom/cpuset.mems"
        fi
        echo 1 > "/sys/fs/cgroup/$subsys/custom/cgroup.procs"
    done
elif [[ $cgroup_mount_type == cgroup2fs ]]; then
    log "Detected cgroups v2"
    log "Creating /sys/fs/cgroup/custom/ and moving PID 1"
    mkdir /sys/fs/cgroup/custom/
    # PID 1 must be the only process running in the container.
    echo 1 > /sys/fs/cgroup/custom/cgroup.procs
    log "Activating memory cgroup controller"
    echo +memory > /sys/fs/cgroup/cgroup.subtree_control
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Remove the trap.
trap '' ERR

# Start systemd.
exec /sbin/init
