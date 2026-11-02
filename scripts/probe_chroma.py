import sys, time
sys.path.insert(0, "src")
from pathlib import Path
import tempfile, shutil

tmp = Path(tempfile.mkdtemp())
from pka.config import Settings
from pka.core import vectorstore
from pka.core.embeddings import HashEmbeddings

def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

step("start")
s = Settings(model_provider="ollama", embedding_provider="hash",
             data_dir=tmp / "data", log_dir=tmp / "logs")
step("settings ok")
client = vectorstore.get_client(s)
step("client ok")
col = vectorstore.get_collection(s)
step("collection ok")
where = {"$and": [{"source": "x.md"}, {"version": "v1.0"}]}
step("calling col.get where=...")
existing = col.get(where=where, include=[])
step(f"col.get ok ids={existing.get('ids')}")
step("skip empty delete (fixed)")
chunks = [{"content": "Python 装饰器是包函数的函数", "source": "x.md", "version": "v1.0", "topic": "t", "page": 1}]
step("calling add_chunks...")
n = vectorstore.add_chunks(s, chunks)
step(f"add_chunks ok n={n}")
step("calling search...")
hits = vectorstore.search(s, "装饰器")
step(f"search ok hits={len(hits)}")
step("ALL OK")
shutil.rmtree(tmp, ignore_errors=True)
