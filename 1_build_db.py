"""第一步：把 novels/ 目录下的小说切分成片段，做成向量数据库。

用法：
    python 1_build_db.py              # 增量建库（自动跳过已入库的书）
    python 1_build_db.py --rebuild    # 清空数据库后全部重建
    python 1_build_db.py --book 三体   # 只处理书名包含“三体”的书（建议先用一本测试）

提示：50MB 左右的小说全集，首次向量化可能要几分钟到十几分钟，
     建议先 `--book 某本` 跑一本验证没问题，再全量跑。
"""
import os
import time
import argparse

import config
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma


def detect_encoding(path):
    """依次尝试多种编码，返回第一个能严格解码成功的（中文 txt 常见 UTF-8 / GBK）。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "utf-16"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"  # 兜底


def read_novel(path):
    """读取小说文本并做轻度清洗：统一换行、压缩连续空行、保留段落结构。"""
    enc = detect_encoding(path)
    with open(path, "r", encoding=enc, errors="replace") as f:
        text = f.read()

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]

    out, blank = [], 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank <= 1:
                out.append("")   # 保留单个空行作段落分隔，多余的丢弃
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out)


def make_splitter():
    """针对中文小说的切分器：优先按段落/句子边界切，避免切断语义。"""
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", "、", " ", ""],
        length_function=len,   # len() 对中文字符按 1 计数，正合适
        is_separator_regex=False,
    )


def build(rebuild=False, book_filter=None):
    if not os.path.isdir(config.NOVELS_DIR):
        os.makedirs(config.NOVELS_DIR)
        print(f"⚠️  未找到 {config.NOVELS_DIR}，已自动创建。请把 .txt 小说放进去后重新运行。")
        return

    # 与 2_chat.py 使用完全一致的 embedding 模型与集合名
    embeddings = OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )
    vectorstore = Chroma(
        collection_name=config.COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=config.DB_DIR,
    )

    if rebuild:
        vectorstore.reset_collection()
        print("🧹 已清空旧数据库，准备重建。")

    files = [f for f in os.listdir(config.NOVELS_DIR) if f.lower().endswith(".txt")]
    if book_filter:
        files = [f for f in files if book_filter in f]
    files = sorted(files)

    if not files:
        print("📭 没有找到要处理的 .txt 文件。")
        return

    print(f"📚 扫描到 {len(files)} 本小说。")
    splitter = make_splitter()
    new_count = 0
    t_start = time.time()

    for idx, filename in enumerate(files, 1):
        book_name = os.path.splitext(filename)[0]

        # 增量判断：库里是否已有这本书（按 book_name 精确匹配）
        try:
            existing = vectorstore.get(where={"book_name": book_name}, limit=1)
            if existing.get("ids"):
                print(f"  [{idx}/{len(files)}] 跳过（已入库）: {filename}")
                continue
        except Exception:
            pass  # 查询失败就按“未入库”处理，直接重入

        path = os.path.join(config.NOVELS_DIR, filename)
        print(f"  [{idx}/{len(files)}] 读取: {filename} ...")
        try:
            text = read_novel(path)
        except Exception as e:
            print(f"    ❌ 读取失败: {e}")
            continue

        chunks = splitter.split_text(text)
        print(f"    → 切分成 {len(chunks)} 个片段，开始向量化...")

        t0 = time.time()
        total_added = 0
        for i in range(0, len(chunks), config.EMBED_BATCH):
            batch = chunks[i:i + config.EMBED_BATCH]
            docs = [
                Document(
                    page_content=t,
                    metadata={
                        "source": filename,   # 原始文件名
                        "book_name": book_name,  # 去掉扩展名，便于按书名过滤
                        "chunk_index": i + j,
                    },
                )
                for j, t in enumerate(batch)
            ]
            vectorstore.add_documents(docs)
            total_added += len(docs)
            done = min(i + config.EMBED_BATCH, len(chunks))
            el = time.time() - t0
            print(f"    ⏳ {done}/{len(chunks)}  已用时 {el:.0f}s", end="\r")

        print(f"\n    ✅ 《{book_name}》入库完成，共 {total_added} 个片段（用时 {time.time()-t0:.0f}s）。")
        new_count += 1

    total_el = time.time() - t_start
    print(f"\n🎉 全部完成！本次新增 {new_count} 本书，总用时 {total_el:.0f}s。")
    print(f"📦 数据库位于: {config.DB_DIR}")
    print("👉 下一步：运行  python 2_chat.py  开始对话。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="构建小说向量数据库")
    ap.add_argument("--rebuild", action="store_true", help="清空数据库后重建")
    ap.add_argument("--book", default=None, help="只处理书名包含该关键字的书")
    args = ap.parse_args()
    build(rebuild=args.rebuild, book_filter=args.book)
