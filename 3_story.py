"""第三步：多角色回合制互动小说引擎（导演 + 旁白模式）。

循环逻辑：
    选一个角色 → 组装提示词（人物卡 + 剧情摘要 + 最近正文）
    → 模型先以「旁白」推进剧情（时间/场景/新事件），再让指定角色以第三人称反应
    → 追加进正文 manuscript → 判断下一个角色 → 回到开头。

角色配置写在 story_state.json（只读，运行中不会被改动）。每次运行会新建一个
按日期时间命名的目录 runs/YYYYMMDD_HHMMSS/，里面放：
    state.json     本次运行的进度（正文 / 摘要 / 当前角色）
    manuscript.txt 小说正文（可直接读）

用法：
    python 3_story.py

命令：
    （回车）           继续下一段（下一角色由模型决定）
    /next 名字         强制指定下一个出场角色
    /scene 描述        以「旁白」身份插入外部事件（你当主持人推进剧情）
    /characters        查看人物卡
    /manuscript        查看当前完整正文
    /save              保存（每轮自动保存，并导出 manuscript.txt）
    /exit              退出
"""
import datetime
import json
import os
import re

import config
from langchain_ollama import ChatOllama

# ================= 路径 =================
_BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_BASE, "story_state.json")   # 角色配置（只读，永不改动）
RUNS_DIR = os.path.join(_BASE, "runs")                  # 每次运行一个时间戳子目录

# ================= 正文 / 上下文参数 =================
RECENT_CHARS = 2000       # 每次喂给模型的「最近正文」字符数
SUMMARIZE_AT_CHARS = 7000 # 未压缩正文超过此长度时触发压缩（正文本身不删）

# ================= 提示词 =================
DIRECTOR_SYSTEM = """你是一部互动小说的导演兼旁白。每轮你要做两件事：
1) 以「旁白」身份推进剧情——时间的流逝、场景的转换、新的突发事件、或角色间暗流的变化，让故事往前走，绝不停在原地复读；
2) 再让指定角色「X」对这一新局面做出反应——只写 X 这一个人的动作、神态与对话。

硬性规则：
1. 全程第三人称叙述（一律用角色名，禁止「我」「你」这种第一/第二人称）。
2. 只输出一个 JSON 对象，不要任何多余文字，格式：
   {"narrator":"旁白：推进剧情的一两句话","character":"当前角色名","text":"该角色第三人称的动作与对话","next":"下一个出场角色名"}
3. character 必须是本轮指定的角色；next 只能是【可选角色】里列出的名字，严禁引入新角色。
4. 角色名必须与人物卡一字不差，不要写错字、不要夹英文或拼音。
5. text 只写 character 这一个人，150~250 字，贴合其性格、目标与人际关系。
6. narrator 是剧情推进器，必须让故事「往前跳一步」，至少做到其一：
   - 时间明确前进（如「第二天一早」「半小时后」「放学铃响」）；
   - 场景切换（如「众人转场到图书馆」「门被推开」）；
   - 出现新事件或新信息（电话/消息/意外/有人闯入/某个角色抛出新提议）。
   若最近剧情还停在原地，narrator 要主动制造转折。禁止写「空气安静了」「众人沉默」「一时无言」这类不推进的静态句子。
7. next 不能等于 character，别让同一角色连续出场两次。"""

SUMMARY_SYSTEM = """把下面【既有摘要】和【新增正文】合并成一段连贯的第三人称小说叙事。
要求：按时间顺序复述关键情节，保留重要对话的要点、人物的关键行动、伏笔与悬念，
文笔流畅、读起来像小说正文（而不是简介或分点提纲），篇幅可到 500~800 字。只输出正文。"""


def _default_config():
    return {
        "title": "雨夜凶宅",
        "characters": [
            {"name": "林岚", "persona": "冷静理性的私家侦探，说话简短克制，观察力极强", "goal": "找出真凶"},
            {"name": "陈默", "persona": "话多冲动的记者，爱抢话、爱煽动气氛", "goal": "抢到独家新闻"},
            {"name": "沈薇", "persona": "阴郁沉默的富家女，似乎藏着不可告人的秘密", "goal": "隐瞒某个真相"},
        ],
        "opening": "暴雨夜，山中别墅突然断电。主人沈薇点起蜡烛，冷眼扫过在座的每一个人——他们当中，有人半小时前杀死了管家。",
    }


