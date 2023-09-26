# Systemd Containers

This repo aims to exercise systemd running as a container payload in various configurations, demonstrating what works and what doesn't.
The primary focus is around cgroup setup, since this seems to be one of the trickiest things to get working with systemd in a container.

See <https://systemd.io/CONTAINER_INTERFACE/> for systemd's statement on how to run inside a container (how the container should be set up).

See <https://www.lewisgaul.co.uk/blog/coding/2022/05/13/cgroups-intro/> for an earlier blog post I wrote providing more background on cgroups, including some of my previous insights into their use within systemd and containers.


## Background

### Early Days, Cgroups v1

People have tried running systemd in Docker/Podman since when Docker first became popular.
One of the main problems that is hit when trying to run without `--privileged` is that systemd requires `/sys/fs/cgroup/systemd` to be mounted read-write, but it is mounted read-only in non-privileged containers.

There are various posts online where people recommend (for cgroups v1) passing `-v /sys/fs/cgroup:/sys/fs/cgroup:ro` into the container (see <https://developers.redhat.com/blog/2014/05/05/running-systemd-within-docker-container>, <https://stackoverflow.com/questions/36617368/docker-centos-7-with-systemctl-failed-to-mount-tmpfs-cgroup>, <https://zauner.nllk.net/post/0038-running-systemd-inside-a-docker-container/>), which works on a host running systemd because `/sys/fs/cgroup/systemd` will be read-write mounted (and on non-systemd hosts the mount can be created manually on the host).

The big problem with this approach is it breaks the container's cgroup isolation - the container has been given write access to the entirety of the host's cgroup hierarchies, and this is fundamentally incompatible with passing `--cgroupns=private` to set up a private cgroup namespace. (Aside: I assume the only reason private cgroup namespaces are not the default on cgroups v1 is that it was a new Linux kernel feature released in v4.6).
This means the container is capable of restricting the entire host's memory/pid/cpu usage, and this could be done *by accident* if the container payload software were to assume it's running on its own host (e.g. a system manager with lack of awareness of containers).

The Docker project has seemed uninterested in providing support for running systemd in containers, with many people saying that containers should have one small isolated purpose, perhaps even using only a single process.
Out of this came the RedHat Podman project, which aims to natively support systemd by ensuring `/sys/fs/cgroup/systemd` gets mounted read-write when needed.
However, Podman isn't always an option (e.g. Kubernetes in AWS EC2, running on a host not supported by Podman, instability in Podman, ...).

### Cgroups v2

As people started moving to hosts using cgroups v2 they found that the `-v /sys/fs/cgroup:/sys/fs/cgroup:ro` workaround was no longer working (see <https://serverfault.com/questions/1053187/systemd-fails-to-run-in-a-docker-container-when-using-cgroupv2-cgroupns-priva/1054414>, <https://github.com/moby/moby/issues/42275>).
The reason for this is that under cgroups v2 `/sys/fs/cgroup` is the unified hierarchy, and systemd requires the whole thing be writable.

Naively you would expect to be able to instead use `-v /sys/fs/cgroup:/sys/fs/cgroup:rw`.
However, the other difference with cgroups v2 is that Docker (and Podman) changed the default for `--cgroupns` to 'private', which I mentioned above is incompatible with passing the host's cgroup mount into the container.
Therefore `--cgroupns=host` must also be passed, and there's still the issue of a lack of container isolation that I described before.


## Repo Contents

This repo contains a suite of Python tests intended to exercise running systemd in a container in different configurations.
The tests are primarily intended to give insightful debug output, rather than performing extensive asserts on behaviour (although some checks are performed, such as ensuring successful container startup).

The tests are written in Python using the popular Pytest framweork.
See the section below on how to run them.

The tests are automatically parameterised on the following:
- Cgroup namespace setup (host/private)
- Systemd cgroup mode (if host uses cgroups v1 - legacy/hybrid)
- Setup mode (various setup approaches, in the form of a script that runs prior to starting systemd)

Note that the default behaviour would be as follows:
- On a host using cgroups v1:
  - `cgroupns=host`
  - `cgroup_mode=hybrid`
- On a host using cgroups v2:
  - `cgroupns=private`
  - `cgroup_mode=unified` (only option)
- `setup_mode=default` (systemd invoked directly)

There is also support for testing on different host setups (simply by running the tests on that host, or by passing `--container-host`) and using different container managers such as Podman by passing `--container-exe`.
There is known to be a sensitivity to the host setup, primarily around how the cgroup mounts are set up (e.g. whether the host is running systemd).
To test with cgroups v1 and v2, a host with the corresponding version must be used.


### Setup Modes

As documented by the tests, there are a few approaches to running systemd in a container:
- Use a privileged container (mounts are all read-write)
- Mount the host's `/sys/fs/cgroup` into the container (and use `cgroupns=host`)
- Use Podman's systemd mode (or `--security-opt unmask=/sys/fs/cgroup`)
- Use a custom script to set things up before systemd runs (generally requires `CAP_SYS_ADMIN` to be able to create mounts)

Various approaches for using a custom pre-systemd setup script are explored in these tests - see `tests/setup_modes/`.

These approaches include:
- `cgroupns` - create a cgroup namespace and set up cgroup mounts
  - This provides the container with proper cgroup isolation even if `cgroupns=host` was used.
  - Requires kernel version 4.6 or newer.
- `cgroupns_simple` - simpler approach to creating a cgroup namespace
  - Create a cgroup namespace with minimal mount setup, avoiding the need for `CAP_SYS_ADMIN` on cgroups v1.
- `inner_cgroup` - create an inner cgroup and move PID 1
  - Demonstration of creating a custom cgroup and systemd not having access to the full container cgroup paths.
  - This is capable of triggering the exec process issue intermittently reproduced on cgroups v2 by the `test_exec_proc_spam()` testcase, which is otherwise hit in systemd startup (this illustrates the possibility of implementing a retry or helpful error message). 
- `minimal` - only ensure `/sys/fs/cgroup/systemd` is writable (cgroups v1)
  - Only remount if needed, avoiding the need for `CAP_SYS_ADMIN` with Podman's systemd mode.
- `rebind` - recreate cgroup bind mounts such that host cgroups are read-only
  - Illustration of the complicated setup required to make the host's cgroup paths read-only with the container cgroup paths read-write.
- `unmount` - remove cgroup mounts for systemd to recreate
  - Simply remove cgroup mounts and let systemd do the setup.
  - This is the most compatible option with non-systemd hosts, since the container manager mirrors the host's cgroup mount setup which may not match systemd's approach.


## Running The Tests

Set up a Python virtual environment as follows:
```sh
python3 -m venv venv
source venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

Then run the tests with:
```sh
pytest --log-cli-level=debug
```

This will automatically parameterise the tests, running them all using Docker by default (use Podman by passing `--container-exe=podman`).
The tests can be filtered using `--setup-modes`, `--cgroupns`, `--cgroup-mode`, and the regular pytest `-k` argument.

The recommended way to make use of the tests is to observe the debug output, rather than just verifying that they pass - many of the tests aren't actually asserting anything interesting.

Note that the tests are known not to pass with rootless Podman in general, due to the lack of permissions for creating mounts.
However, some of the setup modes are still interesting to try with rootless Podman, such as 'default', 'cgroupns', and 'minimal'.

Example usage:
```
(venv) systemd-containers/(main)$ pytest --log-cli-level=debug --container-exe=docker --setup-mode=unmount --cgroup-mode=hybrid --cgroupns=host -k "test_non_priv or test_cgroup"
=============================================== test session starts ================================================
platform linux -- Python 3.9.5, pytest-7.4.0, pluggy-1.2.0
rootdir: /mnt/c/Users/legaul/Documents/personal/systemd-containers
configfile: pytest.ini
testpaths: tests/
collecting 240 items
----------------------------------------------- live log collection ------------------------------------------------
09:32:54:DEBUG[tests.conftest:170] Removing 296 test parameterisations that don't apply
09:32:54:DEBUG[tests.conftest:193] Removing 269 test parameterisations due to CLI args
collected 576 items / 5 deselected / 571 selected

tests/test_boot_success.py::test_non_priv[host-hybrid-unmount]
-------------------------------------------------- live log setup --------------------------------------------------
09:32:54:INFO[tests.conftest:234] Using container manager docker, see debug logs for detailed info
09:32:54:DEBUG[tests.utils:99] Running command: 'docker info'
09:32:54:DEBUG[tests.utils:149] Command stdout:
... <snip> ...
09:32:54:DEBUG[tests.utils:229] Building image using Dockerfile:
FROM ubuntu:20.04
RUN apt-get update -y \
    && apt-get install -y systemd \
    && ln -s /lib/systemd/systemd /sbin/init \
    && systemctl mask systemd-resolved.service \
    && systemctl set-default multi-user.target
RUN echo 'root:root' | chpasswd
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/sbin/init"]
09:32:54:DEBUG[tests.utils:229] Building image using Dockerfile:
FROM ubuntu-systemd:20.04
COPY init_script.sh /init_script.sh
ENTRYPOINT ["/init_script.sh"]
-------------------------------------------------- live log call ---------------------------------------------------
09:32:55:INFO[tests.conftest:474] Running container image ubuntu-systemd-unmount:20.04 with args: cap_add=['sys_admin'], tmpfs=['/run'], envs={'container': 'docker'}, tty=True, interactive=True, detach=True, remove=False, cgroupns=host, name=systemd-tests-1695717175.27
09:32:56:DEBUG[tests.conftest:514] Init script logs:
2023-09-26 08:32:55,772: Detected cgroups v1
2023-09-26 08:32:55,773: Unmounting all /sys/fs/cgroup mounts (allow systemd to recreate)
09:32:56:DEBUG[tests.conftest:515] Container boot logs:
systemd 245.4-4ubuntu3.22 running in system mode. (+PAM +AUDIT +SELINUX +IMA +APPARMOR +SMACK +SYSVINIT +UTMP +LIBCRYPTSETUP +GCRYPT +GNUTLS +ACL +XZ +LZ4 +SECCOMP +BLKID +ELFUTILS +KMOD +IDN2 -IDN +PCRE2 default-hierarchy=hybrid)
Detected virtualization wsl.
Detected architecture x86-64.

Welcome to Ubuntu 20.04.6 LTS!

Set hostname to <63f53fa2322b>.
[  OK  ] Created slice system-getty.slice.
[  OK  ] Created slice system-modprobe.slice.
[  OK  ] Created slice User and Session Slice.
[  OK  ] Started Dispatch Password ▒ts to Console Directory Watch.
[  OK  ] Started Forward Password R▒uests to Wall Directory Watch.
[  OK  ] Reached target Local Encrypted Volumes.
[  OK  ] Reached target Paths.
[  OK  ] Reached target Remote File Systems.
[  OK  ] Reached target Slices.
[  OK  ] Reached target Swap.
[  OK  ] Listening on initctl Compatibility Named Pipe.
[  OK  ] Listening on Journal Socket (/dev/log).
[  OK  ] Listening on Journal Socket.
         Mounting Huge Pages File System...
systemd-journald.service: Attaching egress BPF program to cgroup /sys/fs/cgroup/unified/docker/63f53fa2322b2edeb2f796759783575e1a81e3b0beac3cb04f3f8aa94e8578ea/system.slice/systemd-journald.service failed: Invalid argument
         Starting Journal Service...
         Mounting FUSE Control File System...
         Starting Remount Root and Kernel File Systems...
[  OK  ] Mounted Huge Pages File System.
[  OK  ] Mounted FUSE Control File System.
[  OK  ] Finished Remount Root and Kernel File Systems.
         Starting Create System Users...
[  OK  ] Started Journal Service.
         Starting Flush Journal to Persistent Storage...
[  OK  ] Finished Flush Journal to Persistent Storage.
[  OK  ] Finished Create System Users.
         Starting Create Static Device Nodes in /dev...
[  OK  ] Finished Create Static Device Nodes in /dev.
[  OK  ] Reached target Local File Systems (Pre).
[  OK  ] Reached target Local File Systems.
         Starting Create Volatile Files and Directories...
[  OK  ] Finished Create Volatile Files and Directories.
[  OK  ] Reached target System Time Set.
[  OK  ] Reached target System Time Synchronized.
         Starting Update UTMP about System Boot/Shutdown...
[  OK  ] Finished Update UTMP about System Boot/Shutdown.
[  OK  ] Reached target System Initialization.
[  OK  ] Started Daily apt download activities.
[  OK  ] Started Daily apt upgrade and clean activities.
[  OK  ] Started Periodic ext4 Onli▒ata Check for All Filesystems.
[  OK  ] Started Message of the Day.
[  OK  ] Started Daily Cleanup of Temporary Directories.
[  OK  ] Reached target Timers.
[  OK  ] Listening on D-Bus System Message Bus Socket.
[  OK  ] Reached target Sockets.
[  OK  ] Reached target Basic System.
[  OK  ] Started D-Bus System Message Bus.
         Starting Dispatcher daemon for systemd-networkd...
         Starting Login Service...
         Starting Permit User Sessions...
[  OK  ] Finished Permit User Sessions.
[  OK  ] Started Console Getty.
[  OK  ] Reached target Login Prompts.
[  OK  ] Started Login Service.
[  OK  ] Started Dispatcher daemon for systemd-networkd.
[  OK  ] Reached target Multi-User System.
         Starting Update UTMP about System Runlevel Changes...
[  OK  ] Finished Update UTMP about System Runlevel Changes.

09:32:57:WARNING[tests.test_boot_success:90] Unexpected boot log lines:
systemd-journald.service: Attaching egress BPF program to cgroup /sys/fs/cgroup/unified/docker/63f53fa2322b2edeb2f796759783575e1a81e3b0beac3cb04f3f8aa94e8578ea/system.slice/systemd-journald.service failed: Invalid argument
PASSED                                                                                                       [ 16%]
tests/test_boot_success.py::test_non_priv_systemd_mode[host-hybrid-unmount] SKIPPED (Systemd mode not su...) [ 33%]
tests/test_cgroups.py::test_cgroup_dir[host-hybrid-unmount]
-------------------------------------------------- live log call ---------------------------------------------------
09:32:58:INFO[tests.conftest:474] Running container image ubuntu-systemd-unmount:20.04 with args: tmpfs=['/run'], envs={'container': 'docker'}, cap_add=['sys_admin'], tty=True, interactive=True, detach=True, remove=False, cgroupns=host, name=systemd-tests-1695717178.02
09:32:59:DEBUG[tests.test_cgroups:19] Contents of /sys/fs/cgroup/:
total 0
dr-xr-xr-x 3 root root  0 Sep 24 14:05 blkio
lrwxrwxrwx 1 root root 11 Sep 26 08:32 cpu -> cpu,cpuacct
drwxr-xr-x 2 root root 40 Sep 26 08:32 cpu,cpuacct
lrwxrwxrwx 1 root root 11 Sep 26 08:32 cpuacct -> cpu,cpuacct
dr-xr-xr-x 3 root root  0 Sep 24 14:05 cpuset
dr-xr-xr-x 5 root root  0 Sep 24 14:05 devices
dr-xr-xr-x 3 root root  0 Sep 24 14:05 freezer
dr-xr-xr-x 3 root root  0 Sep 24 14:05 hugetlb
dr-xr-xr-x 6 root root  0 Sep 24 14:05 memory
lrwxrwxrwx 1 root root 16 Sep 26 08:32 net_cls -> net_cls,net_prio
drwxr-xr-x 2 root root 40 Sep 26 08:32 net_cls,net_prio
lrwxrwxrwx 1 root root 16 Sep 26 08:32 net_prio -> net_cls,net_prio
dr-xr-xr-x 3 root root  0 Sep 24 14:05 perf_event
dr-xr-xr-x 5 root root  0 Sep 24 14:05 pids
dr-xr-xr-x 3 root root  0 Sep 24 14:05 rdma
dr-xr-xr-x 6 root root  0 Sep 25 16:01 systemd
dr-xr-xr-x 3 root root  0 Sep 24 14:05 unified
PASSED                                                                                                       [ 50%]
tests/test_cgroups.py::test_cgroup_mounts[host-hybrid-unmount]
-------------------------------------------------- live log call ---------------------------------------------------
09:33:00:INFO[tests.conftest:474] Running container image ubuntu-systemd-unmount:20.04 with args: tmpfs=['/run'], envs={'container': 'docker'}, cap_add=['sys_admin'], tty=True, interactive=True, detach=True, remove=False, cgroupns=host, name=systemd-tests-1695717180.15
09:33:01:DEBUG[tests.test_cgroups:29] Cgroup mounts:
TARGET                      SOURCE  FSTYPE  OPTIONS
/sys/fs/cgroup              tmpfs   tmpfs   ro,nosuid,nodev,noexec,mode=755
|-/sys/fs/cgroup/unified    cgroup2 cgroup2 rw,nosuid,nodev,noexec,relatime,nsdelegate
|-/sys/fs/cgroup/systemd    cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,xattr,name=systemd
|-/sys/fs/cgroup/rdma       cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,rdma
|-/sys/fs/cgroup/blkio      cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,blkio
|-/sys/fs/cgroup/cpuset     cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,cpuset
|-/sys/fs/cgroup/memory     cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,memory
|-/sys/fs/cgroup/hugetlb    cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,hugetlb
|-/sys/fs/cgroup/pids       cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,pids
|-/sys/fs/cgroup/freezer    cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,freezer
|-/sys/fs/cgroup/perf_event cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,perf_event
`-/sys/fs/cgroup/devices    cgroup  cgroup  rw,nosuid,nodev,noexec,relatime,devices
PASSED                                                                                                       [ 66%]
tests/test_cgroups.py::test_cgroup_paths[host-hybrid-unmount]
-------------------------------------------------- live log call ---------------------------------------------------
09:33:02:INFO[tests.conftest:474] Running container image ubuntu-systemd-unmount:20.04 with args: tmpfs=['/run'], envs={'container': 'docker'}, cap_add=['sys_admin'], tty=True, interactive=True, detach=True, remove=False, cgroupns=host, name=systemd-tests-1695717182.69
09:33:04:DEBUG[tests.test_cgroups:43] Got PID 1 cgroups:
14:name=systemd:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/init.scope
13:rdma:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
12:pids:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
11:hugetlb:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
10:net_prio:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
9:perf_event:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
8:net_cls:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
7:freezer:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
6:devices:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
5:blkio:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
4:cpuacct:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
3:cpu:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
2:cpuset:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
1:memory:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
0::/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/init.scope
09:33:04:DEBUG[tests.test_cgroups:46] Got systemd-journald (PID 25) cgroups:
14:name=systemd:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/system.slice/systemd-journald.service
13:rdma:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
12:pids:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/system.slice/systemd-journald.service
11:hugetlb:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
10:net_prio:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
9:perf_event:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
8:net_cls:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
7:freezer:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
6:devices:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/system.slice/systemd-journald.service
5:blkio:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
4:cpuacct:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
3:cpu:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
2:cpuset:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c
1:memory:/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/system.slice/systemd-journald.service
0::/docker/97ecda794d72e6e641306916fbb2fc5e8738ddc1e6ceeadf36217b5716b0390c/system.slice/systemd-journald.service
PASSED                                                                                                       [ 83%]
tests/test_cgroups.py::test_cgroup_controllers[host-hybrid-unmount]
-------------------------------------------------- live log call ---------------------------------------------------
09:33:05:INFO[tests.conftest:474] Running container image ubuntu-systemd-unmount:20.04 with args: tmpfs=['/run'], envs={'container': 'docker'}, cap_add=['sys_admin'], tty=True, interactive=True, detach=True, remove=False, cgroupns=host, name=systemd-tests-1695717185.28
09:33:06:DEBUG[tests.test_cgroups:59] Enabled controllers: {'memory', 'pids', 'devices'}
PASSED                                                                                                       [100%]

=================================== 5 passed, 1 skipped, 5 deselected in 14.14s ====================================
```
