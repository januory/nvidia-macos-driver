#!/usr/bin/env python3
"""The translator's shader-cache tag must name the build without hashing the whole dylib again.

nvmtl_translator_cache_tag ran on the first render pipeline's critical path and SHA-256'd all 15 MB of
libnvmtl_translate.dylib: a measured 47 ms pipeline build was 46.9 ms of that tag. dyld already hashed every
page to load the library, so the code signature's CDHash carries the same identity for a fraction of the cost.

Compiles the production tag function against real signed dylibs. The identity and cost arms fail on the
pre-fix code (which answers sha256- and pays the full hash); the correctness arms must hold either way.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1])
src = (root / 'plugin/NVMTLLibraryLoad.m').read_text()

start = src.index('static void nvmtl_translator_cache_tag(')
end = src.index('typedef int (*nvmtl_sampler_fn)')
funcs = src[start:end]
# The signature reader is what this change adds; without it the harness still builds and the arms below fail.
cd_start = src.find('static BOOL nvmtl_translator_cdhash(')
if cd_start >= 0:
    funcs = src[cd_start:start] + funcs

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#import <Security/Security.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include "nvmtl_spvcache_name.h"
#define nvlog(...) (fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
#define NVMTL_SPVCACHE_TAG_MAX_LOCAL 160
static char gXlateTag[NVMTL_SPVCACHE_TAG_MAX];

static double ms(void) { return (double)clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) / 1e6; }

/* What the tag cost before: read the file and SHA-256 all of it. Declared here rather than taken from the
   production source so this test compiles and runs against the unfixed code too. */
static double content_hash_ms(const char *path, char *out, size_t cap) {
    double t = ms();
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    CC_SHA256_CTX c; CC_SHA256_Init(&c); uint8_t b[65536]; ssize_t n;
    while (fd >= 0 && (n = read(fd, b, sizeof b)) > 0) CC_SHA256_Update(&c, b, (CC_LONG)n);
    if (fd >= 0) close(fd);
    uint8_t d[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_Final(d, &c);
    char hex[2 * CC_SHA256_DIGEST_LENGTH + 1];
    for (size_t i = 0; i < sizeof d; ++i) snprintf(hex + 2*i, 3, "%02x", d[i]);
    snprintf(out, cap, "sha256-%s", hex);
    return ms() - t;
}

static int fails;
static void arm(const char *what, int ok) { printf("%s  %s\n", ok ? "ok  " : "FAIL", what); if (!ok) fails++; }

int main(int argc, char **argv) {
    /* argv: big.dylib big2.dylib unsigned.dylib unsigned2.dylib copy.dylib */
    char tag[NVMTL_SPVCACHE_TAG_MAX], other[NVMTL_SPVCACHE_TAG_MAX], hash[NVMTL_SPVCACHE_TAG_MAX];

    double t = ms();
    nvmtl_translator_cache_tag(argv[1], tag, sizeof tag);
    double tag_ms = ms() - t;
    double hash_ms = content_hash_ms(argv[1], hash, sizeof hash);
    printf("      tag %s\n      tag %.2f ms, whole-file SHA-256 %.2f ms\n", tag, tag_ms, hash_ms);

    arm("the tag is the signature's CDHash, not a second pass over the file", strncmp(tag, "cdhash-", 7) == 0);
    arm("tagging costs under a third of the whole-file hash it replaces", tag_ms * 3.0 < hash_ms);

    nvmtl_translator_cache_tag(argv[2], other, sizeof other);
    arm("a different build gets a different tag", strcmp(tag, other) != 0);

    nvmtl_translator_cache_tag(argv[5], other, sizeof other);
    arm("the same bytes at another path keep the tag (a reinstall keeps the cache)", strcmp(tag, other) == 0);

    nvmtl_translator_cache_tag(argv[3], other, sizeof other);
    arm("an unsigned translator still gets a content tag", strncmp(other, "sha256-", 7) == 0);
    nvmtl_translator_cache_tag(argv[4], hash, sizeof hash);
    arm("two unsigned builds do not share a tag", strcmp(other, hash) != 0);

    arm("the tag leaves room for every mode suffix",
        nvmtl_spvcache_mode_tag(gXlateTag, sizeof gXlateTag, tag, 1, 1, 1, 1, 1) == 1);
    char entry[512];
    snprintf(entry, sizeof entry, "abc123.vertex.%s.c3.spv", gXlateTag);
    arm("the stale sweep recognises this build's own entries", nvmtl_spvcache_same_build(entry, tag) == 1);

    printf("%s\n", fails ? "FAIL" : "PASS");
    return fails ? 1 : 0;
}
'''


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def build_dylib(path, source, pad_bytes=0):
    """A real signed dylib. -sectcreate pads it to a size where hashing costs measurable milliseconds."""
    cmd = ['xcrun', 'clang', '-arch', 'x86_64', '-dynamiclib', '-O1', '-o', str(path), '-x', 'c', '-']
    if pad_bytes:
        pad = path.with_suffix('.pad')
        with open(pad, 'wb') as f:
            f.truncate(pad_bytes)
        cmd += ['-Wl,-sectcreate,__DATA,__pad,' + str(pad)]
    r = subprocess.run(cmd, input=source, capture_output=True, text=True)
    if r.returncode:
        sys.exit('FAIL could not build the test dylib: ' + r.stderr)
    r = run(['codesign', '-f', '-s', '-', '--identifier', 'com.nullmoth.test.translator', str(path)])
    if r.returncode:
        sys.exit('FAIL could not sign the test dylib: ' + r.stderr)


with tempfile.TemporaryDirectory() as td:
    d = pathlib.Path(td)
    # 8 MB: the whole-file hash costs ~25 ms, the signature read ~2 ms, so the cost arm has a wide margin.
    build_dylib(d / 'big.dylib', 'int nvmtl_translate(void) { return 1; }\n', 8 * 1024 * 1024)
    build_dylib(d / 'big2.dylib', 'int nvmtl_translate(void) { return 2; }\n', 8 * 1024 * 1024)
    build_dylib(d / 'unsigned.dylib', 'int nvmtl_translate(void) { return 3; }\n')
    build_dylib(d / 'unsigned2.dylib', 'int nvmtl_translate(void) { return 4; }\n')
    for n in ('unsigned.dylib', 'unsigned2.dylib'):
        run(['codesign', '--remove-signature', str(d / n)])
    (d / 'copy.dylib').write_bytes((d / 'big.dylib').read_bytes())

    harness = d / 'harness.m'
    # The production functions go after the includes so the header's declarations are in scope.
    harness.write_text(HARNESS.replace('static double ms(void)', funcs + '\nstatic double ms(void)', 1))

    exe = d / 'test_translator_tag'
    r = run(['xcrun', 'clang', '-arch', 'x86_64', '-fobjc-arc', '-O1', '-I', str(root / 'plugin'),
             '-o', str(exe), str(harness), '-framework', 'Foundation', '-framework', 'Security'])
    if r.returncode:
        sys.exit('FAIL the production tag function does not compile:\n' + r.stderr)
    r = run([str(exe)] + [str(d / n) for n in
                          ('big.dylib', 'big2.dylib', 'unsigned.dylib', 'unsigned2.dylib', 'copy.dylib')])
    print(r.stdout, end='')
    if r.stderr.strip():
        print(r.stderr, end='', file=sys.stderr)
    sys.exit(r.returncode)
