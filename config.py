"""本地文学创作 AI 的全局配置。

建库脚本（1_build_db.py）和对话脚本（2_chat.py）都会 import 这个文件，
保证两侧使用的路径、模型、集合名完全一致——这是 RAG 能检索到东西的关键。
"""
import os

# ================= 1. 代理修复（关键） =================
# Windows 上如果装了 Clash / v2ray / 系统代理，localhost 请求可能被拦截，
# 导致连接 Ollama 失败（旧代码就是栽在这里）。这里彻底清空代理并放行本机地址。
for var in ("http_proxy", "https_proxy", "all_proxy",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(var, None)
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

# ================= 2. Ollama 连接 =================
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
os.environ.setdefault("OLLAMA_HOST", OLLAMA_BASE_URL)

# ================= 3. 模型 =================
EMBEDDING_MODEL = "nomic-embed-text"   # 向量化模型（把文本切成片段转成向量）
LLM_MODEL = "qwen3:8b"               # 对话 / 创作模型

# ================= 4. 路径 =================
# 基于本文件所在目录，而不是“当前工作目录”，所以从哪儿运行都一样。
_BASE = os.path.dirname(os.path.abspath(__file__))
NOVELS_DIR = os.path.join(_BASE, "novels")   # 放 .txt 小说的文件夹
DB_DIR = os.path.join(_BASE, "chroma_db")    # 向量数据库保存位置
COLLECTION_NAME = "novel_collection"         # 集合名（建库与聊天必须一致）

# ================= 5. 切分 & 检索参数 =================
CHUNK_SIZE = 800          # 每个片段的字符数（中文小说建议 600~1000）
CHUNK_OVERLAP = 120       # 相邻片段重叠字符数，避免一句话被拦腰切断
RETRIEVE_K = 4            # 每次检索返回最相关的片段数
EMBED_BATCH = 200         # 每批向量化多少片段（分批是为了显示进度、控制内存）

# ================= 6. 对话生成参数 =================
LLM_NUM_CTX = 8192        # 上下文长度（放得下检索片段 + 你的问题）
STORY_NUM_CTX = 16384     # 三场短篇：开场、完整已接受场景、场景卡与审核上下文
LLM_TEMPERATURE = 0.8     # 温度：文学创作适当调高，更有想象力；想更严谨可降到 0.3
LLM_REPEAT_PENALTY = 1.2  # 重复惩罚（>1 抑制模型复读同一句，防互动小说车轱辘话）
