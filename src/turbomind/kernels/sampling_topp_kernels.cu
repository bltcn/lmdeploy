/*
 * Copyright (c) 2019-2023, NVIDIA CORPORATION.  All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef CUDART_VERSION
#error CUDART_VERSION Undefined!
#elif (CUDART_VERSION >= 11000)
#include <cub/cub.cuh>
#else
#include "3rdparty/cub/cub.cuh"
#endif

#include "src/turbomind/core/core.h"

#include "src/turbomind/kernels/core/math.h"
#include "src/turbomind/kernels/reduce_kernel_utils.cuh"
#include "src/turbomind/kernels/sampling_topp_kernels.h"

#include "src/turbomind/utils/constant.h"
#include "src/turbomind/utils/cuda_utils.h"

namespace turbomind {

__global__ void topPSortInitialize(const int    vocab_size_padded,
                                   const int    vocab_size,
                                   const size_t batch_size,
                                   const int*   top_ks,
                                   int*         topp_id_val_buf,
                                   int*         begin_offset_buf,
                                   int*         end_offset_buf)
{
    int tid = threadIdx.x;
    int bid = blockIdx.x;

    // According to https://nvidia.github.io/cccl/cub/api/structcub_1_1DeviceSegmentedRadixSort.html
    // `num_items` should match the largest element within the range `[d_end_offsets, d_end_offsets + num_segments)`
    // We need to move `begin_offset` (instead of `end_offset`) to make empty intervals
    if (bid == 0) {
        for (int i = tid; i < batch_size; i += blockDim.x) {
            int beg = i * vocab_size_padded;
            int end = i * vocab_size_padded + vocab_size;
            if (top_ks[i] > 0) {  // already sorted by topk, make it an empty interval
                beg = end;
            }
            begin_offset_buf[i] = beg;
            end_offset_buf[i]   = end;
        }
    }

    int index = tid + bid * blockDim.x;
    while (index < batch_size * vocab_size_padded) {
        int batch_id = index / vocab_size_padded;
        if (top_ks[batch_id] == 0) {
            // sort by topp
            topp_id_val_buf[index] = index % vocab_size_padded;
        }
        index += blockDim.x * gridDim.x;
    }
}

void invokeTopPSortInitialize(const int    vocab_size_padded,
                              const int    vocab_size,
                              const size_t batch_size,
                              const int*   top_ks,
                              int*         topp_id_val_buf,
                              int*         begin_offset_buf,
                              int*         end_offset_buf,
                              cudaStream_t stream)
{
    const size_t block_size = 512;
    const size_t grid_size  = (batch_size * vocab_size_padded + block_size - 1) / block_size;
    topPSortInitialize<<<grid_size, block_size, 0, stream>>>(
        vocab_size_padded, vocab_size, batch_size, top_ks, topp_id_val_buf, begin_offset_buf, end_offset_buf);
}

template<typename T>
static __global__ void softmax(T* logits, const int vocab_size_padded, const int vocab_size, const int* kept)
{
    int bid = blockIdx.x;
    int n   = kept[bid];
    // skip softmax as it was already done by topk
    if (n != vocab_size) {
        return;
    }
    logits += bid * vocab_size_padded;

    float            max_val = -1 * FLT_MAX;
    __shared__ float s_max_val;
    __shared__ float s_sum_val;

    for (int tid = threadIdx.x; tid < vocab_size; tid += blockDim.x) {
        max_val = max(max_val, (float)logits[tid]);
    }

    max_val = blockReduceMax<float>((float)max_val);
    if (threadIdx.x == 0) {
        s_max_val = max_val;
    }
    __syncthreads();

    max_val       = s_max_val;
    float sum_val = 0.0f;
    for (int tid = threadIdx.x; tid < vocab_size; tid += blockDim.x) {
        logits[tid] = __expf((float)logits[tid] - max_val);
        sum_val += (float)logits[tid];
    }

    sum_val = blockReduceSum<float>(sum_val);
    if (threadIdx.x == 0) {
        s_sum_val = sum_val;
    }
    __syncthreads();

    sum_val = s_sum_val;
    for (int tid = threadIdx.x; tid < vocab_size; tid += blockDim.x) {
        logits[tid] = ((float)logits[tid] / sum_val);
    }
}

template<typename T>
void invokeSoftmax(T*           logits,
                   const int    vocab_size_padded,
                   const int    vocab_size,
                   const int    batch_size,
                   const int*   kept,
                   cudaStream_t stream)
{
    dim3 grid(batch_size);
    dim3 block(std::min(vocab_size_padded, 1024));
    softmax<<<grid, block, 0, stream>>>(logits, vocab_size_padded, vocab_size, kept);
}

#define INSTANTIATE_INVOKE_SOFTMAX(T)                                                                                  \
    template void invokeSoftmax<T>(T * logits,                                                                         \
                                   const int    vocab_size_padded,                                                     \
                                   const int    vocab_size,                                                            \
                                   const int    batch_size,                                                            \
                                   const int*   kept,                                                                  \
                                   cudaStream_t stream);

INSTANTIATE_INVOKE_SOFTMAX(float);

template<typename T, int MAX_K, int THREADBLOCK_SIZE>
__launch_bounds__(THREADBLOCK_SIZE) __global__ void topp_beam_topk_kernel(const T*     logits,
                                                                          T*           sorted_logits,
                                                                          int*         sorted_indices,
                                                                          int*         kept,
                                                                          const int    vocab_size,
                                                                          const int    vocab_size_padded,
                                                                          int*         begin_offset_buf,
                                                                          int*         end_offset_buf,
                                                                          const float* top_ps,
                                                                          const int*   top_ks)
{
    int thread_id = threadIdx.x;
    int batch_id  = blockIdx.x;
    if (top_ks[batch_id] > 0) {
        return;
    }

    logits += batch_id * vocab_size_padded;
    sorted_logits += batch_id * vocab_size_padded;
    sorted_indices += batch_id * vocab_size_padded;
    float p_threshold = top_ps[batch_id];

    typedef cub::BlockReduce<TopK<T, MAX_K>, THREADBLOCK_SIZE> BlockReduce;
    __shared__ typename BlockReduce::TempStorage               temp_storage;
    TopK<T, MAX_K>                                             partial;

    const T MAX_T_VAL = getMaxValue<T>();

#pragma unroll
    for (int i = 0; i < MAX_K; ++i) {
        partial.p[i] = -1;
        partial.u[i] = -MAX_T_VAL;
    }

#pragma unroll
    for (int elem_id = thread_id; elem_id < vocab_size; elem_id += THREADBLOCK_SIZE) {
        partial.insert(logits[elem_id], elem_id);
    }

    TopK<T, MAX_K> total = BlockReduce(temp_storage).Reduce(partial, reduce_topk_op<T, MAX_K>);

    if (thread_id == 0) {
        float sum_prob = 0.f;

#pragma unroll
        for (int i = 0; i < MAX_K; i++) {
            sum_prob += (float)total.u[i];
        }

        if (sum_prob >= p_threshold) {
            begin_offset_buf[batch_id] = end_offset_buf[batch_id];
            kept[batch_id]             = MAX_K;

#pragma unroll
            for (int i = 0; i < MAX_K; ++i) {
                sorted_logits[i]  = (float)total.u[i] / sum_prob;
                sorted_indices[i] = total.p[i];
            }
        }
    }
}

template<typename T>
void invokeTopPSort(TopPSortParams& params, cudaStream_t stream)
{
    const int num_items = params.vocab_size_padded * (params.batch_size - 1) + params.vocab_size;

    size_t cub_temp_storage_size{};
    check_cuda_error(cub::DeviceSegmentedRadixSort::SortPairsDescending(nullptr,
                                                                        cub_temp_storage_size,
                                                                        (T*)nullptr,
                                                                        (T*)nullptr,
                                                                        (int*)nullptr,
                                                                        (int*)nullptr,
                                                                        num_items,
                                                                        params.batch_size,
                                                                        (int*)nullptr,
                                                                        (int*)nullptr,
                                                                        0,              // begin_bit
                                                                        sizeof(T) * 8,  // end_bit = sizeof(KeyT) * 8
                                                                        stream));       // cudaStream_t

    TM_CHECK(core::Context::stream().handle() == stream);

    Buffer_<uint8_t> cub_temp_storage(cub_temp_storage_size, kDEVICE);

    Buffer_<int> topp_ids(params.batch_size * params.vocab_size_padded, kDEVICE);
    Buffer_<int> beg_offset(params.batch_size, kDEVICE);
    Buffer_<int> end_offset(params.batch_size, kDEVICE);

    auto topp_ids_buf   = topp_ids.data();
    auto beg_offset_buf = beg_offset.data();
    auto end_offset_buf = end_offset.data();

    invokeTopPSortInitialize(params.vocab_size_padded,
                             params.vocab_size,
                             params.batch_size,
                             params.top_ks,
                             topp_ids_buf,
                             beg_offset_buf,
                             end_offset_buf,
                             stream);

    topp_beam_topk_kernel<T, 1, 256><<<params.batch_size, 256, 0, stream>>>((T*)params.logits,
                                                                            (T*)params.sorted_logits,
                                                                            params.sorted_indices,
                                                                            params.kept,
                                                                            params.vocab_size,
                                                                            params.vocab_size_padded,
                                                                            beg_offset_buf,
                                                                            end_offset_buf,
                                                                            params.top_ps,
                                                                            params.top_ks);

    check_cuda_error(cub::DeviceSegmentedRadixSort::SortPairsDescending(cub_temp_storage.data(),
                                                                        cub_temp_storage_size,
                                                                        (T*)params.logits,
                                                                        (T*)params.sorted_logits,
                                                                        topp_ids_buf,
                                                                        params.sorted_indices,
                                                                        num_items,
                                                                        params.batch_size,
                                                                        beg_offset_buf,
                                                                        end_offset_buf,
                                                                        0,              // begin_bit
                                                                        sizeof(T) * 8,  // end_bit = sizeof(KeyT) * 8
                                                                        stream));       // cudaStream_t
}

template void invokeTopPSort<float>(TopPSortParams& params, cudaStream_t stream);

template<typename T, int BLOCK_SIZE>
__global__ void topPMinPFilter(T*           sorted_logits,
                               int*         sorted_indices,
                               int*         kept,
                               const int    vocab_size_padded,
                               const float* top_ps,
                               const float* min_ps)
{
    int   tid        = threadIdx.x;
    int   bid        = blockIdx.x;
    int   n          = kept[bid];
    float sum_logits = 1.f;
    float top_p      = top_ps[bid];
    float min_p      = min_ps[bid];
    sorted_logits += bid * vocab_size_padded;
    sorted_indices += bid * vocab_size_padded;

    const float kEps = 1e-6f;

    __shared__ int   s_kept;
    __shared__ float s_sum;

    if (tid == 0) {
        s_kept = n;
        s_sum  = 1.f;
    }
    __syncthreads();

    if (top_p != 1.0f) {
        typedef cub::BlockScan<float, BLOCK_SIZE>  BlockScan;
        __shared__ typename BlockScan::TempStorage temp_storage;
        // Initialize running total
        BlockPrefixCallbackOp prefix_op(0);
        // topp
        int   end        = ((n + BLOCK_SIZE - 1) / BLOCK_SIZE) * BLOCK_SIZE;
        float prefix_sum = 0.f;
        for (int i = tid; i < end; i += BLOCK_SIZE) {
            float thread_count = (i < n) ? (float)sorted_logits[i] : 0.f;
            BlockScan(temp_storage).InclusiveSum(thread_count, prefix_sum, prefix_op);
            auto count = __syncthreads_count(prefix_sum > top_p);
            if (count != 0 || (i + BLOCK_SIZE >= end)) {
                if (tid == min(BLOCK_SIZE - count, BLOCK_SIZE - 1)) {
                    s_kept = min(i + 1, n);
                    s_sum  = prefix_sum;
                }
                break;
            }
        };
        __syncthreads();
    }

    if (min_p != 0.f) {
        n          = s_kept;
        sum_logits = s_sum;

        typedef cub::BlockScan<float, BLOCK_SIZE>  BlockScan;
        __shared__ typename BlockScan::TempStorage temp_storage;
        // Initialize running total
        BlockPrefixCallbackOp prefix_op(0);
        // minp
        float scaled_min_p = (float)sorted_logits[0] / (sum_logits + kEps) * min_p;
        int   end          = ((n + BLOCK_SIZE - 1) / BLOCK_SIZE) * BLOCK_SIZE;
        float prefix_sum   = 0.f;
        for (int i = tid; i < end; i += BLOCK_SIZE) {
            float thread_count = (i < n) ? (float)sorted_logits[i] / (sum_logits + kEps) : 0.f;
            BlockScan(temp_storage).ExclusiveSum(thread_count, prefix_sum, prefix_op);
            auto count = __syncthreads_count(thread_count < scaled_min_p);
            if (count != 0 || (i + BLOCK_SIZE >= end)) {
                if (tid == min(BLOCK_SIZE - count, BLOCK_SIZE - 1)) {
                    if (count == 0) {
                        ++i;
                        prefix_sum += thread_count;
                    }
                    s_kept = min(i, n);
                    s_sum *= prefix_sum;
                }
                break;
            }
        };
        __syncthreads();
    }

    if (top_p != 1.f || min_p != 0.f) {
        n          = s_kept;
        sum_logits = s_sum;
        if (tid == 0) {
            kept[bid] = n;
        }
        // norm
        for (int i = tid; i < n; i += BLOCK_SIZE) {
            sorted_logits[i] = (float)sorted_logits[i] / sum_logits;
        }
    }
}

template<typename T>
void invokeTopPMinPFilter(TopPMinPFilterParams& params, cudaStream_t stream)
{
    topPMinPFilter<T, 256><<<params.batch_size, 256, 0, stream>>>((T*)params.sorted_logits,
                                                                  params.sorted_indices,
                                                                  params.kept,
                                                                  params.vocab_size_padded,
                                                                  params.top_ps,
                                                                  params.min_ps);
}

template void invokeTopPMinPFilter<float>(TopPMinPFilterParams& params, cudaStream_t stream);

}  // namespace turbomind
