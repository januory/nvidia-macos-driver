// Does a stage-boundary counter sample resolve to a sane GPU timestamp?
// The device now claims MTLCounterSamplingPointAtStageBoundary, which makes UE's Metal RHI enable
// timestamp render queries. If a sample never lands, UE would wait on a query that cannot resolve,
// so the claim has to be backed by values that arrive and advance.
//
// Build and run on a supported card (needs a GPU, so run_all_tests leaves it to the build step):
//   clang -fobjc-arc -O1 -o /tmp/test_stage_counter_sampling tools/test_stage_counter_sampling.m -framework Metal -framework Foundation
//   /tmp/test_stage_counter_sampling
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdio.h>

static NSString *src(void) {
    return @"#include <metal_stdlib>\nusing namespace metal;\n"
            "vertex float4 vs(uint v [[vertex_id]]) { float2 q = float2(float((v<<1)&2), float(v&2)); return float4(q*2.0-1.0,0,1); }\n"
            "fragment float4 fs() { float4 c = float4(0.3,0.5,0.7,1); for (int k=0;k<64;++k) c = sqrt(abs(c)+1e-4)*1.0009; return c; }\n";
}

int main(void) {
    @autoreleasepool {
        id<MTLDevice> d = MTLCreateSystemDefaultDevice();
        if (!d) { fprintf(stderr, "no device\n"); return 2; }
        printf("stage boundary supported: %s\n", [d supportsCounterSampling:MTLCounterSamplingPointAtStageBoundary] ? "YES" : "no");
        printf("timestamp frequency: %llu Hz\n", (unsigned long long)d.queryTimestampFrequency);

        MTLCounterSampleBufferDescriptor *sd = [MTLCounterSampleBufferDescriptor new];
        sd.counterSet = d.counterSets.firstObject;
        sd.sampleCount = 4;
        sd.storageMode = MTLStorageModeShared;
        NSError *e = nil;
        id<MTLCounterSampleBuffer> sb = [d newCounterSampleBufferWithDescriptor:sd error:&e];
        if (!sb) { printf("FAIL sample buffer: %s\n", e.description.UTF8String ?: "?"); return 3; }

        id<MTLLibrary> l = [d newLibraryWithSource:src() options:nil error:&e];
        if (!l) { printf("FAIL library: %s\n", e.description.UTF8String ?: "?"); return 3; }
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [l newFunctionWithName:@"vs"];
        pd.fragmentFunction = [l newFunctionWithName:@"fs"];
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
        id<MTLRenderPipelineState> pso = [d newRenderPipelineStateWithDescriptor:pd error:&e];
        if (!pso) { printf("FAIL pipeline: %s\n", e.description.UTF8String ?: "?"); return 3; }

        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                                                                      width:512 height:512 mipmapped:NO];
        td.usage = MTLTextureUsageRenderTarget; td.storageMode = MTLStorageModePrivate;
        id<MTLTexture> tex = [d newTextureWithDescriptor:td];
        id<MTLCommandQueue> q = [d newCommandQueue];

        int fails = 0;
        for (int round = 0; round < 3; round++) {
            MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
            rp.colorAttachments[0].texture = tex;
            rp.colorAttachments[0].loadAction = MTLLoadActionClear;
            rp.colorAttachments[0].storeAction = MTLStoreActionStore;

            id<MTLCommandBuffer> cb = [q commandBuffer];
            // Two passes, each bracketed on its own encoder: the stage-boundary usage UE's RHI makes.
            id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
            [enc setRenderPipelineState:pso];
            [enc sampleCountersInBuffer:sb atSampleIndex:0 withBarrier:YES];
            for (int i = 0; i < 20; i++) [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [enc sampleCountersInBuffer:sb atSampleIndex:1 withBarrier:YES];
            [enc endEncoding];
            id<MTLRenderCommandEncoder> enc2 = [cb renderCommandEncoderWithDescriptor:rp];
            [enc2 setRenderPipelineState:pso];
            [enc2 sampleCountersInBuffer:sb atSampleIndex:2 withBarrier:YES];
            for (int i = 0; i < 20; i++) [enc2 drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [enc2 sampleCountersInBuffer:sb atSampleIndex:3 withBarrier:YES];
            [enc2 endEncoding];
            [cb commit];
            [cb waitUntilCompleted];

            NSData *resolved = [sb resolveCounterRange:NSMakeRange(0, 4)];
            if (resolved.length != 4 * sizeof(MTLCounterResultTimestamp)) {
                printf("FAIL round %d: resolve gave %zu bytes\n", round, (size_t)resolved.length); fails++; continue;
            }
            const MTLCounterResultTimestamp *t = resolved.bytes;
            uint64_t a = t[0].timestamp, b = t[1].timestamp, c = t[2].timestamp, f = t[3].timestamp;
            int ok = a != MTLCounterErrorValue && b != MTLCounterErrorValue &&
                     c != MTLCounterErrorValue && f != MTLCounterErrorValue &&
                     a != 0 && b >= a && c >= b && f >= c;
            double us = (double)(f - a) * 1e9 / (double)d.queryTimestampFrequency / 1000.0;
            printf("%s round %d: p1-open %llu  p1-end %llu  p2-open %llu  p2-end %llu   span %.1f us\n",
                   ok ? "ok  " : "FAIL", round, (unsigned long long)a, (unsigned long long)b,
                   (unsigned long long)c, (unsigned long long)f, us);
            if (!ok) fails++;
        }
        printf("%s\n", fails ? "FAIL" : "PASS");
        return fails ? 1 : 0;
    }
}
