"""ゆるマッチングの「みんなで話せそうな話題」を、文章レベルで4〜5個つくる。

背景(かずさん、2026-10-14): 3〜4人で話すと、2人だけの共通点の話題は2人だけが話して
残りが聞くだけになりがちで、実際にはそういう流れになりにくい。そこで以前の
「(Aさん×Bさん) 共通の興味「読書」の話で…」という2人組ごとの話題(pairwise_topics)を
やめ、グループの3人以上(4人グループなら4人中3人以上)が乗れる話題だけを、タグ名ではなく
「そのまま投げかけられる問いかけの文」として出す。

LLM APIは使わない(従量課金を避ける、かずさんの判断)。タグの値は「旅行/海外旅行/国内旅行/
世界一周」のように表記がばらけていて、値の完全一致だと3人以上はまず重ならないため、
タグ値と自己紹介文をキーワードで大きめのテーマ(THEMES)に寄せてから重なりを数える。
優先順:
  1. 3人以上で完全一致するタグ(questions_for_tagの質問文)
  2. FIRE済の人とこれからの人が混ざっている → 経験者に聞いてみる話題
  3. 3人以上が当てはまるテーマ(テーマごとの問いかけからランダム)
  4. F研メンバーなら誰でも乗れる汎用の問いかけ(ランダム)で4個まで埋める

各話題は {"text": str, "members": [nickname, ...], "source": "tag" | "fire_mix" | "theme" | "generic"}。
members がグループ全員と同じなら表示側で名前を省略する(format_topic_line)。
"""

from __future__ import annotations

import random
from typing import Any

from yuru_talk_questions import questions_for_tag

MAX_GROUP_TOPICS = 5
MIN_GROUP_TOPICS = 4
# 4人グループなら3人以上。2人だけの共通点は話題にしない(上のdocstring参照)。
MIN_TOPIC_MEMBERS = 3

# 完全一致のタグから作る話題に使うカテゴリ(run_member_matching.TOPIC_TAG_CATEGORIESと同じ並び)。
# affiliation(所属チーム・部活)は使わない: そのチームには定期ミーティングがあって話す場は足りているうえ、
# チームにいない人からすると内輪ネタになる(かずさんの判断、2026-10-14)。テーマ判定・詳細の材料からも外す。
EXACT_TAG_CATEGORIES = ["interest", "chat_topic", "investment_style", "skill", "fire_status", "mbti"]
# テーマ判定に使うカテゴリ。consultation(相談できること)は不妊治療・持病など踏み込んだ内容が
# 入っているので使わない。mbtiは記号なので対象外。
THEME_TAG_CATEGORIES = ["interest", "chat_topic", "investment_style", "skill", "wants_to_know"]

