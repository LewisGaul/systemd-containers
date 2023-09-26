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

function get_cgroup_dir() {
    local subsys=$1
    grep -E "[0-9]+:$subsys:/" /proc/1/cgroup | cut -d ':' -f 3
}


CGROUP_VERSION=$(get_cgroup_version)
# Export this so that the script knows the version after the re-exec.
export CGROUP_VERSION

if [[ $REEXEC != 1 ]]; then
    log "In first exec of init script"
    if [[ $(is_private_cgroupns) == 1 ]]; then
        log_stderr "NOT SUPPORTED: Nothing to do with cgroupns=private"
        exit 1
    fi

    log "Unmounting /sys/fs/cgroup to be recreated after cgroup ns creation"
    umount -R /sys/fs/cgroup

    log "Re-executing in new cgroup namespace"
    REEXEC=1 exec unshare -C "$0"
else
    log "In re-exec of init script"
    if [[ $(is_private_cgroupns) == 0 ]]; then
        log_stderr "ERROR: Expected private cgroupns after re-exec"
        exit 1
    fi
    # Recreate cgroup mount so that systemd knows which cgroup version to use.
    # Can alternatively use:
    #  SYSTEMD_PROC_CMDLINE="systemd.unified_cgroup_hierarchy=1"
    if [[ $CGROUP_VERSION == 1 ]]; then
        log "Recreating cgroup v1 tmpfs mount"
        mount -t tmpfs tmpfs /sys/fs/cgroup
    elif [[ $CGROUP_VERSION == 2 ]]; then
        log "Recreating cgroup2 mount"
        mount -t cgroup2 cgroup2 /sys/fs/cgroup
    else
        log_stderr "Unrecognised cgroup version: '$CGROUP_VERSION'"
        exit 1
    fi
    log "Starting systemd"
    exec /sbin/init
fi
