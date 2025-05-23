# PyTorchEngine Multithread

We have removed `thread_safe` mode from PytorchEngine since [PR2907](https://github.com/InternLM/lmdeploy/pull/2907). We encourage users to achieve high concurrency by using **service API** or **coroutines** whenever possible, for example:

```python
import asyncio
from lmdeploy import pipeline, PytorchEngineConfig

event_loop = asyncio.new_event_loop()
asyncio.set_event_loop(event_loop)

model_path = 'Llama-3.2-1B-Instruct'
pipe = pipeline(model_path, backend_config=PytorchEngineConfig())

async def _gather_output():
    tasks = [
        pipe.async_batch_infer('Hakuna Matata'),
        pipe.async_batch_infer('giraffes are heartless creatures'),
    ]
    return await asyncio.gather(*tasks)

output = asyncio.run(_gather_output())
print(output[0].text)
print(output[1].text)
```

If you do need multithreading, it would be easy to warp it like below:

```python
import threading
from queue import Queue
import asyncio
from lmdeploy import pipeline, PytorchEngineConfig

model_path = 'Llama-3.2-1B-Instruct'


async def _batch_infer(inque: Queue, outque: Queue, pipe):
    while True:
        if inque.empty():
            await asyncio.sleep(0)
            continue

        input = inque.get_nowait()
        output = await pipe.async_batch_infer(input)
        outque.put(output)


def server(inques, outques):
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    pipe = pipeline(model_path, backend_config=PytorchEngineConfig())
    for inque, outque in zip(inques, outques):
        event_loop.create_task(_batch_infer(inque, outque, pipe))
    event_loop.run_forever()

def client(inque, outque, message):
    inque.put(message)
    print(outque.get().text)


inques = [Queue(), Queue()]
outques = [Queue(), Queue()]

t_server = threading.Thread(target=server, args=(inques, outques))
t_client0 = threading.Thread(target=client, args=(inques[0], outques[0], 'Hakuna Matata'))
t_client1 = threading.Thread(target=client, args=(inques[1], outques[1], 'giraffes are heartless creatures'))

t_server.start()
t_client0.start()
t_client1.start()

t_client0.join()
t_client1.join()
```

> \[!WARNING\]
> This is NOT recommended, as multithreading introduces additional overhead, leading to unstable inference performance.
