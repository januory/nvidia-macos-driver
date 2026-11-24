#!/usr/bin/env python3
"""Every counter sampling point the device claims must be served by a real timestamp write.

The device withheld MTLCounterSamplingPointAtStageBoundary although all three encoders already
implemented sampleCountersInBuffer. UE's Metal RHI reads that one point to set
GSupportsTimestampRenderQueries, so withholding it turned off timestamp render queries entirely.

This pins the invariant in both directions: a claimed point needs an implementing entry point, and a
timestamp write must be legal outside a render pass (that is what a stage boundary is). The stage arm
fails on the pre-fix device. Hardware acceptance is tools/test_stage_counter_sampling.m.
"""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1])
dev = (root / 'plugin/NVMTLDevice.m').read_text()
obj = (root / 'plugin/NVMTLObjects.m').read_text()
vk = (root / 'plugin/nvmtl_vk.c').read_text()

fails = []


def arm(what, ok):
    print(('ok    ' if ok else 'FAIL  ') + what)
    if not ok:
        fails.append(what)


m = re.search(r'-\s*\(BOOL\)supportsCounterSampling:\(MTLCounterSamplingPoint\)\w*\s*\{(.*?)\n\}', dev, re.S)
if not m:
    sys.exit('FAIL supportsCounterSampling: is not defined in NVMTLDevice.m')
body = m.group(1)
claimed = set(re.findall(r'MTLCounterSamplingPointAt(\w+)Boundary', body))

# The point UE queries for timestamp render queries, and the three it uses for per-boundary sampling.
for point in ('Stage', 'Draw', 'Dispatch', 'Blit'):
    arm(f'the device claims At{point}Boundary', point in claimed)

# Each claimed point is sampled through an encoder entry point that routes to the one write helper.
sites = re.findall(r'-\s*\(void\)sampleCountersInBuffer:[^\n]*\{\s*nvmtl_sample_counter\(', obj)
arm('all three encoders and the command buffer route sampling to one helper', len(sites) >= 4)
arm('the sampling helper writes a Vulkan timestamp', 'nvmtl_vk_cmd_ts_write(' in obj)
arm('the timestamp write is a real vkCmdWriteTimestamp', 'pvkCmdWriteTimestamp(' in vk)

# A stage boundary is a point with no render pass open. The write must handle that rather than refuse it.
arm('a timestamp outside a render pass is flushed, not refused',
    re.search(r'return\s+c->in_rp\s*\?\s*0\s*:\s*nvmtl_counter_flush\(c\)\s*;', vk) is not None)

print('FAIL' if fails else 'PASS')
sys.exit(1 if fails else 0)
