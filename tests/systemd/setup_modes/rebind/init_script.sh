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

cgroup_mount_type=$(stat -f /sys/fs/cgroup/ -c %T)

if [[ $cgroup_mount_type == tmpfs ]]; then
    log "Detected cgroups v1"
    v1_subsys_dirs=(
        "memory:memory"
        "cpuset:cpuset"
        "cpu:cpu"
        "cpuacct:cpuacct"
        "blkio:blkio"
        "devices:devices"
        "freezer:freezer"
        "net_cls:net_cls"
        "net_prio:net_prio"
        "perf_event:perf_event"
        "hugetlb:hugetlb"
        "pids:pids"
        "rdma:rdma"
        "name=systemd:systemd"
    )
    # Use the memory controller to determine the container's root cgroup path,
    # to have a common hierarchy between all subsystems.
    ctr_relpath=$(get_cgroup_dir "memory")
    log "Using $ctr_relpath as the container's root cgroup path"
    umount -R /sys/fs/cgroup
    mount -t tmpfs tmpfs /sys/fs/cgroup
    mkdir /tmp/cgroup/
    mount -t tmpfs tmpfs /tmp/cgroup
    for subsys_dir in "${v1_subsys_dirs[@]}"; do
        subsys=${subsys_dir%%:*}
        dir_name=${subsys_dir#*:}
        log "Mounting $subsys under dir $dir_name"
        # Mount read-only under /sys/fs/cgroup/.
        mkdir -p "/sys/fs/cgroup/$dir_name"
        mount -t cgroup cgroup "/sys/fs/cgroup/$dir_name" -o "$subsys,ro,nosuid,nodev,noexec,relatime"
        # Mount read-write under /tmp/cgroup/, to use for creating bind mount.
        mkdir -p "/tmp/cgroup/$dir_name"
        mount -t cgroup cgroup "/tmp/cgroup/$dir_name" -o "$subsys,rw,nosuid,nodev,noexec,relatime"
        # Create and ensure the container's cgroup path, if necessary.
        mkdir -p "/tmp/cgroup/$dir_name$ctr_relpath"
        echo 1 > "/tmp/cgroup/$dir_name$ctr_relpath/cgroup.procs"
        # Create the read-write bind mount in /sys/fs/cgroup.
        mount --bind "/tmp/cgroup/$dir_name$ctr_relpath" "/sys/fs/cgroup/$dir_name$ctr_relpath"
    done
    # If the host supports unified then the '0::/...' entry will be found in
    # /proc/$PID/cgroup, and we set it up in case systemd wants to use it.
    if get_cgroup_dir ""; then
        dir_name=unified
        log "Mounting cgroupv2 hierarchy under dir $dir_name"
        # Mount read-only under /sys/fs/cgroup/.
        mkdir -p "/sys/fs/cgroup/$dir_name"
        mount -t cgroup2 cgroup2 "/sys/fs/cgroup/$dir_name" -o "ro,nosuid,nodev,noexec,relatime"
        # Mount read-write under /tmp/cgroup/, to use for creating bind mount.
        mkdir -p "/tmp/cgroup/$dir_name"
        mount -t cgroup2 cgroup2 "/tmp/cgroup/$dir_name" -o "rw,nosuid,nodev,noexec,relatime"
        # Create and ensure the container's cgroup path, if necessary.
        mkdir -p "/tmp/cgroup/$dir_name$ctr_relpath"
        echo 1 > "/tmp/cgroup/$dir_name$ctr_relpath/cgroup.procs"
        # Create the read-write bind mount in /sys/fs/cgroup.
        mount --bind "/tmp/cgroup/$dir_name$ctr_relpath" "/sys/fs/cgroup/$dir_name$ctr_relpath"
    fi
    umount -R /tmp/cgroup
    rmdir /tmp/cgroup
elif [[ $cgroup_mount_type == cgroup2fs ]]; then
    log "Detected cgroups v2"
    umount -R /sys/fs/cgroup/
    mkdir /tmp/cgroup/
    log "Mounting cgroupv2 hierarchy"
    # Mount read-only under /sys/fs/cgroup/.
    mount -t cgroup2 cgroup2 "/sys/fs/cgroup" -o "ro,nosuid,nodev,noexec,relatime"
    # Mount read-write under /tmp/cgroup/, to use for creating bind mount.
    mount -t cgroup2 cgroup2 "/tmp/cgroup" -o "rw,nosuid,nodev,noexec,relatime"
    # Create the read-write bind mount in /sys/fs/cgroup.
    mount --bind "/tmp/cgroup$ctr_relpath" "/sys/fs/cgroup$ctr_relpath"
    umount /tmp/cgroup
    rmdir /tmp/cgroup
else
    log_stderr "ERROR: Unable to detect cgroup version using /sys/fs/cgroup mount"
    exit 1
fi

# Start systemd.
exec /sbin/init
