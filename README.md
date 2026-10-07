# 本地文学创作 AI（Ollama + RAG）

一个跑在本机的文学创作 / 小说问答助手：把你的小说 `.txt` 切分入库，之后用
`qwen2.5:7b` 结合检索到的原文片段来回答问题、分析文风、辅助仿写。

## 环境要求

- 已安装 [Ollama](https://ollama.com/)，并且拉取了两个模型：

  ```bash
  ollama pull nomic-embed-text   # 向量化模型
  ollama pull qwen2.5:7b         # 对话模型
  ```

- Python 3.10+，已安装依赖：

  ```bash
  pip install langchain langchain-ollama langchain-chroma langchain-text-splitters
  ```

## 使用步骤

1. 把小说 `.txt` 放进 `novels/` 文件夹（已放了 8 本示例）。
2. 建库（把小说切成片段 → 转成向量 → 存入 Chroma 数据库）：

   ```bash
   # 建议先只跑一本验证（书名含“三体”的书）
   python 1_build_db.py --book 三体

   # 全部入库（增量，自动跳过已入库的书）
   python 1_build_db.py

   # 想清空重来
   python 1_build_db.py --rebuild
   ```

3. 开始对话：

   ```bash
   python 2_chat.py
   ```

   进入后直接提问；支持命令：

   | 命令 | 作用 |
   | --- | --- |
   | `/books` | 列出库内所有书 |
   | `/book 三体` | 只从书名包含“三体”的书里检索 |
   | `/all` | 恢复为全部书 |
   | `/sources` | 显示/隐藏检索到的原文出处 |
   | `/exit` | 退出 |

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `config.py` | 全局配置：代理清理、模型名、路径、切分/检索参数 |
| `1_build_db.py` | 建库脚本（切分 + 向量化 + 入库） |
| `2_chat.py` | 交互式 RAG 对话脚本 |
| `3_story.py` | 多角色回合制互动小说引擎（导演 + 旁白模式） |
| `story_state.json` | 角色配置：标题 + 人物卡 + 开场（只读，运行中不改动） |
| `runs/` | 每次运行一个时间戳目录，内含 `state.json` + `manuscript.txt` |
| `novels/` | 放小说 `.txt` 的地方 |
| `chroma_db/` | 向量数据库（自动生成） |

## 多角色互动小说引擎（`3_story.py`）

不是问答，而是「导演模式」自动写小说：给每个角色一张人物卡（性格 + 目标），
引擎每轮让一个角色用第三人称旁白说/做一小段，并让模型决定下一个出场角色，循环推进。

1. 编辑 `story_state.json`，改 `characters`（名字/性格/目标）和开场 `history`。
2. 运行：

   ```bash
   python 3_story.py
   ```

3. 回车让故事继续；可用命令：

   | 命令 | 作用 |
   | --- | --- |
   | （回车） | 继续下一段，下一个角色由模型决定 |
   | `/next 林岚` | 强制指定下一个出场角色 |
   | `/scene 描述` | 以「旁白」身份插入外部事件（你当主持人） |
   | `/characters` | 查看人物卡 |
   | `/summary` | 查看剧情摘要与进度 |
   | `/exit` | 退出（自动保存） |

**内部逻辑**：选角色 → 组装提示词（人物卡 + 剧情摘要 + 最近正文）→ 模型先以「旁白」推进剧情，
再让指定角色以第三人称反应，输出 `{"narrator":"…","character":"…","text":"…","next":"…"}` →
追加进 `manuscript`（正文，永久保留不删）→ 按 `next` 继续。`next` 非法或重复时自动回退到轮询下一位。
正文超过 7000 字后，旧内容会被压缩成「叙事体摘要」喂给模型，正文本身仍完整保存在
`runs/<时间戳>/manuscript.txt`（每次保存自动导出）。角色配置 `story_state.json` 只读，
运行进度写进 `runs/<时间戳>/state.json`，方便多次运行对比测试，避免撑爆上下文（`num_ctx=8192`）。

## 常见问题

- **连接 Ollama 失败 / 端口报错**：通常是本地代理（Clash、v2ray）拦了 localhost。
  `config.py` 已自动清空代理并放行 `127.0.0.1`，一般直接就能连上。
- **首次建库很慢**：50MB 小说全集在 CPU 上向量化可能要几分钟到十几分钟，属正常；
  先用 `--book 某本` 跑一本验证。
- **想改文风/更严谨**：编辑 `config.py` 里的 `LLM_TEMPERATURE`（0.8 更发散，0.3 更严谨）。
- **检索片段太短/太长**：调 `config.py` 里的 `CHUNK_SIZE` / `CHUNK_OVERLAP`，改完 `--rebuild` 重建。
