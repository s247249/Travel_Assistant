"""Travel RAG assistant package.

No eager imports here: importing the package must stay cheap and must not
require optional heavy dependencies (chromadb, fastapi, ...). Import submodules
explicitly, e.g. `from reply_proj.backend.retriever import Retriever`.
"""


def main() -> None:
    print("Hello from reply-proj!")