# キーワードはタグ値・自己紹介文への部分一致。自己紹介文にも当てるので、「本」(日本)や「IT」
# のように別の語に含まれやすい短い語は入れない。健康・家族の踏み込んだ話題(病気・妊活など)は
# 初対面の雑談に向かないのでテーマにしない。
THEMES: list[dict[str, Any]] = [
    {
        "key": "travel",
        "label": "旅行",
        "keywords": ["旅行", "世界一周", "温泉", "百名城", "都道府県", "マイレージ", "観光", "旅"],
        "questions": [
            "これまで行った中で、もう一度行きたい場所はどこですか？",
            "次に行ってみたい旅先や、旅の予定はありますか？",
            "旅先でのお金の使い方で、ケチらないと決めているものはありますか？",
        ],
    },
    {
        "key": "exercise",
        "label": "運動・健康",
        "keywords": ["筋トレ", "ウォーキング", "ランニング", "マラソン", "水泳", "ヨガ", "ピラティス", "バドミントン",
                     "テニス", "ゴルフ", "自転車", "ロードバイク", "サーフィン", "ダイエット", "ハイキング", "登山", "散歩"],
        "questions": [
            "体を動かす習慣で、続いているものはありますか？",
            "健康のために、お金や時間をかけていることはありますか？",
        ],
    },
    {
        "key": "reading",
        "label": "本・マンガ",
        "keywords": ["読書", "マンガ", "漫画", "読書部", "書道", "文学"],
        "questions": [
            "最近読んでよかった本やマンガはありますか？",
            "人生やお金の考え方が変わった一冊はありますか？",
        ],
    },
    {
        "key": "writing",
        "label": "発信・執筆",
        "keywords": ["note", "ブログ", "YouTube", "発信", "Kindle", "kindle", "出版", "ラジオ", "執筆"],
        "questions": [
            "発信や執筆を続けていて、よかったこと・大変なことは何ですか？",
            "書いたり話したりするネタは、どうやって見つけていますか？",
        ],
    },
    {
        "key": "food",
        "label": "食・料理",
        "keywords": ["料理", "グルメ", "食べ歩き", "ランチ", "カフェ", "ワイン", "お酒", "スナック", "家庭菜園", "調理"],
        "questions": [
            "最近おいしかったお店や、よく作る料理はありますか？",
            "食費はどこまでかける派・どこで抑える派ですか？",
        ],
    },
    {
        "key": "games",
        "label": "ゲーム",
        "keywords": ["ゲーム", "麻雀", "マーダーミステリー", "スプラ", "ボードゲーム"],
        "questions": [
            "最近遊んでいるゲームや、みんなでできる遊びはありますか？",
        ],
    },
    {
        "key": "index",
        "label": "インデックス投資・積立",
        "keywords": ["インデックス", "オルカン", "S&P500", "NISA", "iDeCo", "投資信託", "企業型DC", "つみたて"],
        "questions": [
            "NISAやiDeCoなどの制度、どう使い分けていますか？",
            "積立投資を続けるうえで、気持ちの面で工夫していることはありますか？",
            "暴落のとき、どんなふうに過ごしていましたか？",
        ],
    },
    {
        "key": "dividend",
        "label": "高配当・優待",
        "keywords": ["高配当", "個別株", "優待", "日本株", "配当"],
        "questions": [
            "配当や株主優待で、もらってうれしかったものはありますか？",
            "個別株を選ぶとき、どんなところを見ていますか？",
        ],
    },
    {
        "key": "living",
        "label": "暮らし・移住",
        "keywords": ["移住", "二拠点", "多拠点", "地方", "海外生活", "田舎", "果樹園", "養鶏", "養蜂"],
        "questions": [
            "住む場所や暮らし方を変えたこと、変えてみたいことはありますか？",
            "FIRE後に住んでみたい場所はありますか？",
        ],
    },
    {
        "key": "real_estate",
        "label": "不動産・住まい",
        "keywords": ["不動産", "物件", "賃貸", "持ち家", "住宅ローン"],
        "questions": [
            "賃貸派・持ち家派、それぞれどんな理由で選んでいますか？",
            "住まいにかけるお金は、どのくらいが心地いいと思いますか？",
        ],
    },
    {
        "key": "work",
        "label": "副業・起業",
        "keywords": ["副業", "起業", "法人", "フリーランス", "独立", "経営", "コンサル", "マーケティング", "事務代行"],
        "questions": [
            "本業以外で、やっている・やってみたい仕事はありますか？",
            "会社員以外の稼ぎ方で、気になっているものはありますか？",
        ],
    },
    {
        "key": "tech",
        "label": "AI・テック",
        "keywords": ["AI", "プログラミング", "Vibe coding", "エンジニア", "開発"],
        "questions": [
            "仕事や生活で、AIをどんなふうに使っていますか？",
        ],
    },
    {
        "key": "culture",
        "label": "映画・音楽・アート",
        "keywords": ["音楽", "映画", "美術館", "観劇", "ライブ", "ドラム", "ギター", "ピアノ", "DJ", "アニメ"],
        "questions": [
            "最近見てよかった映画やライブ、展示はありますか？",
        ],
    },
    {
        "key": "outdoor",
        "label": "アウトドア・畑",
        "keywords": ["キャンプ", "釣り", "園芸", "アウトドア", "狩猟", "漁業"],
        "questions": [
            "休みの日に外で過ごすなら、どんなことをしていますか？",
        ],
    },
    {
        "key": "parenting",
        "label": "子育て",
        "keywords": ["子育て", "育児", "育休"],
        "questions": [
            "子育てとお金・時間のバランスで、工夫していることはありますか？",
        ],
    },
]

# fire_statusの値から「FIRE済側」「これから側」を見分ける語。どちらにも当たらない値は無視する。
FIRE_DONE_WORDS = ["FIRE済", "FI済", "セミリタイア", "コーストFIRE"]
FIRE_AHEAD_WORDS = ["目指し", "準備", "検討", "会社員"]

# F研メンバーなら誰でも乗れる話題。上の3段で4つに届かないときの埋め草。
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
    "住む場所を自由に選べるとしたら、どこに住んでみたいですか？",
]


def _ordered(nicknames: list[str], subset: set[str] | list[str]) -> list[str]:
    return [n for n in nicknames if n in subset]


def _exact_tag_topics(members: list[dict[str, Any]], nicknames: list[str], min_members: int) -> list[dict[str, Any]]:
    holders: dict[tuple[str, str], set[str]] = {}
    for category in EXACT_TAG_CATEGORIES:
        for member in members:
            for value in set((member.get("tags") or {}).get(category, [])):
                holders.setdefault((category, value), set()).add(member["nickname"])
    shared = [(c, v, names) for (c, v), names in holders.items() if len(names) >= min_members]
    shared.sort(key=lambda t: (-len(t[2]), EXACT_TAG_CATEGORIES.index(t[0]), t[1]))
    return [
        {"text": _exact_tag_question(category, value), "members": _ordered(nicknames, names), "source": "tag", "value": value}
        for category, value, names in shared
    ]


def _exact_tag_question(category: str, value: str) -> str:
    return questions_for_tag(value, category)[0]


