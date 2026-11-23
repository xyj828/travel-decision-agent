"""
高德工具自检脚本（不依赖大模型，不消耗 AI 网关额度）

用法：
    .venv\\Scripts\\python.exe scripts\\check_amap_tools.py
    .venv\\Scripts\\python.exe scripts\\check_amap_tools.py --location "红莲南路地铁站" --brands "倍轻松,西厅村屋"

它会依次验证：Key 是否可用、地点能否解析、商场能否检索、品牌能否匹配、距离能否计算、一站式推荐是否正常。
任何一步失败都会打印高德返回的真实错误码，方便排查。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_tools():
    """按文件路径加载 agents/_tools.py（避免与 openai-agents 的同名包冲突）。"""
    spec = importlib.util.spec_from_file_location("amap_tools", ROOT / "agents" / "_tools.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def call(tool, **kwargs) -> dict:
    """直接调用工具函数本体（跳过 SDK 包装，避免依赖运行时 trace 上下文）。"""
    try:
        raw = tool.__wrapped__(**kwargs)
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要把任何异常都打出来
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"工具返回非 JSON：{raw!r}"}


def show(title: str, data: dict, limit: int = 900) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) > limit:
        text = text[:limit] + "\n  ... (已截断)"
    print(f"\n--- {title} ---\n{text}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", default="红莲南路地铁站", help="起点地点")
    parser.add_argument("--brands", default="倍轻松,西厅村屋", help="要核对的品牌，逗号分隔")
    parser.add_argument("--radius", type=int, default=5000, help="商场搜索半径（米）")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key = (os.getenv("AMAP_API_KEY") or "").strip()
    if not key:
        print("[FAIL] 未在 .env 中配置 AMAP_API_KEY。")
        print("       高德开放平台 → 应用管理 → 我的应用 → 添加 Key → 服务平台选「Web服务」，")
        print(f"       然后把 Key 填到 {ROOT / '.env'} 的 AMAP_API_KEY= 后面。")
        return 2
    print(f"[OK] 已读取 AMAP_API_KEY（长度 {len(key)}，不打印内容）")

    tools = load_tools()

    # 0) 工具 schema 是否可正常生成（决定模型能否正确调用）
    for name in (
        "resolve_location",
        "search_nearby_malls",
        "match_brands_in_mall",
        "get_travel_distance",
        "find_nearest_brand_store",
        "find_malls_with_all_brands",
    ):
        tool = getattr(tools, name)
        props = list(tool.params_json_schema.get("properties", {}))
        print(f"[OK] schema {name}: {props}")

    failures = 0

    loc = call(tools.resolve_location, location=args.location)
    show("1) resolve_location", loc)
    if not loc.get("ok"):
        print("\n定位失败，后续检查无法进行。请按上面的错误提示修正 Key 或地点名称。")
        return 1
    lng, lat = loc["lng"], loc["lat"]

    malls = call(tools.search_nearby_malls, lng=lng, lat=lat, radius_m=args.radius)
    show("2) search_nearby_malls", malls)
    if not malls.get("ok") or malls.get("count", 0) == 0:
        failures += 1

    brands = [b.strip() for b in args.brands.replace("，", ",").split(",") if b.strip()]
    mall_list = malls.get("malls") or []
    if mall_list:
        first = mall_list[0]
        mall_lng, mall_lat = [float(x) for x in first["location"].split(",")]
        match = call(
            tools.match_brands_in_mall,
            mall_name=first["name"],
            mall_lng=mall_lng,
            mall_lat=mall_lat,
            brands=",".join(brands),
        )
        show("3) match_brands_in_mall", match)
        if not match.get("ok"):
            failures += 1

        dist = call(
            tools.get_travel_distance,
            origin=f"{lng},{lat}",
            destination=f"{mall_lng},{mall_lat}",
            mode="driving",
        )
        show("4) get_travel_distance", dist)
        if not dist.get("ok"):
            failures += 1

    nearest = call(
        tools.find_nearest_brand_store,
        brand=brands[0],
        location=args.location,
        radius_m=max(args.radius, 8000),
    )
    show("5) find_nearest_brand_store", nearest)
    if not nearest.get("ok") or nearest.get("count", 0) == 0:
        failures += 1

    combo = call(
        tools.find_malls_with_all_brands,
        location=args.location,
        brands=",".join(brands),
        radius_m=args.radius,
    )
    show("6) find_malls_with_all_brands", combo, limit=1500)
    if not combo.get("ok"):
        failures += 1

    print("\n===== 结果 =====")
    if failures:
        print(f"有 {failures} 项检查未通过，请看上面的错误信息。")
        return 1
    print("全部工具调用成功，Agent 的地图能力已就绪。")
    if combo.get("best"):
        print(f"推荐：{combo['best']['mall']}（约 {combo['best']['distance_m']} 米）")
    else:
        print("未找到同时满足全部品牌的商场（这是真实结果，不是报错）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
