#!/bin/bash
# Cross-distro compatibility: expose only NVIDIA's already installed 32-bit
# libraries to Debian's loader. Do not add Arch's libc or /opt/host-lib32 to
# LD_LIBRARY_PATH. The host directory is mounted read-only into this container.
set -e
if [[ -d /opt/host-lib32 ]]; then
    shopt -s nullglob
    for library in /opt/host-lib32/libnvidia*.so* /opt/host-lib32/libGLX_nvidia.so* /opt/host-lib32/libEGL_nvidia.so* /opt/host-lib32/libGLESv1_CM_nvidia.so* /opt/host-lib32/libGLESv2_nvidia.so* /opt/host-lib32/libnvcuvid.so* /opt/host-lib32/libcuda.so*; do
        [[ -f "$library" ]] || continue
        ln -sfn "$library" "/usr/lib/i386-linux-gnu/${library##*/}"
    done
    ldconfig
fi
