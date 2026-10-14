"""ゆるマッチングの「みんなで話せそうな話題」を、文章レベルで4〜5個つくる。

背景(かずさん、2026-10-14): 3〜4人で話すと、2人だけの共通点の話題は2人だけが話して
残りが聞くだけになりがちで、実際にはそういう流れになりにくい。そこで以前の
「(Aさん×Bさん) 共通の興味「読書」の話で…」という2人組ごとの話題(pairwise_topics)を
やめ、グループの3人以上(4人グループなら4人中3人以上)が乗れる話題だけを、タグ名ではなく
「そのまま投げかけられる問いかけの文」として出す。

生成は2段構え:
  1. ANTHROPIC_API_KEY があれば、メンバーのタグ・自己紹介文をClaudeに渡して文章で生成する
     (generate_with_claude)。根拠のメンバー名を必ず付けさせ、3人以上に関係しない話題や
     グループ外の名前が混ざったものはこちらで捨てる。
  2. キーが無い・API失敗・件数不足のときは、タグの重なりと汎用の話題から機械的に作る
     (rule_based_topics)。マッチング告知自体を止めないため、こちらは必ず何か返す。

各話題は {"text": str, "members": [nickname, ...], "source": "claude" | "rule"}。
members がグループ全員と同じなら表示側で名前を省略する(format_topic_line)。
"""

from __future__ import annotations

import json
import os
import random
from typing import Any

from yuru_talk_questions import questions_for_tag

MAX_GROUP_TOPICS = 5
MIN_GROUP_TOPICS = 4
# 4人グループなら3人以上。2人だけの共通点は話題にしない(上のdocstring参照)。
MIN_TOPIC_MEMBERS = 3
CLAUDE_MODEL = "claude-opus-5-5"

# タグの重なりから作る話題に使うカテゴリ(run_member_matching.TOPIC_TAG_CATEGORIESと同じ並び)。
# mbti/fire_statusは「3人が同じMBTI」はまず起きないので実質ほぼ出ないが、出たら面白いので残す。
RULE_TAG_CATEGORIES = ["interest", "chat_topic", "investment_style", "affiliation", "skill", "fire_status", "mbti"]

# F研メンバーなら誰でも乗れる話題。タグの重なりだけで4つに届かないときの埋め草。
# 3人以上で重なるタグは実データではかなり珍しく(2026-10時点の直近グループでほぼ0〜1個)、
# 毎回同じ文面が並ばないよう、グループごとにここからランダムに選ぶ。
GENERIC_GROUP_TOPICS = [
    "FIREや資産形成を意識しはじめたきっかけは何でしたか？",
    "最近「これはお金をかけてよかった」と思えた使い方はありますか？",
    "F研に入ってみて、よかったことや意外だったことはありますか？",
    "FIREしたら(している人は、してみて)時間をいちばん使いたいことは何ですか？",
    "最近ハマっていることや、ちょっと始めてみたことはありますか？",
    "逆に「これは節約しない」と決めているものはありますか？",
    "休みの日は、どんなふうに過ごすことが多いですか？",
    "お金や働き方について、昔と今で考えが変わったことはありますか？",
    "最近読んだ本・見た動画で、おすすめしたいものはありますか？",
    "住む場所を自由に選べるとしたら、どこに住んでみたいですか？",
]

TAG_CATEGORY_LABELS = {
    "interest": "興味",
    "chat_topic": "話したい話題",
    "investment_style": "投資スタイル",
    "affiliation": "活動・部活",
    "skill": "得意なこと",
    "mbti": "MBTI",
    "fire_status": "FIREタイプ",
    "consultation": "相談に乗れること",
    "wants_to_know": "知りたいこと",
}

SYSTEM_PROMPT = """\
あなたはFIRE(経済的自立・早期リタイア)に関心がある人のオンラインコミュニティ「F研」で、
少人数のボイス雑談「ゆるマッチング」の話題づくりを手伝っています。
初対面に近い3〜4人が、全員で話を回せるきっかけを考えるのが役割です。

ルール:
- 話題は、グループのうち少なくとも3人(3人グループなら全員)に関係するものだけにする。
  2人だけの共通点は、残りの人が聞き役になってしまうので出さない。
- 各話題は、そのまま場に投げかけられる日本語の問いかけ1文(40〜70字程度、です・ます調)にする。
  「〇〇の話」のようなタグ名だけの書き方はしない。
- 根拠は、渡されたプロフィール(タグ・自己紹介文)に書かれている事実だけ。書かれていない興味を推測で足さない。
- members には、その話題の根拠になったメンバーのニックネームを、渡された表記どおりに入れる。
- 投資の売買判断や銘柄の推奨を求める聞き方(「買うべき？」など)は避け、経験や感想を聞く形にする。
- 収入・資産額・健康・家族の事情など踏み込んだ個人情報や、自己紹介文の引用は話題に入れない。
- 似た話題を重ねず、お金の話・暮らしや趣味の話などテーマを散らす。
"""


