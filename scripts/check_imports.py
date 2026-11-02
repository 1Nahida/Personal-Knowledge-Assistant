"""导入与 API 兼容性检查（Phase 1b 冒烟）。"""
import sys

results = []


def check(label, fn):
    try:
        r = fn()
        results.append((True, label, str(r)[:100]))
    except Exception as e:
        results.append((False, label, f"{type(e).__name__}: {e}"))


check("chromadb", lambda: __import__("chromadb").__version__)
check("pymupdf(fitz)", lambda: __import__("fitz").__doc__)
check("python-docx", lambda: __import__("docx").__version__ if hasattr(__import__("docx"), "__version__") else "ok")
check("dotenv", lambda: __import__("dotenv").load_dotenv)
check("langchain_core.messages", lambda: __import__("langchain_core.messages", fromlist=["HumanMessage"]).HumanMessage)
check("langchain_openai.ChatOpenAI", lambda: __import__("langchain_openai", fromlist=["ChatOpenAI"]).ChatOpenAI)
check("langchain_community.chat_models.ChatOllama",
      lambda: __import__("langchain_community.chat_models", fromlist=["ChatOllama"]).ChatOllama)
check("langchain_community.embeddings.OllamaEmbeddings",
      lambda: __import__("langchain_community.embeddings", fromlist=["OllamaEmbeddings"]).OllamaEmbeddings)
check("langchain_classic.chat_models.ChatOllama",
      lambda: __import__("langchain_classic.chat_models", fromlist=["ChatOllama"]).ChatOllama)

for ok, label, detail in results:
    print(("OK   " if ok else "FAIL ") + label + " -> " + detail)

sys.exit(0 if all(r[0] for r in results) else 1)