def load_config():
    """读取角色配置（只读）。文件不存在时才生成示例，绝不覆盖已有配置。"""
    if not os.path.exists(CONFIG_FILE):
        cfg = _default_config()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"✨ 首次运行，已生成示例角色配置文件：{CONFIG_FILE}\n   直接编辑它换人物/开场（该文件运行中不会被改动）。")
        return cfg
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def opening_text(cfg):
    """取开场正文：优先 opening，其次兼容旧版的 manuscript 字段。"""
    return (cfg.get("opening") or cfg.get("manuscript") or "").strip()


def new_run_dir():
    """为本次运行创建一个按日期时间命名的输出目录（同秒冲突时加序号）。"""
    os.makedirs(RUNS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(RUNS_DIR, stamp)
    n = 2
    while os.path.exists(d):
        d = os.path.join(RUNS_DIR, f"{stamp}_{n}")
        n += 1
    os.makedirs(d)
    return d


def init_run(cfg):
    """基于配置初始化本次运行的状态（不碰配置文件）。"""
    run_dir = new_run_dir()
    chars = cfg.get("characters") or []
    state = {
        "title": cfg.get("title", "未命名"),
        "characters": chars,
        "manuscript": opening_text(cfg),
        "summary": "",
        "summarized_len": 0,
        "current": chars[0]["name"] if chars else "",
    }
    return run_dir, state


def save_state(state, run_dir):
    """保存本次运行进度到 runs/<时间戳>/，并把正文导出为 manuscript.txt。"""
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    title = state.get("title", "未命名")
    with open(os.path.join(run_dir, "manuscript.txt"), "w", encoding="utf-8") as f:
        f.write(f"《{title}》\n\n" + state.get("manuscript", ""))


def extract_json(raw):
    """从模型输出里稳健地抠出 JSON 对象（兼容代码围栏、前后废话、嵌套引号）。"""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    start = raw.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except Exception:
                        return None
    return None


def names(state):
    return [c["name"] for c in state["characters"]]


def fallback_next(state, current):
    ns = names(state)
    if current in ns:
        return ns[(ns.index(current) + 1) % len(ns)]
    return ns[0]


def persona_lines(state):
    return "\n".join(
        f"- {c['name']}：{c.get('persona', '')}（目标：{c.get('goal', '')}）"
        for c in state["characters"]
    )


def recent_manuscript(state):
    """取「最近正文」：从上次压缩点之后的内容里截最后 RECENT_CHARS 字。"""
    man = state.get("manuscript", "")
    summarized = state.get("summarized_len", 0)
    return man[summarized:][-RECENT_CHARS:]


def build_llm(format_json=False, repeat_penalty=None):
    """构造对话模型。format_json=True 时让 Ollama 强制输出 JSON（旧版不支持则回退）。"""
    kwargs = dict(
        model=config.LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=config.LLM_TEMPERATURE,
        num_ctx=config.LLM_NUM_CTX,
    )
    if repeat_penalty is not None:
        kwargs["repeat_penalty"] = repeat_penalty
        kwargs["repeat_last_n"] = 256
    if format_json:
        try:
            return ChatOllama(format="json", **kwargs)
        except TypeError:
            pass
    return ChatOllama(**kwargs)


def generate_turn(state, speaker, llm):
    """让模型写出「旁白推进 + speaker 反应」这一段，返回 (dict, raw)；失败返回 (None, raw)。"""
    ns = names(state)
    prompt = f"""【人物卡】
{persona_lines(state)}

【可选角色（next 只能从中选）】：{'、'.join(ns)}

【剧情摘要】
{state.get('summary') or '（无）'}

【最近正文】
{recent_manuscript(state)}

现在请推进剧情，并让「{speaker}」做出反应。只输出 JSON。"""
    messages = [("system", DIRECTOR_SYSTEM), ("human", prompt)]
    try:
        raw = llm.invoke(messages).content
    except Exception as e:
        print(f"⚠️  生成失败：{e}")
        return None, ""
    data = extract_json(raw)
    if not isinstance(data, dict):
        print(f"⚠️  模型输出无法解析为 JSON，原文：\n{raw[:300]}")
        return None, raw
    return data, raw


def compress_if_needed(state, llm):
    """未压缩正文过长时，把旧正文折进「叙事体摘要」；正文本身一字不删。"""
    man = state.get("manuscript", "")
    summarized = state.get("summarized_len", 0)
    unsummarized = man[summarized:]
    if len(unsummarized) <= SUMMARIZE_AT_CHARS:
        return
    fold = unsummarized[: len(unsummarized) - RECENT_CHARS]
    if not fold:
        return
    prompt = f"""【既有摘要】
{state.get('summary') or '（无）'}

【新增正文】
{fold}"""
    messages = [("system", SUMMARY_SYSTEM), ("human", prompt)]
    try:
        raw = llm.invoke(messages).content
        state["summary"] = raw.strip()
        state["summarized_len"] = summarized + len(fold)
        print(f"🧠 已将 {len(fold)} 字旧正文压缩进叙事摘要（正文共 {len(man)} 字，未删任何内容）。")
    except Exception as e:
        print(f"⚠️  摘要生成失败：{e}")


def print_state(state):
    tail = "｜已有摘要" if state.get("summary") else ""
    print(f"📖 《{state['title']}》  人物：{'、'.join(names(state))}  正文 {len(state.get('manuscript', ''))} 字{tail}")


def main():
    cfg = load_config()
    if not cfg.get("characters"):
        print("⚠️  角色配置里没有 characters，请先编辑 story_state.json。")
        return
    run_dir, state = init_run(cfg)

    summary_llm = build_llm(format_json=False)
    director_llm = build_llm(format_json=True, repeat_penalty=config.LLM_REPEAT_PENALTY)

    print_state(state)
    print(f"📁 本次输出目录：{run_dir}")
    print("✅ 就绪！回车继续（下一个角色由模型决定），输入 /help 看命令。\n")

    ns = names(state)
    current = state.get("current") if state.get("current") in ns else ns[0]
    print(f"🎬 当前出场角色：{current}（可用 /next 名字 换）")

    while True:
        try:
            cmd = input("⏎ 回车继续 / 命令：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 已保存，再见！")
            save_state(state, run_dir)
            break

        if cmd in ("/exit", "/quit", "/q"):
            save_state(state, run_dir)
            print(f"👋 已保存，正文见 {os.path.join(run_dir, 'manuscript.txt')}。再见！")
            break
        if cmd == "/help":
            print("命令：（回车）继续 · /next 名字 · /scene 描述 · /characters · /manuscript · /save · /exit")
            continue
        if cmd in ("/characters", "/c"):
            print("👥 人物卡：\n" + persona_lines(state))
            continue
        if cmd in ("/manuscript", "/m", "/novel"):
            print("📜 当前正文：\n\n" + state.get("manuscript", ""))
            continue
        if cmd == "/save":
            save_state(state, run_dir)
            print(f"💾 已保存，正文见 {os.path.join(run_dir, 'manuscript.txt')}。")
            continue
        if cmd.startswith("/next"):
            name = cmd[len("/next"):].strip()
            if name not in ns:
                print(f"⚠️  没有这个角色，可用：{'、'.join(ns)}")
                continue
            current = name
            state["current"] = current
        elif cmd.startswith("/scene"):
            text = cmd[len("/scene"):].strip()
            if not text:
                print("用法：/scene 一段旁白描述")
                continue
            state["manuscript"] = state.get("manuscript", "") + text.strip() + "\n\n"
            save_state(state, run_dir)
            print(f"🎬 已插入旁白：{text}")
            continue
        elif cmd:
            print("未知命令，输入 /help 查看。")
            continue

        # ---- 生成「旁白推进 + 当前角色反应」这一小段 ----
        print(f"✍️  轮到【{current}】……", flush=True)
        data, raw = generate_turn(state, current, director_llm)
        if data is None:
            current = fallback_next(state, current)
            state["current"] = current
            save_state(state, run_dir)
            continue

        speaker = data.get("character")
        if speaker not in ns:
            speaker = current
        narrator = (data.get("narrator") or "").strip()
        text = (data.get("text") or "").strip()
        if not text:
            print(f"⚠️  模型返回了空 text（原文：{raw[:300]}）")
            text = "（沉默）"

        man = state.get("manuscript", "")
        if narrator:
            man += narrator.strip() + "\n\n"
            print(f"📝 旁白：{narrator}")
        man += text.strip() + "\n\n"
        state["manuscript"] = man
        print(f"【{speaker}】{text}\n")

        # ---- 判断下一个角色 ----
        nxt = data.get("next")
        if nxt in ns and nxt != speaker:
            current = nxt
        elif nxt == speaker:
            current = fallback_next(state, speaker)
            print(f"⚠️  模型让 {speaker} 连续出场，已强制换到 {current}。")
        else:
            current = fallback_next(state, speaker)
            if nxt:
                print(f"⚠️  模型给出的 next「{nxt}」不合法，已回退到 {current}。")

        state["current"] = current
        save_state(state, run_dir)
        compress_if_needed(state, summary_llm)
        save_state(state, run_dir)


if __name__ == "__main__":
    main()
