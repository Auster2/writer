"""第二步：本地文学创作助手（RAG 对话）。

用法：
    python 2_chat.py

进入后直接输入问题即可。支持命令：
    /books            列出知识库里的所有书
    /book 三体         只从书名包含“三体”的书里检索
    /all              恢复为在所有书里检索
    /sources          显示 / 隐藏检索到的原文出处
    /exit 或 /quit    退出
"""
import config
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """你是一位资深的文学评论家与小说创作者，精通中文文学分析、仿写与创作辅助。

规则：
1. 优先依据下方【参考资料】回答；若资料中没有相关信息，如实说明“知识库中未找到相关内容”，不要编造。
2. 做文学分析或回答作品问题时，尽量贴合原著的语气与风格，并注明信息出自哪本书。
3. 用户若要求你创作 / 仿写，可借鉴参考资料的文风与设定，允许合理发挥。
4. 回答要有深度、有细节、条理清晰。
"""

PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("system", "【参考资料】\n{context}"),
    ("human", "{question}"),
])


def list_books(vectorstore):
    """返回知识库里所有不重复的书名。

    分页读取：一次取全部 3 万+ 条会触发 SQLite“too many SQL variables”报错，
    所以用 limit + offset 分批拿。
    """
    names = set()
    offset, batch = 0, 500
    try:
        while True:
            res = vectorstore.get(include=["metadatas"], limit=batch, offset=offset)
            metas = res.get("metadatas") or []
            if not metas:
                break
            for m in metas:
                if m and m.get("book_name"):
                    names.add(m["book_name"])
            if len(metas) < batch:
                break
            offset += batch
    except Exception as e:
        print(f"⚠️  读取书名列表出错：{e}")
        return []
    return sorted(names)


def build_retriever(vectorstore, target_books):
    kw = {"k": config.RETRIEVE_K}
    if target_books:
        kw["filter"] = {"book_name": {"$in": target_books}}
    return vectorstore.as_retriever(search_kwargs=kw)


def main():
    print("⏳ 正在加载向量数据库与模型（首次可能需要十几秒）...")
    embeddings = OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )
    vectorstore = Chroma(
        collection_name=config.COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=config.DB_DIR,
    )
    llm = ChatOllama(
        model=config.LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=config.LLM_TEMPERATURE,
        num_ctx=config.LLM_NUM_CTX,
    )

    all_books = list_books(vectorstore)
    if not all_books:
        print("⚠️  知识库是空的！请先运行  python 1_build_db.py  建库。")
    else:
        print(f"📚 知识库共有 {len(all_books)} 本书：{', '.join(all_books)}")
    print("✅ 就绪！输入问题开始，输入 /help 查看命令。\n")

    target_books = []      # 空列表 = 全部书
    show_sources = True

    while True:
        try:
            q = input("🙋 你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break
        if not q:
            continue

        if q in ("/exit", "/quit", "/q"):
            print("👋 再见！")
            break
        if q == "/help":
            print("命令：/books · /book 书名 · /all · /sources · /exit")
            continue
        if q == "/books":
            print(f"📚 库内书籍：{', '.join(all_books) if all_books else '（空）'}")
            continue
        if q == "/all":
            target_books = []
            print("🔍 已恢复：在所有小说中检索。")
            continue
        if q == "/sources":
            show_sources = not show_sources
            print(f"📚 出处显示：{'开' if show_sources else '关'}")
            continue
        if q.startswith("/book"):
            keyword = q[len("/book"):].strip()
            if not keyword:
                target_books = []
                print("📌 已清除限定，恢复为全部书。")
                continue
            matches = [b for b in all_books if keyword in b]
            if not matches:
                print(f"⚠️  没找到书名包含“{keyword}”的书。可用：{', '.join(all_books) if all_books else '（空）'}")
                continue
            target_books = matches
            print(f"📌 已限定检索范围：{', '.join(matches)}")
            continue

        # ---- 检索 ----
        retriever = build_retriever(vectorstore, target_books)
        docs = retriever.invoke(q)
        if not docs:
            print("❌ 未检索到相关内容，换个问法试试。\n")
            continue

        context = "\n\n".join(
            f"[片段 {i+1} · 出自《{d.metadata.get('book_name', '?')}》]\n{d.page_content}"
            for i, d in enumerate(docs)
        )
        if show_sources:
            books = sorted({d.metadata.get("book_name", "?") for d in docs})
            print(f"📚 参考：{', '.join(books)}")

        # ---- 生成（流式输出）----
        print("🤖 助手：", end="", flush=True)
        try:
            messages = PROMPT_TEMPLATE.format_messages(context=context, question=q)
            for chunk in llm.stream(messages):
                content = chunk.content
                if content:
                    print(content, end="", flush=True)
        except Exception as e:
            print(f"\n⚠️ 生成失败：{e}")
        print("\n")


if __name__ == "__main__":
    main()
