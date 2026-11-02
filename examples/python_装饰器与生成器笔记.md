# Python 装饰器与生成器学习笔记

## 什么是装饰器

装饰器（Decorator）本质是一个**接受函数作为参数、并返回新函数的高阶函数**，语法上写作 `@decorator`。
它的作用是在**不修改原函数代码**的前提下，为函数增加额外行为（日志、计时、权限校验、缓存等）。

最简实现：

```python
import functools

def my_decorator(func):
    @functools.wraps(func)  # 保留原函数的 __name__、__doc__
    def wrapper(*args, **kwargs):
        print(">>> before")
        result = func(*args, **kwargs)
        print("<<< after")
        return result
    return wrapper

@my_decorator
def hello(name):
    """打个招呼"""
    print(f"hello, {name}")
```

`functools.wraps` 很重要：没有它，被装饰函数的 `__name__` 会变成 `wrapper`，影响调试与文档展示。

## 带参数的装饰器

带参数的装饰器需要**三层嵌套**：参数层 -> 装饰器层 -> wrapper 层。

```python
def repeat(n):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for _ in range(n):
                func(*args, **kwargs)
        return wrapper
    return decorator

@repeat(3)
def show():
    print("again")
```

## 类作为装饰器

类装饰器要求实现 `__call__`，适合需要保存状态的场景（如缓存、重试计数）。

```python
class CountCalls:
    def __init__(self, func):
        self.func = func
        self.count = 0

    def __call__(self, *args, **kwargs):
        self.count += 1
        print(f"{self.func.__name__} 第 {self.count} 次调用")
        return self.func(*args, **kwargs)

@CountCalls
def ping():
    return "pong"
```

## 常见标准库装饰器

- `@staticmethod`：静态方法，不接收 self。
- `@classmethod`：类方法，接收 cls，常用于工厂方法。
- `@property`：把方法变成属性访问。
- `@functools.lru_cache(maxsize=128)`：函数记忆化缓存，纯函数提速利器。
- `@abc.abstractmethod`：抽象方法，强制子类实现。

## 生成器（Generator）

生成器是**惰性求值**的迭代器，用 `yield` 暂停/恢复函数执行，内存友好，适合处理无限序列或大文件。

```python
def count_up(start, stop):
    n = start
    while n < stop:
        yield n      # 暂停，产出 n
        n += 1

for i in count_up(1, 5):
    print(i)

# 生成器表达式
squares = (x * x for x in range(10))
```

生成器与装饰器经常组合使用：用装饰器给生成器函数增加耗时统计或重试逻辑。
