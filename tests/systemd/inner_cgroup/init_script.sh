#!/bin/bash

set -e


function log() {
    local msg=$1
    echo "$(date +"%Y-%m-%d %H:%M:%S,%03N"): $msg" >> /var/log/init_script.log
}

function log_stderr() {
    local msg=$1
    echo "$msg" >&2
    log "$msg"
}


cgroup_mount_type=$(stat -f /sys/fs/cgroup/ -c %T)

if [[ $cgroup_mount_type == tmpfs ]]; then
    log "Detected cgroups v1"
    mkdir /sys/fs/cgroup/memory/custom/
    echo 1 > /sys/fs/cgroup/memory/custom/cgroup.procs
elif [[ $cgroup_mount_type == cgroup2fs ]]; then
    log "Detected cgroups v2"
    mkdir /sys/fs/cgroup/custom/
    # PID 1 must be the only process running in the container.
    echo 1 > /sys/fs/cgroup/custom/cgroup.procs
    echo +memory > /sys/fs/cgroup/cgroup.subtree_control
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Start systemd.
exec /sbin/init