def _fire_mix_topic(members: list[dict[str, Any]], nicknames: list[str]) -> dict[str, Any] | None:
    done, ahead = [], []
    for member in members:
        statuses = (member.get("tags") or {}).get("fire_status", [])
        if any(w in s for s in statuses for w in FIRE_AHEAD_WORDS):
            ahead.append(member["nickname"])
        elif any(w in s for s in statuses for w in FIRE_DONE_WORDS):
            done.append(member["nickname"])
    if not done or not ahead:
        return None
    done_names = "・".join(f"{n}さん" for n in done)
    return {
        "text": f"FIRE済の{done_names}に、FIRE前にやっておいてよかったこと・FIRE後に意外だったことを聞いてみませんか？",
        "members": list(nicknames),
        "source": "fire_mix",
    }


THEME_BY_KEY = {theme["key"]: theme for theme in THEMES}


# 部分一致で別のテーマのキーワードを含んでしまう語(「プランニング」⊃「ランニング」など)。判定前に取り除く。
FALSE_POSITIVE_WORDS = ["プランニング", "旅館業"]


def _clean(text: str) -> str:
    for word in FALSE_POSITIVE_WORDS:
        text = text.replace(word, "")
    return text


def _has_keyword(text: str, keywords: list[str]) -> bool:
    text = _clean(text)
    return any(kw in text for kw in keywords)


def themes_in_text(text: str) -> set[str]:
    """文章にキーワードが含まれるテーマのkey(部分一致)。投稿の取り込み(sync_member_interest_signals.py)でも使う。"""
    return {theme["key"] for theme in THEMES if _has_keyword(text, theme["keywords"])}


def profile_themes(member: dict[str, Any]) -> set[str]:
    """タグ値と自己紹介文から判定したテーマ。"""
    texts = [v for c in THEME_TAG_CATEGORIES for v in (member.get("tags") or {}).get(c, [])]
    if member.get("intro"):
        texts.append(member["intro"])
    return set().union(*(themes_in_text(t) for t in texts)) if texts else set()


def member_themes(member: dict[str, Any]) -> set[str]:
    """プロフィール由来のテーマ + 最近のDiscord/note投稿由来のテーマ(member["recent_themes"])。"""
    return profile_themes(member) | set(member.get("recent_themes") or [])


def _theme_topics(
    members: list[dict[str, Any]], nicknames: list[str], min_members: int, rng: random.Random, covered_values: list[str],
) -> list[dict[str, Any]]:
    holders: dict[str, set[str]] = {}
    for member in members:
        for key in member_themes(member):
            holders.setdefault(key, set()).add(member["nickname"])
    topics = []
    for index, theme in enumerate(THEMES):
        names = holders.get(theme["key"], set())
        if len(names) < min_members:
            continue
        # 完全一致タグの話題(例: インデックス投資)で既に出ているテーマは重ねない
        if any(kw in value for kw in theme["keywords"] for value in covered_values):
            continue
        topics.append((len(names), index, {
            "text": f"【{theme['label']}】{rng.choice(theme['questions'])}",
            "members": _ordered(nicknames, names),
            "source": "theme",
        }))
    topics.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in topics]


def build_group_topics(members: list[dict[str, Any]], rng: random.Random | None = None) -> list[dict[str, Any]]:
    """グループの3人以上が乗れる話題を、優先順(モジュールdocstring参照)に最大MAX_GROUP_TOPICS個。"""
    rng = rng or random.Random()
    nicknames = [m["nickname"] for m in members]
    min_members = min(MIN_TOPIC_MEMBERS, len(nicknames))

    topics = _exact_tag_topics(members, nicknames, min_members)
    fire_mix = _fire_mix_topic(members, nicknames)
    if fire_mix:
        topics.append(fire_mix)
    covered = [t["value"] for t in topics if "value" in t]
    topics.extend(_theme_topics(members, nicknames, min_members, rng, covered))

    seen: set[str] = set()
    unique = []
    for topic in topics:
        if topic["text"] not in seen:
            seen.add(topic["text"])
            unique.append({k: v for k, v in topic.items() if k != "value"})
    for text in rng.sample(GENERIC_GROUP_TOPICS, len(GENERIC_GROUP_TOPICS)):
        if len(unique) >= MIN_GROUP_TOPICS:
            break
        if text not in seen:
            unique.append({"text": text, "members": list(nicknames), "source": "generic"})
    return unique[:MAX_GROUP_TOPICS]


def format_topic_line(topic: dict[str, Any], group_nicknames: list[str]) -> str:
    """Discord/画面用の1行。グループ全員が対象なら名前は省略し、3人だけの話題には名前を添える。

    以前は各話題の下に「かずさん: 自己紹介に『出版』 ／ …」という根拠の詳細行も出していたが、
    冗長なのでやめた(かずさんのフィードバック、2026-10-14)。具体性は「この人に聞いてみたい」で補う。
    """
    members = topic.get("members") or []
    if not members or set(members) >= set(group_nicknames):
        return topic["text"]
    return f"{topic['text']}（{'・'.join(f'{n}さん' for n in members)}）"