def _member_profile_text(member: dict[str, Any]) -> str:
    lines = [f"## {member['nickname']}"]
    for category, values in (member.get("tags") or {}).items():
        if values:
            label = TAG_CATEGORY_LABELS.get(category, category)
            lines.append(f"- {label}: {'、'.join(values)}")
    intro = (member.get("intro") or "").strip()
    if intro:
        lines.append(f"- 自己紹介文: {intro}")
    if len(lines) == 1:
        lines.append("- (プロフィール情報なし)")
    return "\n".join(lines)


TOPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "members": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "members"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["topics"],
    "additionalProperties": False,
}


def _valid_topics(raw_topics: list[dict[str, Any]], nicknames: list[str]) -> list[dict[str, Any]]:
    """グループ外の名前を含むもの・関係者が3人未満のもの・重複を捨てる。"""
    group = set(nicknames)
    min_members = min(MIN_TOPIC_MEMBERS, len(nicknames))
    seen_texts: set[str] = set()
    topics = []
    for topic in raw_topics:
        text = str(topic.get("text") or "").strip()
        # 「かずさん」のように敬称付きで返ってきても受け付ける
        raw_members = {
            m if m in group else str(m).removesuffix("さん") for m in (topic.get("members") or [])
        }
        if not raw_members <= group:
            continue  # グループ外の名前が混ざっている=根拠があやしいので使わない
        if not text or text in seen_texts or len(raw_members) < min_members:
            continue
        members = raw_members
        seen_texts.add(text)
        # 表示順をグループの並びにそろえる
        topics.append({"text": text, "members": [n for n in nicknames if n in members], "source": "claude"})
    return topics


def generate_with_claude(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claudeで話題を生成する。キーが無い・SDK未インストール・API失敗のときは空リスト。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return []
    try:
        import anthropic
    except ImportError:
        print("  anthropic SDK is not installed; using rule-based group topics.")
        return []

    nicknames = [m["nickname"] for m in members]
    user_prompt = (
        f"今回マッチしたのは次の{len(members)}人です。\n\n"
        + "\n\n".join(_member_profile_text(m) for m in members)
        + f"\n\n全員で話せそうな話題を{MAX_GROUP_TOPICS}個考えてください。"
    )
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": TOPICS_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIConnectionError as exc:
        print(f"  Claude API connection failed; using rule-based group topics: {exc}")
        return []
    except anthropic.APIStatusError as exc:
        print(f"  Claude API error {exc.status_code}; using rule-based group topics: {exc.message}")
        return []

    if response.stop_reason in ("refusal", "max_tokens"):
        print(f"  Claude stopped with {response.stop_reason}; using rule-based group topics.")
        return []
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        raw_topics = json.loads(text).get("topics", [])
    except json.JSONDecodeError:
        print("  Claude returned invalid JSON; using rule-based group topics.")
        return []
    return _valid_topics(raw_topics, nicknames)[:MAX_GROUP_TOPICS]


def rule_based_topics(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """タグの重なり(3人以上)→F研メンバー向けの汎用話題、の順で最大MAX_GROUP_TOPICS個。"""
    nicknames = [m["nickname"] for m in members]
    min_members = min(MIN_TOPIC_MEMBERS, len(nicknames))
    holders: dict[tuple[str, str], list[str]] = {}
    for category in RULE_TAG_CATEGORIES:
        for member in members:
            for value in set((member.get("tags") or {}).get(category, [])):
                holders.setdefault((category, value), []).append(member["nickname"])
    shared = [
        (category, value, names) for (category, value), names in holders.items() if len(names) >= min_members
    ]
    # 共有人数が多い順、同数ならカテゴリの優先順
    shared.sort(key=lambda t: (-len(t[2]), RULE_TAG_CATEGORIES.index(t[0]), t[1]))

    topics: list[dict[str, Any]] = []
    for category, value, names in shared:
        question = questions_for_tag(value, category)[0]
        topics.append({"text": question, "members": [n for n in nicknames if n in names], "source": "rule"})
        if len(topics) >= MAX_GROUP_TOPICS:
            return topics
    for text in random.sample(GENERIC_GROUP_TOPICS, len(GENERIC_GROUP_TOPICS)):
        if len(topics) >= MIN_GROUP_TOPICS:
            break
        topics.append({"text": text, "members": list(nicknames), "source": "rule"})
    return topics


def build_group_topics(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claudeの生成を優先し、MIN_GROUP_TOPICSに足りない分はルールベースで補う。"""
    topics = generate_with_claude(members)
    if len(topics) < MIN_GROUP_TOPICS:
        seen = {t["text"] for t in topics}
        for topic in rule_based_topics(members):
            if len(topics) >= MIN_GROUP_TOPICS:
                break
            if topic["text"] not in seen:
                topics.append(topic)
                seen.add(topic["text"])
    return topics[:MAX_GROUP_TOPICS]


def format_topic_line(topic: dict[str, Any], group_nicknames: list[str]) -> str:
    """Discord/画面用の1行。グループ全員が対象なら名前は省略する。"""
    members = topic.get("members") or []
    if not members or set(members) >= set(group_nicknames):
        return topic["text"]
    return f"{topic['text']}（{'・'.join(f'{n}さん' for n in members)}）"
