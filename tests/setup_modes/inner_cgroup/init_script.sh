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
    # Note that this approach relies on the pseudo cgroup namespace that gets
    # set up with bind mounts on cgroupv1 under cgroupns=host, where we assume
    # /sys/fs/cgroup/<subsys>/ is the container's root cgroup path.
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
    # Make sure to handle cgroupns=host, where no bind mount is used to act as
    # a pseudo-private cgroup namespace under cgroups v2.
    ctr_cgroup_dir=$(grep "::/" /proc/1/cgroup | cut -d ':' -f 3)
    controllers=( $(cat "/sys/fs/cgroup$ctr_cgroup_dir/cgroup.controllers") )
    log "Creating /sys/fs/cgroup$ctr_cgroup_dir/custom/ and moving PID 1"
    mkdir "/sys/fs/cgroup$ctr_cgroup_dir/custom/"
    # PID 1 must be the only process running in the container.
    echo 1 > "/sys/fs/cgroup$ctr_cgroup_dir/custom/cgroup.procs"
    log "Activating controllers: ${controllers[*]}"
    echo "${controllers[*]/#/+}" > "/sys/fs/cgroup$ctr_cgroup_dir/cgroup.subtree_control"
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Remove the trap.
trap '' ERR

# Start systemd.
exec /sbin/init
