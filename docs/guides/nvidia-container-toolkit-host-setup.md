# NVIDIA Container Toolkit Host Setup

This guide prepares a Linux developer host to run the RoboHarness Isaac Sim
container with an NVIDIA GPU. It configures the host, not the project image.
The project image can be built without a GPU; the Toolkit is required when
Docker starts that image with `gpus: all`.

The supported PR 13 validation host is Ubuntu 22.04 x86_64 with rootful Docker
Engine. Follow the variant notes below instead of applying the primary commands
unchanged to rootless Docker, WSL2, Jetson, or a remote Docker daemon.

## What the Toolkit provides

The four layers are separate:

1. the host NVIDIA driver owns the physical GPU and kernel modules;
2. NVIDIA Container Toolkit exposes devices and matching driver libraries to a
   container;
3. CDI (Container Device Interface) describes the available NVIDIA devices to
   Docker/containerd; and
4. CUDA or Isaac Sim inside the image consumes the injected GPU.

Do not install the CUDA development toolkit merely to fix Docker GPU access.
Do not copy host driver libraries into the Isaac image. NVIDIA's
[Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
is the authority for supported distributions and current repository commands.

## Choose the correct host path

| Host | Project support | Action |
| --- | --- | --- |
| Ubuntu 22.04 x86_64, rootful Docker | PR 13 validation baseline | Follow this guide |
| Other supported Debian/Ubuntu release | Developer-local only until recorded | Use NVIDIA's matching `apt` instructions, then run the same probes |
| Rootless Docker | Not the current baseline | Use the rootless variant below |
| Docker Desktop / WSL2 | Not a PR 13 acceptance host | Use Docker Desktop GPU support; do not apply the systemd steps blindly |
| Jetson/aarch64 | Cannot run the pinned x86_64 Isaac Sim image | Use a remote x86_64 RTX host |
| CPU-only or non-NVIDIA GPU | CPU development and mock stack only | Do not run `make isaac-smoke` |
| Remote Docker context | Toolkit belongs on the daemon host | Configure the remote machine, not the CLI workstation |

## 1. Verify the driver before changing Docker

Run on the Docker daemon host:

```bash
uname -m
cat /etc/os-release
uname -r
nvidia-smi
```

Stop here if `nvidia-smi` fails. Container Toolkit cannot repair a missing,
unloaded, Secure-Boot-blocked, or incompatible host driver. For the pinned
Isaac Sim 4.5 runtime, also check the driver requirements in the
[Isaac Sim requirements](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/requirements.html).
After installing or upgrading a driver, reboot before continuing: a successful
package/DKMS installation does not prove that the running kernel loaded the new
module.

Record the current Docker mode and version:

```bash
docker context show
docker info
docker compose version
```

The commands below assume the active context points to the local, rootful
Docker daemon. Restarting Docker can stop every container on the host; schedule
that interruption before continuing.

## 2. Add NVIDIA's `apt` repository

Install the repository prerequisites:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends curl gnupg
```

Download and install NVIDIA's repository key:

```bash
curl --fail --silent --show-error --location \
  https://nvidia.github.io/libnvidia-container/gpgkey \
  --output /tmp/nvidia-container-toolkit.gpgkey
sudo gpg --dearmor --yes \
  --output /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  /tmp/nvidia-container-toolkit.gpgkey
```

Add the stable Debian repository with the key restricted to that source:

```bash
curl --fail --silent --show-error --location \
  https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  --output /tmp/nvidia-container-toolkit.list
sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  /tmp/nvidia-container-toolkit.list \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
```

Before installation, `apt-cache policy nvidia-container-toolkit` should show a
candidate from `nvidia.github.io`. If it does not, inspect the generated source
file, proxy, DNS, system clock, and keyring rather than proceeding with an
unrelated package.

## 3. Install and record the Toolkit

Install the stable package set:

```bash
sudo apt-get install --yes nvidia-container-toolkit
nvidia-ctk --version
nvidia-container-cli --version
dpkg-query --show 'nvidia-container-toolkit*' 'libnvidia-container*'
```

The host package is deliberately not pinned in the project image. Record the
actual version in validation evidence so failures can be reproduced. Teams
that centrally pin host packages should select a version visible in
`apt-cache madison nvidia-container-toolkit` and keep all Toolkit/library
packages on the same release.

## 4. Configure rootful Docker

If `/etc/docker/daemon.json` already exists, inspect and back it up because it
may contain registry mirrors, proxies, or other site policy. Then let
`nvidia-ctk` add the NVIDIA runtime without replacing unrelated keys:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify that Docker came back and registered the runtime:

```bash
systemctl is-active docker
docker info
```

If the developer uses Docker without `sudo`, membership changes take effect
only in a new login session:

```bash
getent group docker
id
newgrp docker
docker version
```

Only add a trusted local user to the `docker` group. That group is effectively
root-equivalent on the host.

## 5. Verify or refresh CDI

Recent Toolkit releases generate a transient NVIDIA CDI specification using
`nvidia-cdi-refresh`. Inspect it with:

```bash
nvidia-ctk cdi list
systemctl status nvidia-cdi-refresh.path
systemctl status nvidia-cdi-refresh.service
ls -l /var/run/cdi/nvidia.yaml
```

After changing the GPU driver or device configuration, refresh and check it:

```bash
sudo systemctl restart nvidia-cdi-refresh.service
nvidia-ctk cdi list
```

If the installed Toolkit predates `nvidia-cdi-refresh`, follow the
[NVIDIA CDI support guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html)
for that exact version. A manual fallback is:

```bash
sudo mkdir -p /etc/cdi
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
nvidia-ctk cdi list
```

Do not keep stale specifications in both `/etc/cdi` and `/var/run/cdi`. Prefer
the managed refresh service when it is available.

## 6. Prove generic Docker GPU access

First test the same `--gpus all` path used by RoboHarness:

```bash
docker run --rm --gpus all ubuntu:22.04 nvidia-smi
```

The GPU name and driver version should match the host. An optional explicit CDI
probe on Docker versions that support CDI is:

```bash
docker run --rm --device=nvidia.com/gpu=all ubuntu:22.04 nvidia-smi
```

These probes are independent of Isaac Sim and are based on Docker's
[GPU container documentation](https://docs.docker.com/engine/containers/resource_constraints/#gpu).
Do not diagnose the RoboHarness extension until the generic probe passes.

## 7. Validate RoboHarness

From the repository root:

```bash
cp deployment/env/.env.example deployment/env/.env
```

Review NVIDIA's Omniverse EULA, then set `ACCEPT_EULA=Y` in the untracked
`deployment/env/.env`. Continue with:

```bash
make isaac-config
make isaac-smoke
```

Passing `make isaac-smoke` proves that the pinned Isaac image starts on this
host and an external ROS 2 observer receives the native `/clock`. Evidence is
written under `.build/isaac-smoke/`; retain the directory and record the host
OS, kernel, GPU, driver, Docker, Compose, Toolkit, and image digest.

The reference PR 13 run on 2026-08-24 passed with Ubuntu 22.04.5, kernel
`6.8.0-138-generic`, driver `580.173.02`, and Toolkit `1.20.0`. Treat this as a
known-good snapshot, not a requirement to replace another driver that already
satisfies Isaac Sim 4.5 and passes the generic GPU probe.

## Rootless Docker variant

Do not modify `/etc/docker/daemon.json` for a rootless daemon. Confirm rootless
mode in `docker info`, then follow NVIDIA's rootless Docker section. The current
upstream flow uses the user's daemon configuration and user service:

```bash
nvidia-ctk runtime configure \
  --runtime=docker \
  --config="${HOME}/.config/docker/daemon.json"
systemctl --user restart docker
sudo nvidia-ctk config \
  --set nvidia-container-cli.no-cgroups \
  --in-place
```

Run the generic GPU probe again. Rootless results are developer-local until the
project records that host configuration as a validated target.

## Failure routing

| Symptom | Layer to investigate | First checks |
| --- | --- | --- |
| Host `nvidia-smi` fails | Driver/kernel/Secure Boot | driver module, kernel log, reboot state |
| `nvidia-container-cli` is missing | Toolkit package/repository | `apt-cache policy`, NVIDIA source file |
| Docker socket permission denied | User session/context | `docker context show`, `id`, new login |
| `no known GPU vendor found` | CDI generation/discovery | `nvidia-ctk cdi list`, refresh service, CDI files |
| `could not select device driver` | Docker runtime configuration | `docker info`, `nvidia-ctk runtime configure`, daemon restart |
| Container cannot load `libcuda.so.1` | GPU/driver-library injection | generic `docker run --gpus all` probe |
| Generic probe passes but Isaac fails | Isaac/Kit/project layer | `.build/isaac-smoke/*/compose.log` and `env.log` |

Never work around these failures by embedding the host driver in the image,
running a privileged container, weakening device permissions globally, or
claiming GPU validation from a successful image build alone.
