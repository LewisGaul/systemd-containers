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


function is_private_cgroupns() {
    # If in a private cgroup namespace then all cgroup paths will be "/".
    for line in $(cat /proc/1/cgroup); do
        cgroup_path=$(echo "$line" | cut -d ':' -f 3)
        if [[ $cgroup_path != / ]]; then
            log "Detected host cgroupns"
            echo 0
            return
        fi
    done
    log "Detected private cgroupns"
    echo 1
}

function get_cgroup_version() {
    if [[ $CGROUP_VERSION ]]; then
        echo "$CGROUP_VERSION"
        return
    fi
    cgroup_mount_type=$(stat -f /sys/fs/cgroup/ -c %T)
    if [[ $cgroup_mount_type == tmpfs ]]; then
        log "Detected cgroups v1"
        echo 1
    elif [[ $cgroup_mount_type == cgroup2fs ]]; then
        log "Detected cgroups v2"
        echo 2
    else
        log "ERROR: Unable to detect cgroup version from cgroup mount type $cgroup_mount_type"
        return 1
    fi
}

if [[ $(is_private_cgroupns) == 1 ]]; then
    log_stderr "NOT SUPPORTED: Nothing to do with cgroupns=private"
    exit 1
fi

CGROUP_VERSION=$(get_cgroup_version)

if [[ $CGROUP_VERSION == 1 ]]; then
    # This relies on the Docker/Podman pseudo-namespace cgroup bind mounts,
    # otherwise the cgroup mounts will have the wrong root path.
    log "Starting systemd in new cgroup namespace"
    exec unshare -C /sbin/init
else
    # Remove cgroup mount and let systemd recreate based on the created cgroup
    # namespace, otherwise the cgroup mount will have the wrong root path.
    log "Unmounting /sys/fs/cgroup"
    umount /sys/fs/cgroup

    log "Starting systemd in new cgroup namespace"
    SYSTEMD_PROC_CMDLINE="systemd.unified_cgroup_hierarchy=1" \
        exec unshare -C /sbin/init
fi
