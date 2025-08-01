# Copyright (c) OpenMMLab. All rights reserved.
import asyncio
import os
import random

from lmdeploy import Tokenizer
from lmdeploy.archs import get_model_arch
from lmdeploy.messages import GenerationConfig, TurbomindEngineConfig
from lmdeploy.model import ChatTemplateConfig, best_match_model
from lmdeploy.tokenizer import DetokenizeState
from lmdeploy.utils import _get_and_verify_max_len, _stop_words, get_hf_gen_cfg

log_level = 'ERROR'
if os.getenv('TM_LOG_LEVEL') is None:
    os.environ['TM_LOG_LEVEL'] = log_level
    from lmdeploy.utils import get_logger
    logger = get_logger('lmdeploy')
    logger.setLevel(log_level)


def input_prompt(model_name):
    """Input a prompt in the consolo interface."""
    if model_name == 'codellama':
        print('\nenter !! to end the input >>>\n', end='')
        sentinel = '!!'
    else:
        print('\ndouble enter to end input >>> ', end='')
        sentinel = ''  # ends when this string is seen
    return '\n'.join(iter(input, sentinel))


async def async_infer(generator, session_id, input_ids, gen_config, sequence_start, step, stream_output, tokenizer,
                      state):
    token_ids = input_ids.copy()
    prev_len = 0
    async for output in generator.async_stream_infer(session_id=session_id,
                                                     input_ids=input_ids,
                                                     gen_config=gen_config,
                                                     sequence_start=sequence_start,
                                                     sequence_end=False,
                                                     step=step,
                                                     stream_output=stream_output):
        tokens = output.num_token
        if tokens > prev_len:
            token_ids += output.token_ids[prev_len - tokens:]
            response, state = tokenizer.detokenize_incrementally(token_ids, state=state)
            prev_len = tokens
            print(response, end='', flush=True)
    return tokens


def main(model_path: str,
         session_id: int = 1,
         top_k: float = 40,
         top_p: float = 0.8,
         temperature: float = 0.8,
         repetition_penalty: float = 1.0,
         cap: str = 'chat',
         dtype: str = 'auto',
         tp: int = 1,
         model_format: str = None,
         quant_policy: int = 0,
         cache_max_entry_count: float = 0.8,
         cache_block_seq_len: int = 64,
         rope_scaling_factor: float = 0.0,
         enable_prefix_caching: bool = False,
         session_len: int = None,
         stream_output: bool = True,
         request_output_len: int = 1024,
         chat_template_config: ChatTemplateConfig = None,
         communicator: str = 'nccl',
         **kwargs):
    """An example to perform model inference through the command line
    interface.

    Args:
        model_path (str): the path of the deployed model
        session_id (int): the identical id of a session
        top_k (int): sampling top k.
        top_p (int): sampling top p.
        temperature (float): sampling temperature.
        repetition_penalty (float): parameter to penalize repetition
        cap (str): the capability of a model. For example, codellama has the
            ability among ['completion', 'infilling', 'chat', 'python']
        dtype (str): data type for model weights and activations. It can be
            one of the following values, ['auto', 'float16', 'bfloat16']
            The `auto` option will use FP16 precision for FP32 and FP16
            models, and BF16 precision for BF16 models.
        tp (int): GPU number used in tensor parallelism
        model_format (str): the layout of the deployed model. It can be one
            of the following values [hf, llama, awq]
        quant_policy (int): default to 0. When k/v is quantized into 4 or 8
            bit, set it to 4 or 8, respectively
        cache_max_entry_count (float): the percentage of gpu memory occupied
            by the k/v cache.
        cache_block_seq_len (int): the length of the token sequence in a k/v
            block, default to 64
        rope_scaling_factor (float): scaling factor used for dynamic ntk,
            default to 0. TurboMind follows the implementation of transformer
            LlamaAttention
        enable_prefix_caching (bool): whether enable prefix caching
        session_len (int): the length input output tokens
        stream_output (bool): indicator for streaming output or not
        request_output_len (int): output token nums
        chat_template_config (ChatTemplateConfig): chat template config
        kwargs (dict): unused args
    """

    # chat template
    chat_template_name = best_match_model(model_path)
    if chat_template_config is None:
        chat_template_config = ChatTemplateConfig(chat_template_name)
    elif chat_template_config.model_name is None:
        chat_template_config.model_name = chat_template_name
    if chat_template_config.capability is None:
        chat_template_config.capability = cap
    print('chat_template_config:\n', chat_template_config, sep='', flush=True)
    model = chat_template_config.chat_template

    _, model_config = get_model_arch(model_path)
    session_len = _get_and_verify_max_len(model_config, session_len)

    # engine
    engine_cfg = TurbomindEngineConfig(max_batch_size=1,
                                       model_format=model_format,
                                       session_len=session_len,
                                       cache_max_entry_count=cache_max_entry_count,
                                       cache_block_seq_len=cache_block_seq_len,
                                       enable_prefix_caching=enable_prefix_caching,
                                       quant_policy=quant_policy,
                                       rope_scaling_factor=rope_scaling_factor,
                                       dtype=dtype,
                                       tp=tp,
                                       communicator=communicator)
    print('engine_cfg:\n', engine_cfg, sep='', flush=True)
    tokenizer = Tokenizer(model_path)
    from lmdeploy import turbomind as tm
    tm_model = tm.TurboMind.from_pretrained(model_path, tokenizer=tokenizer, engine_config=engine_cfg)
    generator = tm_model.create_instance()

    # generation config
    gen_config = GenerationConfig(max_new_tokens=request_output_len,
                                  top_k=top_k,
                                  top_p=top_p,
                                  temperature=temperature,
                                  repetition_penalty=repetition_penalty)
    stop_words = _stop_words(model.stop_words, tokenizer)
    gen_config.convert_stop_bad_words_to_ids(tokenizer)
    if stop_words is not None:
        stop_words = stop_words[0][0].tolist()
    if gen_config.stop_token_ids is None:
        gen_config.stop_token_ids = stop_words
    hf_gen_cfg = get_hf_gen_cfg(model_path)
    gen_config.update_from_hf_gen_cfg(hf_gen_cfg, tokenizer.eos_token_id)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    nth_round = 1
    step = 0
    seed = random.getrandbits(64)
    while True:
        prompt = input_prompt(chat_template_name)
        if prompt == 'exit':
            exit(0)
        elif prompt == 'end':
            loop.run_until_complete(generator.async_end(session_id))
            nth_round = 1
            step = 0
            seed = random.getrandbits(64)
        else:
            prompt = model.get_prompt(prompt, nth_round == 1)
            input_ids = tokenizer.encode(prompt, nth_round == 1)
            gen_config.random_seed = seed

            if model.capability == 'chat':
                sequence_start = (nth_round == 1)
            else:
                sequence_start = True
                step = 0

            if step + len(input_ids) + request_output_len >= tm_model.session_len:
                print('WARNING: exceed session max length.'
                      ' Please end the session.')
                continue

            print(f'{prompt}', end='', flush=True)
            state = DetokenizeState(len(input_ids))

            coro = async_infer(generator, session_id, input_ids, gen_config, sequence_start, step, stream_output,
                               tokenizer, state)
            tokens = loop.run_until_complete(coro)

            # update step
            step += len(input_ids) + tokens
            print()

            nth_round += 1


if __name__ == '__main__':
    import fire

    fire.Fire(main)
