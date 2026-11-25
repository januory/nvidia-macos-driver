#!/usr/bin/env python3
"""The translator emits formatless storage images, so the plugin must enable the features that allow them.

A Metal texture's format lives in the bound resource, not in the shader's type: `texture3d<float, write>`
carries no format. The translator therefore declares every storage image with ImageFormat::Unknown and
declares OpCapability StorageImageWriteWithoutFormat / ReadWithoutFormat. Vulkan requires the matching
VkPhysicalDeviceFeatures to be ENABLED, not merely supported, before a formatless storage image is used.

None of the three was ever enabled. UE's volumetric-fog light scattering compute writes a 160x90x128
RGBA16F texture3d exactly this way, and its channel died with error notifier info32 0xd -- Xid 13, a
graphics engine exception, with GET_MMU_FAULT_INFO returning addr 0 / type NONE and every buffer binding
of the faulting dispatch resolving to a live range.

This is a cross-component invariant: it reads what the translator emits and what the plugin asks for, and
fails when they disagree. Both arms fail on the plugin as it stood.
"""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1])
vk = (root / 'plugin/nvmtl_vk.c').read_text()
cfg = root / 'translator/translator/src/native/owned_cfg.rs'

fails = []


def arm(what, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + what + (('  ' + detail) if detail else ''))
    if not ok:
        fails.append(what)


# The requirement is real only if the translator actually emits formatless storage images.
src = cfg.read_text() if cfg.exists() else ''
arm('the translator declares storage images with ImageFormat::Unknown',
    'ImageFormat::Unknown' in src or 'spirv::ImageFormat::Unknown' in src)
arm('the translator declares StorageImageWriteWithoutFormat', 'StorageImageWriteWithoutFormat' in src)
arm('the translator declares StorageImageReadWithoutFormat', 'StorageImageReadWithoutFormat' in src)

# What the plugin asks the device for. Assignment from `supported.` is the shipped pattern: enable it
# when the device has it, leave it off when it does not.
for feat in ('shaderStorageImageWriteWithoutFormat', 'shaderStorageImageReadWithoutFormat',
             'shaderStorageImageExtendedFormats'):
    arm('the plugin enables %s when the device supports it' % feat,
        re.search(r'enabled\.' + feat + r'\s*=\s*supported\.' + feat, vk) is not None)

arm('the plugin reports what it got, so a refusal is visible in a log',
    'formatless storage images:' in vk)

print('FAIL' if fails else 'PASS')
sys.exit(1 if fails else 0)
