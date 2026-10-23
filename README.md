# 本地文学创作 AI（Ollama + RAG）

一个跑在本机的文学创作 / 小说问答助手：把你的小说 `.txt` 切分入库，之后用
`qwen3:8b` 结合检索到的原文片段来回答问题、分析文风、辅助仿写。

## 环境要求

- 已安装 [Ollama](https://ollama.com/)，并且拉取了两个模型：

  ```bash
  ollama pull nomic-embed-text   # 向量化模型
  ollama pull qwen3:8b         # 对话模型
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

## 第四版可玩公路冒险

已提供独立的 Node.js + TypeScript 浏览器版本：[启动与玩法说明](4_roadtrip/README.md)。内置世界观为[雨季旧公路](4_roadtrip/presets/世界观.md)，可先在离线示例模式玩完三站，再在界面里配置 Ollama 地址和模型。

```powershell
cd 4_roadtrip
npm start
```

需要 Node.js 24+，浏览器打开 `http://127.0.0.1:4317`。存档、个人连接配置与运行产物均忽略。设计方案见 [4_roadtrip.md](4_roadtrip.md)。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `config.py` | 全局配置：代理清理、模型名、路径、切分/检索参数 |
| `1_build_db.py` | 建库脚本（切分 + 向量化 + 入库） |
| `2_chat.py` | 交互式 RAG 对话脚本 |
| `3_story.py` | 三场短篇引擎（规划、整场写作、审核、事实记忆） |
| [第四版公路冒险设计](4_roadtrip.md) | Node.js 与浏览器界面方案；可玩版本见 `4_roadtrip/` |
| `story_state.json` | 角色配置：标题 + 人物卡 + 开场（只读，运行中不改动） |
| `runs/` | 每次运行一个时间戳目录，内含 `state.json` + `manuscript.txt` |
| `novels/` | 放小说 `.txt` 的地方 |
| `chroma_db/` | 向量数据库（自动生成） |

## 三场短篇引擎（`3_story.py`）

使用现有 `story_state.json` 中的人物和开场，一次完成三场、有结尾的短篇。
只依赖 Python 标准库和本机 Ollama，不需要先建向量库，也不需要安装 LangChain。
前面的依赖用于建库、问答脚本。

```bash
# Ollama 服务启动且模型已下载后，真实生成
python 3_story.py

# 指定模型或输出目录；新建输出目录必须不存在
python 3_story.py --model qwen3:8b --output runs/my_story

# 网络中断或审核未通过后，从最后一场已接受正文续跑
python 3_story.py --resume runs/my_story
```

流程：

1. 根据开场确定核心矛盾、具体结局与恰好三张场景卡。
2. 按卡写完整场景，允许多人自然互动，第三人称叙述中的对白可使用“我”“你”。
3. 独立调用编辑审核本场变化、结束条件、事实连续性和结尾收束，并给出依据。
4. 未通过时携带草稿和修改意见重写，默认最多重写两次（`--max-revisions`）。
5. 通过后才提交正文和结构化记忆：已发生事实、关系现状、未解决事项。
6. 第三场通过且未解决事项为空，才标记 `complete`。

审核仍依赖模型判断，结构校验通过不等于文学质量保证。读者可检查各场审核依据。
三场短篇默认上下文为16384 token，传入开场与全部已接受场景，不使用旧版截断摘要。
此实现面向三场短篇，尚非长篇记忆系统。

每次运行保存在 `runs/<时间戳>/`：

| 文件 | 内容 |
| --- | --- |
| `plan.json` | 故事方向、结局、场景卡、初始事实 |
| `state.json` | 原人物与开场快照、已通过场景、当前事实、运行状态 |
| `manuscript.txt` | 原始开场 + 已通过场景，拒绝的草稿不会混入 |
| `*_raw_*.txt` | 每次调用的原始回答，包括格式不合格的回答 |
| `*_review.json` | 各版本审核结果与依据 |

请求失败会停止并保留已提交进度；格式不合格会尝试修复一次。续跑从首个未接受场景重新写作，
旧草稿与审核日志保留。配置文件保持只读。已完成的运行再次续跑不会追加第四场。
新版不能续跑旧版角色轮换引擎的状态文件。

### 已完成示例与离线回放

`examples/completed_run/manuscript.txt` 是现有人物与开场的三场短篇示例。
故事以温水从“包办”转为“协助”为主线，小鞠投稿并亲口道谢，烧盐重新训练，
八奈见自费分享甜点并坦承失落，保住三千日元部费。

**示例正文由 Codex 预写，审核记录为人工编排的回放数据。它验证程序流程，
不代表本机 Ollama 已生成或审核成功。** 实作时本机11434端口未提供服务。
`state.json` 中的 `source: replay` 可用于辨别；示例和真实模型后端不能混用续跑。

```bash
# 输出目录需不存在，可换成自己的目录名
python 3_story.py --replay examples/three_scene_replay.json --output runs/offline_demo

# 运行流程回归测试，不需Ollama
python -m unittest discover -s tests -v
```

## 常见问题

- **连接 Ollama 失败 / 端口报错**：通常是本地代理（Clash、v2ray）拦了 localhost。
  `config.py` 已自动清空代理并放行 `127.0.0.1`，一般直接就能连上。
- **首次建库很慢**：50MB 小说全集在 CPU 上向量化可能要几分钟到十几分钟，属正常；
  先用 `--book 某本` 跑一本验证。
- **想改文风/更严谨**：编辑 `config.py` 里的 `LLM_TEMPERATURE`（0.8 更发散，0.3 更严谨）。
- **检索片段太短/太长**：调 `config.py` 里的 `CHUNK_SIZE` / `CHUNK_OVERLAP`，改完 `--rebuild` 重建。
