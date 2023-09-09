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

function is_private_cgroupns() {
    # If in a private cgroup namespace then all cgroup paths will be "/".
    for line in $(cat /proc/1/cgroup); do
        cgroup_path=$(echo "$line" | cut -d ':' -f 3)
        if [[ $cgroup_path != / ]]; then
            echo 0
            return
        fi
    done
    echo 1
}

function get_cgroup_dir() {
    local subsys=$1
    grep -E "[0-9]+:$subsys:/" /proc/1/cgroup | cut -d ':' -f 3
}


if [[ $(is_private_cgroupns) == 0 ]]; then
    log "Detected host cgroupns"
else
    log "Detected private cgroupns"
    log_stderr "NOT SUPPORTED: Nothing to do in private cgroupns"
    exit 1
fi

log "Unmounting /sys/fs/cgroup for systemd to set up after cgroup ns creation"
umount -R /sys/fs/cgroup

log "Starting systemd in new cgroup namespace"
exec unshare -C /sbin/init
