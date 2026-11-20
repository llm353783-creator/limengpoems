# -*- coding: utf-8 -*-
"""
build_data.py —— 把三份原始 CSV 转成网站可直接读取的数据文件
==================================================
输入（data/ 目录，原始文件不做任何改写）：
    李白.csv           4 列，无表头：[诗题, 诗句, 诗歌id, 诗句序号(0 起)]
    孟浩然.csv         同结构
    李白-孟浩然.csv    11 列，无表头：[李白, 诗题, 诗句, 孟浩然, 诗题, 诗句,
                                    G(相似度,10000制), H(李白诗id), I(李白句id,0起),
                                    J(孟诗id), K(孟诗句id,0起)]

输出：
    data/data.json   完整结构化数据
    data/data.js     window.SITE_DATA = {...}（页面直接用 script 引入，双击也能打开）

原则：
    * 只读，不改写任何原始单元格；
    * 诗句一律按 (诗id, 句序号) 回查原始 CSV 取原文，不做拼补、不做校改；
    * 句内索引保持 0 起（0-base），+1 只在前端展示时发生。
"""
import csv
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
TARGET_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


def open_csv(path):
    """按候选编码打开，返回行列表。"""
    last_err = None
    for enc in TARGET_ENCODINGS:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = list(csv.reader(f))
            if rows:
                return rows
        except UnicodeDecodeError as e:
            last_err = e
    raise RuntimeError("无法读取 %s: %s" % (path, last_err))


def load_single(path):
    """读取单诗人表：返回 {诗id: {title, sentences[], sent_map{}}}"""
    rows = open_csv(path)
    poems = {}
    for row in rows:
        if len(row) < 4:
            continue
        title, sentence, pid, idx = row[0].strip(), row[1], row[2].strip(), row[3].strip()
        if not pid.isdigit() or not idx.lstrip("-").isdigit():
            continue  # 跳过表头或异常行
        idx = int(idx)
        p = poems.setdefault(pid, {"title": title, "sentences": {}, "max_idx": -1})
        p["sentences"][idx] = sentence
        if idx > p["max_idx"]:
            p["max_idx"] = idx
        if not p["title"] and title:
            p["title"] = title
    # 句数组按原始索引留空补齐，保证下标即 CSV 句序号
    for pid, p in poems.items():
        arr = [""] * (p["max_idx"] + 1)
        for i, s in p["sentences"].items():
            arr[i] = s
        p["sentences"] = arr
        p.pop("max_idx", None)
    return poems


def main():
    li_path = os.path.join(DATA_DIR, "李白.csv")
    meng_path = os.path.join(DATA_DIR, "孟浩然.csv")
    pair_path = os.path.join(DATA_DIR, "李白-孟浩然.csv")
    for p in (li_path, meng_path, pair_path):
        if not os.path.exists(p):
            sys.exit("缺少文件：%s" % p)

    li_poems = load_single(li_path)
    meng_poems = load_single(meng_path)
    rows = open_csv(pair_path)

    pairs = []
    bad = 0
    g_min = None
    g_max = None
    for row in rows:
        if len(row) < 11:
            bad += 1
            continue
        g_raw, lid, lsid, mid, msid = row[6], row[7], row[8], row[9], row[10]
        if not (g_raw.strip().isdigit() and lid.strip().isdigit()
                and lsid.strip().isdigit() and mid.strip().isdigit()
                and msid.strip().isdigit()):
            bad += 1  # 表头或脏行
            continue
        g = int(g_raw)
        lid, lsid, mid, msid = lid.strip(), int(lsid), mid.strip(), int(msid)

        li_poem = li_poems.get(lid)
        meng_poem = meng_poems.get(mid)
        if li_poem is None or meng_poem is None:
            bad += 1
            continue
        li_sents, meng_sents = li_poem["sentences"], meng_poem["sentences"]
        if lsid >= len(li_sents) or msid >= len(meng_sents):
            bad += 1
            continue

        pairs.append({
            "g_raw": g,
            "li_poem_id": lid,
            "li_sent_idx": lsid,
            "meng_poem_id": mid,
            "meng_sent_idx": msid,
            "li_sent": li_sents[lsid],
            "meng_sent": meng_sents[msid],
        })
        g_min = g if g_min is None else min(g_min, g)
        g_max = g if g_max is None else max(g_max, g)

    # 诗级统计（章节 02 / 04 直接读这里，不在前端硬写数字）
    stat = defaultdict(lambda: {"pairs": 0, "max_g": 0, "chars": 0})
    for p in pairs:
        for side, pid in (("li", p["li_poem_id"]), ("meng", p["meng_poem_id"])):
            s = stat[(side, pid)]
            s["pairs"] += 1
            s["max_g"] = max(s["max_g"], p["g_raw"])

    poem_stat = {}
    for (side, pid), s in stat.items():
        src = li_poems if side == "li" else meng_poems
        poem_stat["%s:%s" % (side, pid)] = {
            "side": side,
            "poem_id": pid,
            "title": src[pid]["title"],
            "pairs": s["pairs"],
            "max_g": s["max_g"],
            "sent_count": len([x for x in src[pid]["sentences"] if x]),
        }

    out = {
        "meta": {
            "li_poems": len(li_poems),
            "meng_poems": len(meng_poems),
            "li_sentences": sum(len([x for x in p["sentences"] if x]) for p in li_poems.values()),
            "meng_sentences": sum(len([x for x in p["sentences"] if x]) for p in meng_poems.values()),
            "pairs": len(pairs),
            "g_min": g_min,
            "g_max": g_max,
            "skipped_rows": bad,
        },
        "li_poems": {pid: {"title": p["title"], "sentences": p["sentences"]} for pid, p in li_poems.items()},
        "meng_poems": {pid: {"title": p["title"], "sentences": p["sentences"]} for pid, p in meng_poems.items()},
        "poem_stat": poem_stat,
        "pairs": pairs,
    }

    json_path = os.path.join(DATA_DIR, "data.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    js_path = os.path.join(DATA_DIR, "data.js")
    with open(js_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("/* 由 tools/build_data.py 从三份原始 CSV 生成，请勿手工编辑 */\n")
        f.write("window.SITE_DATA = ")
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    m = out["meta"]
    print("[ok] 李白 %d 首 / %d 句" % (m["li_poems"], m["li_sentences"]))
    print("[ok] 孟浩然 %d 首 / %d 句" % (m["meng_poems"], m["meng_sentences"]))
    print("[ok] 互文句对 %d 组（G 范围 %s-%s），跳过异常行 %d" % (m["pairs"], m["g_min"], m["g_max"], m["skipped_rows"]))
    print("[ok] 输出：data/data.json / data/data.js")


if __name__ == "__main__":
    main()
