# Python 异步编程新语法（async/await 进阶）

## 背景

在 `async/await` 出现之前，Python 的并发 IO 主要依赖**回调函数（callback）**与线程池。
回调方式在层级加深时会产生“回调地狱”，可读性差；线程池则受 GIL 限制，IO 密集场景下
需要大量线程，上下文切换开销大。

Python 3.5 引入 `async/await`（PEP 492），用**协程（coroutine）**重写异步 IO：

```python
import asyncio

async def fetch(url: str) -> str:
    await asyncio.sleep(1)  # 模拟网络 IO
    return f"body of {url}"

async def main():
    tasks = [asyncio.create_task(fetch(u)) for u in ("a", "b", "c")]
    results = await asyncio.gather(*tasks)
    print(results)

asyncio.run(main())
```

## 为什么 async/await 优于回调

1. **线性代码**：`await` 让异步代码读起来像同步代码，没有回调嵌套。
2. **任务并发**：`asyncio.gather` / `asyncio.wait` 显式表达并发关系。
3. **异常处理**：可以用普通 try/except 捕获，回调时代需要在每个回调里处理。
4. **与回调互操作**：`asyncio.to_thread`（3.9+）、`loop.run_in_executor` 可桥接阻塞函数。

## 稳定性与社区成熟度

- `async/await` 自 Python 3.5（2015）引入，3.10/3.11 持续增强（TaskGroup、
  asyncio.timeout 等），已被 FastAPI、aiohttp、httpx 等主流框架全面采用，
  **经过大规模生产验证**，是 Python 异步 IO 的事实标准。
- 旧回调方式（如早期的 Tornado 回调风格、twisted 的 deferred）仍存在于遗留系统，
  但社区已停止在回调风格上开发新特性。

## 性能

- 单事件循环即可驱动数万并发连接（对比线程池数百线程的切换开销）。
- 代价：所有协程跑在单线程，**CPU 密集任务必须放到线程池/进程池**，
  否则会阻塞事件循环。
- 资源消耗：协程帧对象约为 KB 级，远小于线程栈（默认 MB 级）。
